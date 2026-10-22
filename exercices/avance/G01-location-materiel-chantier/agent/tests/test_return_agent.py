"""Tests des garde-fous de l'agent retour avec un faux kit (sans réseau) : montants hors grille et taille."""

from __future__ import annotations

import pytest

from agent import return_agent
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import Trace


class DraftKit:
    """Faux kit : enregistre les brouillons créés."""

    def __init__(self) -> None:
        self.drafts: list[dict] = []

    def call(self, name: str, arguments: dict):
        assert name == "creer_brouillon", name
        self.drafts.append(arguments)
        return {"id": len(self.drafts)}


def evidence_file(kit: DraftKit, **overrides) -> str:
    args = {"target": "LOC-2026-0121", "content": "Nettoyage lourd constaté.", "justification": "CR-2026-1044.",
            "sources": ["CR-2026-1044"]} | overrides
    return return_agent.ReturnTools(kit, Trace()).create_evidence_file(args)


@pytest.mark.parametrize("content", [
    "Réparation €2500 HT, à facturer directement.",
    "Réparation EUR 2500.",
    "Réparation 2,5 k€.",
    "Réparation : deux mille cinq cents euros.",
])
def test_amounts_outside_the_grid_are_refused(content: str):
    kit = DraftKit()
    with pytest.raises(ToolError, match="grid_fee"):
        evidence_file(kit, content=content)
    assert kit.drafts == []


def test_grid_fee_is_accepted():
    kit = DraftKit()
    fee = min(return_agent.return_fee_amounts())
    evidence_file(kit, content=f"Forfait de la grille : {fee:.2f} € HT ; réparation non chiffrée.")
    assert len(kit.drafts) == 1


@pytest.mark.parametrize("field", ["content", "justification", "target"])
def test_long_texts_are_refused(field: str):
    kit = DraftKit()
    with pytest.raises(ToolError, match="trop long"):
        evidence_file(kit, **{field: "x" * 5001})
    assert kit.drafts == []
