"""Tests des contrôles en code (lisent le vrai planning du kit, en lecture seule)."""

from __future__ import annotations

import planning
from agent.checks import check_alternative_quote, check_alternatives, shift_needs
from agent.mcp_bridge import quote_arguments

# Besoins de la demande 08 : 12 doubles + 8 simples du 11 au 13/12, salle Cèdre le 12/12 (occupée).
REGIONAL_NEEDS = {
    "date_arrivee": "2026-12-11",
    "date_depart": "2026-12-13",
    "chambres": [{"type": "double", "nombre": 12}, {"type": "simple", "nombre": 8}],
    "salles": [{"salle": "Cèdre", "dates": ["2026-12-12"]}],
    "repas": [{"prestation": "dejeuner_buffet", "couverts": 45, "nombre": 1}],
}


def quote_for(needs: dict) -> dict:
    return planning.calculer_devis(**quote_arguments(needs))


def test_alternative_checks_shifted_hall_dates() -> None:
    # 14→16/12 : assez de chambres, mais Cèdre est occupée le 15/12 (jour décalé de +3).
    problems = check_alternatives(REGIONAL_NEEDS, ["2026-12-14 → 2026-12-16"])
    assert len(problems) == 1 and "Cèdre le 2026-12-15" in problems[0]
    # 13→15/12 : chambres et salle (14/12) libres.
    assert check_alternatives(REGIONAL_NEEDS, ["2026-12-13 → 2026-12-15"]) == []


def test_alternative_quote_recomputed_on_shifted_needs() -> None:
    shifted = shift_needs(REGIONAL_NEEDS, "2026-12-13", "2026-12-15")
    assert shifted["salles"] == [{"salle": "Cèdre", "dates": ["2026-12-14"]}]
    alternatives = ["2026-12-13 → 2026-12-15"]
    assert check_alternative_quote(REGIONAL_NEEDS, quote_for(shifted), alternatives) == []
    # Devis sous-dimensionné : une seule chambre double au lieu de 12 doubles + 8 simples.
    undersized = quote_for({**shifted, "chambres": [{"type": "double", "nombre": 1}]})
    assert "≠ recalcul" in check_alternative_quote(REGIONAL_NEEDS, undersized, alternatives)[0]


def test_alternative_quote_required_and_on_first_alternative() -> None:
    assert "sans devis" in check_alternative_quote(REGIONAL_NEEDS, None, ["2026-12-13 → 2026-12-15"])[0]
    quote = quote_for(shift_needs(REGIONAL_NEEDS, "2026-12-13", "2026-12-15"))
    assert "première date alternative" in check_alternative_quote(REGIONAL_NEEDS, quote, ["2026-12-09 → 2026-12-11"])[0]
