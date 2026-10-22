"""Tests de l'orchestrateur : un faux modèle joue le rôle de l'agent (sans réseau)."""

from __future__ import annotations

import json
from pathlib import Path

from agent.llm_providers import LLMError
from agent.process_requests import process_all
from agent.synthesis import format_synthesis
from agent.tests.fakes import WEDDING_NEEDS, FakeKit


class ListingKit(FakeKit):
    """Faux kit qui liste trois demandes."""

    def call(self, name: str, arguments: dict):
        if name == "lister_demandes":
            return {"nombre": 3, "demandes": [{"id": "dem_ok"}, {"id": "dem_ecart"}, {"id": "dem_panne"}]}
        if name == "lister_brouillons":
            return {"nombre": 0, "brouillons": []}
        return super().call(name, arguments)


class ScriptedAgent:
    """Faux modèle : appelle les outils comme le ferait l'agent, selon la demande."""

    model = "factice"

    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError

    def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
        request_id = user.split(":", 1)[1].strip()
        if request_id == "dem_panne":
            raise LLMError("quota dépassé")
        handlers = {spec.name: spec.handler for spec in tools}
        handlers["calc_devis"]({"besoins": WEDDING_NEEDS})
        needs = dict(WEDDING_NEEDS)
        if request_id == "dem_ecart":
            # La fiche ne correspond pas aux besoins chiffrés : le contrôle doit le voir.
            needs["chambres"] = [{"type": "simple", "nombre": 5}, {"type": "twin", "nombre": 1}]
        sheet = {"statut": "proposition", "besoins": needs, "brouillon_reponse": "Bonjour,\n\nVoici notre devis."}
        handlers["write_draft"]({"fiche_json": sheet})
        return json.dumps(sheet)


def run(tmp_path: Path, monkeypatch) -> list:
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    return process_all(ListingKit(), ScriptedAgent(), tmp_path)


def test_batch_checks_quote_and_survives_model_error(tmp_path: Path, monkeypatch) -> None:
    ok, gap, failed = run(tmp_path, monkeypatch)
    assert (ok.statut, ok.devis_total, ok.brouillon, ok.points_a_verifier) == ("proposition", 1980.0, "b001", [])
    assert "≠ recalcul" in gap.points_a_verifier[0]
    assert failed.statut == "erreur" and failed.points_a_verifier == ["quota dépassé"]


def test_synthesis_and_raw_results_written(tmp_path: Path, monkeypatch) -> None:
    run(tmp_path, monkeypatch)
    synthesis = (tmp_path / "synthese.md").read_text(encoding="utf-8")
    assert "Planning inchangé : oui" in synthesis
    assert "| dem_ok | proposition | 2026-12-13 → 2026-12-16 | — | — | 1980.00 | b001 |" in synthesis
    assert len(json.loads((tmp_path / "resultats.json").read_text(encoding="utf-8"))) == 3


def test_prompt_states_the_real_turn_limit() -> None:
    from datetime import date

    from agent.process_requests import MAX_STEPS, load_system_prompt

    prompt = load_system_prompt(date(2026, 10, 20))
    assert f"au plus {MAX_STEPS} tours" in prompt and "{max_tours}" not in prompt and "20/10/2026" in prompt


def test_synthesis_flags_changed_planning() -> None:
    assert "NON" in format_synthesis([], "factice", planning_unchanged=False)


def test_exhausted_quota_stops_batch_immediately(tmp_path: Path, monkeypatch) -> None:
    from agent.llm_providers.base import LLMQuotaError

    class QuotaAgent(ScriptedAgent):
        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            if "dem_ecart" in user:
                raise LLMQuotaError("quota du jour épuisé")
            return super().run_agent(system, user, tools, max_steps)

    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    ok, stopped, pending = process_all(ListingKit(), QuotaAgent(), tmp_path)
    assert (ok.statut, stopped.statut, pending.statut) == ("proposition", "erreur", "non_traitee")
    assert "lot arrêté" in pending.points_a_verifier[0]


def test_batch_error_after_write_draft_keeps_the_draft(tmp_path: Path, monkeypatch) -> None:
    from agent.llm_providers.base import LLMQuotaError

    class LateQuotaAgent(ScriptedAgent):
        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            answer = super().run_agent(system, user, tools, max_steps)
            if "dem_ok" in user:
                raise LLMQuotaError("quota épuisé après write_draft")
            return answer

    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    ok, *pending = process_all(ListingKit(), LateQuotaAgent(), tmp_path)
    assert (ok.statut, ok.devis_total, ok.brouillon) == ("proposition", 1980.0, "b001")
    assert "lot arrêté après write_draft" in ok.points_a_verifier[-1]
    assert [item.statut for item in pending] == ["non_traitee", "non_traitee"]


