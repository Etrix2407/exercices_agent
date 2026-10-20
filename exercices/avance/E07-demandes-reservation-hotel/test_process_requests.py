"""Tests de l'orchestrateur : un faux modèle joue le rôle de l'agent (sans réseau)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_providers import LLMError
from process_requests import format_synthesis, process_all
from test_mcp_bridge import WEDDING_NEEDS, FakeKit


class ListingKit(FakeKit):
    """Faux kit qui liste trois demandes."""

    def call(self, name: str, arguments: dict):
        if name == "lister_demandes":
            return {"nombre": 3, "demandes": [{"id": "dem_ok"}, {"id": "dem_ecart"}, {"id": "dem_panne"}]}
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
    monkeypatch.setattr("process_requests.planning_fingerprint", lambda: "empreinte")
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


def test_alternative_quote_must_cover_first_alternative() -> None:
    from process_requests import check_alternative_quote

    quote = {"arrivee": "2027-01-04", "depart": "2027-01-06"}
    assert check_alternative_quote(quote, ["2027-01-04 → 2027-01-06"]) is None
    assert "≠" in check_alternative_quote(quote, ["2027-01-11 → 2027-01-13"])


def test_exhausted_quota_stops_batch_immediately(tmp_path: Path, monkeypatch) -> None:
    from llm_providers.base import LLMQuotaError

    class QuotaAgent(ScriptedAgent):
        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            if "dem_ecart" in user:
                raise LLMQuotaError("quota du jour épuisé")
            return super().run_agent(system, user, tools, max_steps)

    monkeypatch.setattr("process_requests.planning_fingerprint", lambda: "empreinte")
    ok, stopped, pending = process_all(ListingKit(), QuotaAgent(), tmp_path)
    assert (ok.statut, stopped.statut, pending.statut) == ("proposition", "erreur", "non_traitee")
    assert "quota" in pending.points_a_verifier[0]
