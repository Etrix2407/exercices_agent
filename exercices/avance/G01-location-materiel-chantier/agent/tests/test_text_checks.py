"""Tests des contrôles de texte : montants, remises, engagements fermes et homoglyphes (sans réseau)."""

from __future__ import annotations

import pytest

from agent import text_checks

QUOTED = {1020.0, 900.0, 120.0, 180.0}


@pytest.mark.parametrize(("text", "expected"), [
    ("Prix final €99", [99.0]),
    ("ou EUR 50", [50.0]),
    ("soit 84O €", [840.0]),
    ("Budget : 2 k€", [2000.0]),
    ("Budget : 2,5 kEUR", [2500.0]),
    ("Location 84 HTVA", [84.0]),
    ("Location 50,-", [50.0]),
    ("Prix : 84", [84.0]),
    ("Le prix final est de 84.", [84.0]),
    ("réparation €2500 HT", [2500.0]),
    ("Total : 1 020,00 € HT (900 € de location, 120 € de transport).", [1020.0, 900.0, 120.0]),
    ("480.00 euros, ou 1.020,00 €", [480.0, 1020.0]),
])
def test_amounts_with_currency_before_after_or_price_word(text: str, expected: list[float]):
    assert text_checks.amounts(text) == expected


@pytest.mark.parametrize("text", [
    "Prix pour la période du 02/11 au 06/11.",
    "Total pour vos 12 jours, du 12 au 16 novembre 2026.",
    "Devis DEV-2026-0001, machine NCI-004, contrat LOC-2026-0121.",
    "Les prix sont en euros HT.",
])
def test_dates_references_and_durations_are_not_amounts(text: str):
    assert text_checks.amounts(text) == []


@pytest.mark.parametrize("text", [
    "84 $", "84 USD", "84 CHF", "quatre-vingt-quatre euros", "mille neuf cent vingt euros", "Prix : 84",
])
def test_amount_problem_refuses_foreign_currency_words_and_unknown_amounts(text: str):
    assert text_checks.amount_problem(text, QUOTED)


def test_amount_problem_accepts_quoted_amounts():
    assert text_checks.amount_problem("Total : 1 020,00 € HT, soit 180 € HT par jour.", QUOTED) is None


@pytest.mark.parametrize("text", [
    "Transport inclus, non facturé.",
    "Le transport est à notre charge.",
    "Livraison à titre gracieux.",
    "Le transport, c'est cadeau.",
    "Un prix d'ami pour vous.",
    "dix pour cent de moins",
    "10 pct de moins",
    "5 p.c. de moins",
    "Une r\u0435mise exceptionnelle.",  # e cyrillique
    "Le transport est \u03bfffert.",  # omicron grec
    "Une re\u200bmise.",  # espace de largeur nulle
])
def test_discount_wording_and_homoglyphs_are_detected(text: str):
    assert text_checks.discount_problem(text)


@pytest.mark.parametrize("text", [
    "Sans aucun cadeau.", "Aucune remise n'est prévue.", "Le transport n'est jamais à notre charge.",
])
def test_negated_discount_is_accepted(text: str):
    assert text_checks.discount_problem(text) is None


@pytest.mark.parametrize(("text", "refused"), [
    ("Disponibilité garantie.", True),
    ("Livraison ferme le 02/11.", True),
    ("Livraison garantie.", True),
    ("La machine est réservée pour vous.", True),
    ("La disponibilité n'est pas garantie.", False),
    ("Proposition sans engagement ferme.", False),
    ("Cette machine n'est pas réservée pour vous.", False),
])
def test_firm_commitments(text: str, refused: bool):
    assert bool(text_checks.commitment_problem(text)) is refused


def test_length_limit():
    assert text_checks.length_problem("x" * text_checks.MAX_TEXT_CHARS) is None
    assert text_checks.length_problem("x" * (text_checks.MAX_TEXT_CHARS + 1))


@pytest.mark.parametrize(("text", "expected"), [
    ("Facture n° 4512 du dossier, forfait nettoyage 85 €", [85.0]),
    ("15.11.2026, tarif 84 €", [84.0]),
    ("Tarif 84 € le 15/11/2026, facture réf. 77, prix no 12, F- 31", [84.0]),
])
def test_references_and_full_dates_near_price_words_are_not_amounts(text: str, expected: list[float]):
    assert text_checks.amounts(text) == expected
    assert text_checks.amount_problem(text, set(expected)) is None
