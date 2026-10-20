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


class ForgetfulAgent(ScriptedAgent):
    """Faux modèle qui calcule le devis puis répond avec le JSON final sans appeler write_draft."""

    def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
        handlers = {spec.name: spec.handler for spec in tools}
        handlers["calc_devis"]({"besoins": WEDDING_NEEDS})
        if "dem_panne" in user:
            return "Parfait ! Voici ma réponse, sans JSON."
        sheet = {"statut": "proposition", "besoins": WEDDING_NEEDS, "brouillon_reponse": "Bonjour,\n\nDevis joint."}
        return "Parfait ! Je dispose de toutes les informations.\n```json\n" + json.dumps(sheet) + "\n```"


def test_script_saves_draft_when_model_forgets_write_draft(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agent.checks.planning_fingerprint", lambda: "empreinte")
    ok, _, no_json = process_all(ListingKit(), ForgetfulAgent(), tmp_path)
    # JSON exploitable : fiche et brouillon enregistrés par le script, devis du code joint, note ajoutée.
    assert (ok.statut, ok.devis_total, ok.brouillon) == ("proposition", 1980.0, "b001")
    assert "enregistrés par le script" in ok.points_a_verifier[-1]
    # Aucun JSON : la demande reste en erreur, avec la raison.
    assert no_json.statut == "erreur" and "aucun JSON exploitable" in no_json.points_a_verifier[0]
