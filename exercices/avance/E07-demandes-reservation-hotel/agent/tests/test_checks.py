"""Tests des contrôles en code (lisent le vrai planning du kit, en lecture seule)."""

from __future__ import annotations

import planning
from agent.checks import (
    amounts_in,
    check_alternative_quote,
    check_alternatives,
    check_draft_body,
    draft_body_problems,
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
    # La base est lue dans KIT_BASE au moment de l'appel (après load_dotenv), pas figée à l'import.
    monkeypatch.setenv("KIT_BASE", str(copy))
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


def test_draft_body_ignores_harmless_remise_but_flags_real_discounts() -> None:
    harmless = "Tarif sans remise, aucune remise possible. Remise des clés à 15 h ; remise de la clé au départ."
    assert check_draft_body(harmless, None) == []
    for text, label in [
        ("Nous vous accordons une remise de 10 % sur les chambres.", "« remise de X % »"),
        ("Une remise exceptionnelle est envisageable.", "« remise »"),
        ("Une réduction est possible.", "« réduction »"),
        ("Un geste commercial sera fait.", "« geste commercial »"),
    ]:
        problems = check_draft_body(text, None)
        assert len(problems) == 1 and label in problems[0], text


def test_draft_body_flags_other_discount_words_and_percentages() -> None:
    for text, label in [
        ("Un rabais est possible.", "« rabais »"),
        ("Une ristourne vous sera versée.", "« ristourne »"),
        ("Le petit-déjeuner est offert.", "« offert »"),
        ("La salle est OFFERTE.", "« offert »"),
        ("Les cafés sont offerts.", "« offert »"),
        ("Le parking est gratuit.", "« gratuit »"),
        ("La navette est gratuite.", "« gratuit »"),
        ("Nous appliquons un tarif préférentiel.", "« tarif préférentiel »"),
        ("Profitez de notre promotion d'hiver.", "« promotion »"),
        ("Une promo est en cours.", "« promotion »"),
        ("A discount applies.", "« discount »"),
        ("Soit 10 % de moins.", "« pourcentage »"),
        ("Soit 10% de moins.", "« pourcentage »"),
        ("Soit -15 % sur les chambres.", "« -X % »"),
    ]:
        problems = check_draft_body(text, None)
        assert len(problems) == 1 and label in problems[0], text
    normal ="Bonjour,\n\nNous avons bien noté votre demande pour 12 chambres du 11 au 13 décembre. Cordialement."
    assert check_draft_body(normal, None) == []


def test_draft_body_separates_blocking_discounts_from_warnings() -> None:
    for text in (
        "Un rabais de 15 % est possible.",
        "Nous offrons 10 % de remise.",
        "Une réduction de 5,5 % sur les chambres.",
        "Soit -15 % sur les chambres.",
        "Nous appliquons un tarif préférentiel.",
        "Un geste commercial sera fait.",
        "A discount applies.",
    ):
        blocking, warnings = draft_body_problems(text, None)
        assert len(blocking) == 1 and warnings == [], text
    for text in (
        "Un acompte de 30 % est demandé à la confirmation.",
        "Le parking est gratuit.",
        "Petit-déjeuner offert dans le forfait.",
        "Profitez de notre promotion d'hiver.",
    ):
        blocking, warnings = draft_body_problems(text, None)
        assert blocking == [] and len(warnings) == 1, text


def test_negated_discount_is_neither_blocked_nor_flagged() -> None:
    for text in (
        "Nos tarifs s'entendent sans remise.",
        "Aucune réduction n'est possible.",
        "Il n'y a pas de rabais sur ce forfait.",
        "Nous ne pratiquons malheureusement pas de remise.",
        "Ni remise ni ristourne.",
        "Sans remise de 5,5 % cette fois.",
    ):
        assert draft_body_problems(text, None) == ([], []), text
    # La négation ne vaut que pour la même phrase.
    blocking, _ = draft_body_problems("Pas de souci. Une remise est possible.", None)
    assert len(blocking) == 1


def test_precisions_without_missing_information_is_flagged() -> None:
    assert review_sheet("precisions_requises", {}, None, [], [], "Bonjour") == [
        "statut « precisions_requises » sans aucune information manquante listée"
    ]
    assert review_sheet("precisions_requises", {}, None, [], ["dates"], "Bonjour") == []


def test_alternative_quote_required_and_on_first_alternative() -> None:
    assert "sans devis" in check_alternative_quote(REGIONAL_NEEDS, None, ["2026-12-13 → 2026-12-15"])[0]
    quote = quote_for(shift_needs(REGIONAL_NEEDS, "2026-12-13", "2026-12-15"))
    assert "première date alternative" in check_alternative_quote(REGIONAL_NEEDS, quote, ["2026-12-09 → 2026-12-11"])[0]


def test_amounts_with_currency_before_k_tax_dash_other_currencies_and_words() -> None:
    text = (
        "€50 ; EUR 50 ; 7 k€ ; 6 680 HTVA ; 6 680,- ; $ 20 ; 30 USD ; CHF 40 ; 6'680 CHF ; "
        "cinquante euros ; mille euros ; six mille six cent quatre-vingts euros ; 6\u202f680\u00a0€"
    )
    assert amounts_in(text) == [50, 50, 7000, 6680, 6680, 20, 30, 40, 6680, 50, 1000, 6680, 6680]
    assert amounts_in("du 2026-12-13 au 2026-12-16, 12 chambres, 3 nuits") == []
    # Montant égal au total du devis, même en lettres : accepté ; tout autre montant : bloquant.
    assert draft_body_problems("Total : six mille six cent quatre-vingts euros.", 6680.0) == ([], [])
    blocking, _ = draft_body_problems("Le total s'élève à mille euros.", 6680.0)
    assert len(blocking) == 1 and "1000.00 EUR" in blocking[0]


def test_disguised_discounts_and_homoglyphs_are_blocking() -> None:
    for text, label in [
        ("Les cafés vous sont offerts à titre gracieux.", "« à titre gracieux »"),
        ("La salle, c'est cadeau.", "« cadeau »"),
        ("Nous vous faisons un prix d’ami.", "« prix d'ami »"),
        ("Le dîner sera non facturé.", "« non facturé »"),
        ("La salle est à notre charge.", "« à notre charge »"),
        ("Soit 10 pour cent de moins.", "« pour cent »"),
        ("Soit 10 p.c. de moins.", "« pour cent »"),
        ("Soit 10 pct de moins.", "« pour cent »"),
        ("Soit dix pour cent de moins.", "« pour cent »"),
        ("Une rеmise est possible.", "« remise »"),  # « е » cyrillique
        ("Une ｒｅｍｉｓｅ est possible.", "« remise »"),  # pleine chasse
        ("Une re\u200bmise est possible.", "« remise »"),  # espace invisible
        ("Soit −15 % sur les chambres.", "« -X % »"),  # signe moins typographique
    ]:
        blocking, _ = draft_body_problems(text, None)
        assert len(blocking) == 1 and label in blocking[0], text
    # La négation reste tolérée, et « % » seul reste un simple signalement.
    assert draft_body_problems("Pas de cadeau ni de prix d'ami : le tarif est celui de la grille.", None) == ([], [])
    assert draft_body_problems("Un acompte de 30 % est demandé.", None)[0] == []


def test_out_of_scope_status_always_asks_for_human_confirmation() -> None:
    from agent.checks import HORS_PERIMETRE_NOTE

    assert review_sheet("hors_perimetre", {}, None, [], [], "Bonjour") == [HORS_PERIMETRE_NOTE]
