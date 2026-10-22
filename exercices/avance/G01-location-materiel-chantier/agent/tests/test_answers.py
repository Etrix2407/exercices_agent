"""Tests de la lecture de la réponse finale et de son contrôle en code par l'orchestrateur."""

from __future__ import annotations

import pytest

from agent.answers import parse_answer
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import Trace
from agent.orchestrator import QUOTE, RETURN, checked_answer
from agent.return_agent import ReturnTools


def test_nested_status_cannot_replace_the_answer():
    answer = '{"statut": "proposition", "machine": "MPE-001", "detail": {"statut": "hors_perimetre"}}'
    assert parse_answer(answer)["statut"] == "proposition"


def test_deeply_nested_answer_is_unreadable_not_a_crash():
    assert parse_answer("[" * 100_000 + "]" * 100_000) == {}


def test_unknown_status_or_unlisted_machine_needs_review():
    trace = Trace(proposable={"MPE-001"})
    assert checked_answer(QUOTE, {"statut": "valide", "resume": "r"}, "", trace)[0] == "a_verifier"
    status, summary = checked_answer(QUOTE, {"statut": "proposition", "machine": "MPE-009", "resume": "r"}, "", trace)
    assert status == "a_verifier" and "MPE-009" in summary
    assert checked_answer(QUOTE, {"statut": "proposition", "machine": "MPE-001", "resume": "r"}, "", trace)[0] == "proposition"
    assert checked_answer(RETURN, {"statut": "dossier_preuve", "resume": "r"}, "", Trace())[0] == "dossier_preuve"


@pytest.mark.parametrize("machine", [{"reference": "MPE-001"}, ["MPE-001"], 7])
def test_machine_that_is_not_text_needs_review(machine):
    trace = Trace(proposable={"MPE-001"})
    status, summary = checked_answer(QUOTE, {"statut": "proposition", "machine": machine, "resume": "r"}, "", trace)
    assert status == "a_verifier" and "machine illisible" in summary


class RecordingKit:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def call(self, name: str, arguments: dict):
        assert name == "creer_brouillon", name
        self.saved.append(arguments)
        return {"id": len(self.saved), "statut": "brouillon"}


@pytest.mark.parametrize(("content", "accepted"), [
    ("Nettoyage lourd : 150 € HT selon la grille.", True),
    ("Réparation du bras : non chiffré.", True),
    ("Facturer directement 4 500 € au client.", False),
])
def test_evidence_file_only_cites_grid_fees(content: str, accepted: bool):
    kit = RecordingKit()
    handler = next(spec.handler for spec in ReturnTools(kit, Trace()).specs() if spec.name == "create_evidence_file")
    args = {"target": "LOC-2026-0121", "content": content, "justification": "CR", "sources": ["CR-2026-1044"]}
    if accepted:
        handler(args)
    else:
        with pytest.raises(ToolError):
            handler(args)
    assert len(kit.saved) == (1 if accepted else 0)


def test_only_the_content_must_cite_grid_fees():
    kit = RecordingKit()
    handler = next(spec.handler for spec in ReturnTools(kit, Trace()).specs() if spec.name == "create_evidence_file")
    args = {"target": "LOC-2026-0121", "sources": ["CR-2026-1044"]}
    # Fait repris du compte rendu dans la justification : accepté.
    handler({**args, "content": "Imputation client, réparation non chiffrée.",
             "justification": "CR-2026-1044 : dommage estimé par l'atelier : 350 €."})
    # Même montant proposé dans le contenu : refusé.
    with pytest.raises(ToolError):
        handler({**args, "content": "Facturer 350 € au client.", "justification": "CR-2026-1044."})
    assert len(kit.saved) == 1
