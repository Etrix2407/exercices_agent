"""Tests des contrôles en code (lisent le vrai planning du kit, en lecture seule)."""

from __future__ import annotations

import planning
from agent.checks import (
    amounts_in,
    check_alternative_quote,
    check_alternatives,
    check_draft_body,
    planning_fingerprint,
    review_sheet,
    shift_needs,
)
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


def test_fingerprint_reads_the_kit_base_even_in_a_path_with_spaces(tmp_path, monkeypatch) -> None:
    reference = planning_fingerprint()
    copy = tmp_path / "dossier avec espace#1" / "hotel.db"
    copy.parent.mkdir()
    copy.write_bytes(planning.CHEMIN_BASE.read_bytes())
    monkeypatch.setattr(planning, "CHEMIN_BASE", copy)
    assert planning_fingerprint() == reference


def test_amounts_read_in_french_and_english_formats() -> None:
    text = "Total : 6 680,00 EUR TTC, soit 6680.00 € ; acompte 1.980 euros ; le 12 janvier 2027 ; 20 %."
    assert amounts_in(text) == [6680.0, 6680.0, 1980.0]


def test_draft_body_flags_other_amount_and_discount_words() -> None:
    assert check_draft_body("Devis indicatif de 1 980,00 EUR TTC.", 1980.0) == []
    problems = check_draft_body("Total 1 800 EUR, avec une réduction et un geste commercial.", 1980.0)
    assert len(problems) == 3 and "≠ total du devis joint 1980.00 EUR" in problems[0]
    assert "« réduction »" in problems[1] and "« geste commercial »" in problems[2]
    assert "aucun devis" in check_draft_body("Comptez 500 €.", None)[0]


def test_precisions_without_missing_information_is_flagged() -> None:
    assert review_sheet("precisions_requises", {}, None, [], [], "Bonjour") == [
        "statut « precisions_requises » sans aucune information manquante listée"
    ]
    assert review_sheet("precisions_requises", {}, None, [], ["dates"], "Bonjour") == []


def test_alternative_quote_required_and_on_first_alternative() -> None:
    assert "sans devis" in check_alternative_quote(REGIONAL_NEEDS, None, ["2026-12-13 → 2026-12-15"])[0]
    quote = quote_for(shift_needs(REGIONAL_NEEDS, "2026-12-13", "2026-12-15"))
    assert "première date alternative" in check_alternative_quote(REGIONAL_NEEDS, quote, ["2026-12-09 → 2026-12-11"])[0]