class PeekingAgent(ScriptedAgent):
    """Faux modèle qui lit la synthèse sur disque au début de chaque demande."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.seen: list[str] = []

    def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
        self.seen.append((self.output_dir / "synthese.md").read_text(encoding="utf-8"))
        return super().run_agent(system, user, tools, max_steps)


def run_peeking(tmp_path: Path, monkeypatch) -> PeekingAgent:
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    agent = PeekingAgent(tmp_path)
    process_all(ListingKit(), agent, tmp_path)
    return agent


def test_synthesis_updated_during_batch(tmp_path: Path, monkeypatch) -> None:
    # Avant chaque demande, la synthèse reflète les demandes déjà traitées.
    agent = run_peeking(tmp_path, monkeypatch)
    for done, content in enumerate(agent.seen):
        assert f"Avancement : {done}/3 demandes traitées (lot en cours)" in content
    assert len(agent.seen) == 3


def test_previous_results_kept_and_updated(tmp_path: Path, monkeypatch) -> None:
    # Une demande d'un ancien lancement reste ; une demande traitée à nouveau est mise à jour.
    old = [
        {"demande_id": "dem_ancienne", "statut": "proposition", "devis_total": 500.0, "traite_le": "2026-10-19 10:00"},
        {
            "demande_id": "dem_ok",
            "statut": "precisions_requises",
            "besoins": {"date_arrivee": None, "date_depart": None},
            "informations_manquantes": ["dates"],
        },
    ]
    (tmp_path / "resultats.json").write_text(json.dumps(old), encoding="utf-8")
    run(tmp_path, monkeypatch)
    saved = {item["demande_id"]: item for item in json.loads((tmp_path / "resultats.json").read_text(encoding="utf-8"))}
    assert saved["dem_ancienne"]["devis_total"] == 500.0
    assert saved["dem_ok"]["statut"] == "proposition"
    # Seules les nouvelles valeurs apparaissent, jamais les anciennes.
    assert saved["dem_ok"]["changements"] == [
        "statut : proposition",
        "arrivée : 2026-12-13",
        "départ : 2026-12-16",
        "chambres : 3 simple, 1 twin",
        "devis : 1980.00 EUR",
        "informations manquantes : aucune",
    ]
    assert "precisions_requises" not in (tmp_path / "synthese.md").read_text(encoding="utf-8")


def test_failure_does_not_replace_previous_valid_result(tmp_path: Path, monkeypatch) -> None:
    # dem_panne échoue (LLMError) : son résultat valide précédent est conservé, avec une note.
    old = [{"demande_id": "dem_panne", "statut": "proposition", "devis_total": 750.0}]
    (tmp_path / "resultats.json").write_text(json.dumps(old), encoding="utf-8")
    run(tmp_path, monkeypatch)
    saved = {item["demande_id"]: item for item in json.loads((tmp_path / "resultats.json").read_text(encoding="utf-8"))}
    assert saved["dem_panne"]["statut"] == "proposition" and saved["dem_panne"]["devis_total"] == 750.0
    assert "résultat précédent conservé" in saved["dem_panne"]["points_a_verifier"][-1]


def test_error_draft_never_replaces_previous_valid_draft(tmp_path: Path, monkeypatch) -> None:
    # L'agent conclut en « erreur » : aucun brouillon écrit, le résultat et le brouillon précédents restent.
    class ErrorAgent(ScriptedAgent):
        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            handlers = {spec.name: spec.handler for spec in tools}
            return handlers["write_draft"]({"fiche_json": {"statut": "erreur", "points_a_verifier": ["outil HS"]}})

    old = [{"demande_id": "dem_ok", "statut": "proposition", "devis_total": 1980.0, "brouillon": "b001"}]
    (tmp_path / "resultats.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    kit = ListingKit()
    results = process_all(kit, ErrorAgent(), tmp_path, only="dem_ok")
    assert results[0].statut == "erreur" and results[0].brouillon == ""
    assert not [name for name, _ in kit.saved if name in ("enregistrer_brouillon", "enregistrer_fiche_besoins")]
    saved = json.loads((tmp_path / "resultats.json").read_text(encoding="utf-8"))[0]
    assert (saved["statut"], saved["brouillon"]) == ("proposition", "b001")


def test_final_outputs_complete_without_tmp_files(tmp_path: Path, monkeypatch) -> None:
    # À la fin : plus de mention « lot en cours », 3 résultats et aucun fichier temporaire.
    run(tmp_path, monkeypatch)
    assert "lot en cours" not in (tmp_path / "synthese.md").read_text(encoding="utf-8")
    assert len(json.loads((tmp_path / "resultats.json").read_text(encoding="utf-8"))) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_new_draft_replaces_previous_one_under_same_id(tmp_path: Path) -> None:
    from agent.process_requests import replace_previous_draft

    # b001 : ancien brouillon de la demande ; b002 : brouillon d'une autre demande ; b003 : nouveau brouillon.
    for name, text in (("b001", "ancien"), ("b002", "autre demande"), ("b003", "nouveau")):
        (tmp_path / f"{name}.eml").write_text(text, encoding="utf-8")

    class DraftsKit:
        def call(self, name: str, arguments: dict) -> dict:
            drafts = [{"id": "b001", "pour": "dem"}, {"id": "b002", "pour": "autre"}, {"id": "b003", "pour": "dem"}]
            return {"nombre": 3, "brouillons": drafts}

    assert replace_previous_draft(DraftsKit(), "dem", "b003", tmp_path) == "b001"
    assert (tmp_path / "b001.eml").read_text(encoding="utf-8") == "nouveau"
    assert (tmp_path / "b002.eml").read_text(encoding="utf-8") == "autre demande"
    # Deux fichiers restent : le kit numérotera le prochain brouillon b003, sans écraser personne.
    assert sorted(path.stem for path in tmp_path.glob("b*.eml")) == ["b001", "b002"]


def test_draft_of_another_request_never_replaces_anything(tmp_path: Path, caplog) -> None:
    from agent.process_requests import replace_previous_draft

    for name in ("b001", "b002"):
        (tmp_path / f"{name}.eml").write_text(name, encoding="utf-8")

    class DraftsKit:
        def call(self, name: str, arguments: dict) -> dict:
            return {"nombre": 2, "brouillons": [{"id": "b001", "pour": "dem"}, {"id": "b002", "pour": "autre"}]}

    assert replace_previous_draft(DraftsKit(), "dem", "b002", tmp_path) == "b002"
    assert [(tmp_path / f"{name}.eml").read_text(encoding="utf-8") for name in ("b001", "b002")] == ["b001", "b002"]
    assert "aucun ancien brouillon remplacé" in caplog.text


def test_model_texts_escaped_and_limited_in_synthesis() -> None:
    from agent.synthesis import RequestResult, model_texts

    injected = r"voir [ici](https://x.example) <img src=x> `code` \<b>"
    points = model_texts([injected, "x" * 1000, *[f"point {n}" for n in range(20)]])
    assert len(points) == 11 and len(points[1]) == 300 and points[-1].startswith("12 élément")
    needs = {"date_arrivee": "<script>", "date_depart": "2026-12-16"}
    item = RequestResult(demande_id="dem", statut="proposition", besoins=needs, points_a_verifier=points)
    text = format_synthesis([item], "factice", True)
    assert r"voir \[ici\]\(https://x.example\) \<img src=x\> \`code\` \\\<b\>" in text
    assert r"\<script\> → 2026-12-16" in text and " <img" not in text and "](" not in text


def test_code_note_kept_after_ten_model_points() -> None:
    from typing import Any

    from agent.llm_providers.base import ToolError
    from agent.mcp_bridge import HotelTools
    from agent.process_requests import build_result

    class SheetFailingKit(FakeKit):
        def call(self, name: str, arguments: dict) -> Any:
            if name == "enregistrer_fiche_besoins":
                raise ToolError("disque plein")
            return super().call(name, arguments)

    tools = HotelTools(SheetFailingKit(), "dem")
    handlers = {spec.name: spec.handler for spec in tools.specs()}
    handlers["calc_devis"]({"besoins": WEDDING_NEEDS})
    points = [f"point {n}" for n in range(10)]
    sheet = {"statut": "proposition", "besoins": WEDDING_NEEDS, "brouillon_reponse": "Bonjour", "points_a_verifier": points}
    handlers["write_draft"]({"fiche_json": sheet})
    result = build_result("dem", tools, "")
    assert result.points_a_verifier[:10] == points
    assert "fiche non enregistrée" in result.points_a_verifier[10] and "disque plein" in result.points_a_verifier[10]


def test_unknown_only_stops_before_starting_the_server(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from agent import process_requests

    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "demande_01_mariage.eml").write_text("", encoding="utf-8")
    monkeypatch.setenv("KIT_BOITE", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["agent", "--only", "demande_99", "--output", str(tmp_path / "sorties")])
    monkeypatch.setattr(process_requests, "configure_logging", lambda output_dir: output_dir / "journal_outils.txt")
    monkeypatch.setattr(process_requests, "run_batch", lambda *args: pytest.fail("serveur démarré"))
    with pytest.raises(SystemExit, match="Demande inconnue : « demande_99 ».*demande_01_mariage"):
        process_requests.main()


def test_grouped_errors_end_with_a_clear_message(monkeypatch) -> None:
    import anyio
    import pytest

    from agent import process_requests

    async def failing_run(*args) -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(anyio.sleep, 0)
            raise ValueError("boîte illisible")

    monkeypatch.setattr(process_requests, "run", failing_run)
    with pytest.raises(SystemExit, match="Traitement interrompu : boîte illisible"):
        process_requests.run_batch(ScriptedAgent(), Path("."), None)


class ForgetfulAgent(ScriptedAgent):
    """Faux modèle qui calcule le devis puis répond avec le JSON final sans appeler write_draft."""

    def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
        handlers = {spec.name: spec.handler for spec in tools}
        handlers["calc_devis"]({"besoins": WEDDING_NEEDS})
        if "dem_panne" in user:
            return "Parfait ! Voici ma réponse, sans JSON."
        sheet = {"statut": "proposition", "besoins": WEDDING_NEEDS, "brouillon_reponse": "Bonjour,\n\nDevis joint."}
        return "Parfait ! Je dispose de toutes les informations.\n```json\n" + json.dumps(sheet) + "\n```"


def test_script_saves_draft_when_model_forgets_write_draft(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    with caplog.at_level("INFO", logger="agent_tools"):
        ok, _, no_json = process_all(ListingKit(), ForgetfulAgent(), tmp_path)
    # Le filet de sécurité passe par le handler journalisé, comme un appel du modèle.
    assert any("[dem_ok] write_draft" in message for message in caplog.messages)
    # JSON exploitable : fiche et brouillon enregistrés par le script, devis du code joint, note ajoutée.
    assert (ok.statut, ok.devis_total, ok.brouillon) == ("proposition", 1980.0, "b001")
    assert "enregistrés par le script" in ok.points_a_verifier[-1]
    # Aucun JSON : la demande reste en erreur, avec la raison.
    assert no_json.statut == "erreur" and "aucun JSON exploitable" in no_json.points_a_verifier[0]


def test_server_lost_during_write_draft_fallback_stops_batch(tmp_path: Path, monkeypatch) -> None:
    from agent.mcp_bridge import KitConnectionError

    class ClosingKit(ListingKit):
        """Faux kit dont la connexion se ferme quand le script enregistre le brouillon à la place du modèle."""

        def call(self, name: str, arguments: dict):
            if name == "enregistrer_fiche_besoins":
                raise KitConnectionError("Connexion au serveur MCP du kit fermée (l'outil enregistrer_fiche_besoins).")
            return super().call(name, arguments)

    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    stopped, *pending = process_all(ClosingKit(), ForgetfulAgent(), tmp_path)
    assert stopped.statut == "erreur" and "serveur MCP" in stopped.points_a_verifier[0]
    assert [item.statut for item in pending] == ["non_traitee", "non_traitee"]


BAD_DATE_EML = "From: P <p@x.example>\nDate: le mardi prochain\nSubject: groupe\n\nBonjour, 10 chambres.\n"
BAD_CHARSET_EML = (
    "From: P <p@x.example>\nDate: Fri, 02 Oct 2026 09:14:00 +0200\nSubject: groupe\nMIME-Version: 1.0\n"
    'Content-Type: text/plain; charset="inexistant-123"\n\nBonjour, 10 chambres.\n'
)


def test_unreadable_emails_fail_alone_with_the_real_kit_server(tmp_path: Path, monkeypatch) -> None:
    """Vrai serveur MCP (local) sur une copie de la boîte : Date illisible et charset inconnu."""
    import shutil

    import anyio

    import planning
    from agent.mcp_bridge import KIT_DIR, KitClient, kit_session

    mailbox = tmp_path / "boite"
    shutil.copytree(KIT_DIR / "boite", mailbox)
    (mailbox / "inbox" / "zz_date.eml").write_text(BAD_DATE_EML, encoding="utf-8")
    (mailbox / "inbox" / "zz_charset.eml").write_text(BAD_CHARSET_EML, encoding="utf-8")
    monkeypatch.setenv("KIT_BOITE", str(mailbox))
    monkeypatch.setattr(planning, "CHEMIN_BASE", planning.CHEMIN_BASE)
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")

    class SilentAgent(ScriptedAgent):
        """Ne touche à rien : seule compte la liste des demandes confiées au modèle."""

        def __init__(self) -> None:
            self.seen: list[str] = []

        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            self.seen.append(user.split(":", 1)[1].strip())
            return ""

    agent = SilentAgent()

    async def scenario() -> list:
        async with kit_session() as client:
            return await anyio.to_thread.run_sync(process_all, KitClient(client), agent, tmp_path)

    results = {result.demande_id: result for result in anyio.run(scenario)}
    assert len(results) == 12 and len(agent.seen) == 10
    for unreadable in ("zz_date", "zz_charset"):
        assert unreadable not in agent.seen
        assert results[unreadable].statut == "erreur"
        assert "courriel illisible" in results[unreadable].points_a_verifier[0]
