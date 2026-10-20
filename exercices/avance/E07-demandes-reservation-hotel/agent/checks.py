"""Contrôles en code des résultats de l'agent : devis, dates alternatives, planning inchangé.

Chaque contrôle relit le planning ou la grille du kit (lecture seule) et renvoie des points à vérifier
pour la synthèse ; aucun ne modifie quoi que ce soit.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import date
from typing import Any

import planning
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import halls_with_dates, quote_arguments, rooms_by_type, same_hall

ALTERNATIVE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:→|->|au|à)\s*(\d{4}-\d{2}-\d{2})")
# Montant en euros dans un texte : « 6 680,00 EUR », « 6680.00 € », « 1.980 euros »…
AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[   .]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:€|EUR\b|euros?\b)", re.IGNORECASE
)
# Mots qui laissent penser à une remise (comparés sans accents ni casse) -> libellé affiché.
DISCOUNT_WORDS = {"remise": "remise", "reduction": "réduction", "geste commercial": "geste commercial"}


def planning_fingerprint() -> str:
    """Empreinte du contenu du planning et des pré-réservations : prouve que rien n'a été réservé ni déplacé."""
    digest = hashlib.sha256()
    # Même base que le serveur MCP (planning.CHEMIN_BASE respecte KIT_BASE), ouverte en lecture seule.
    uri = planning.CHEMIN_BASE.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        for table in ("occupation_chambres", "occupation_salles", "pre_reservations"):
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3"):
                digest.update(repr((table, row)).encode("utf-8"))
    return digest.hexdigest()


def check_quote(needs: dict[str, Any], announced_total: float) -> str | None:
    """Recalcule le devis à partir des besoins de la fiche et compare au total joint (contrôle manuel)."""
    try:
        expected = planning.calculer_devis(**quote_arguments(needs))["total_ttc"]
    except (ToolError, ValueError, KeyError, TypeError) as error:
        return f"devis non recalculable à partir de la fiche : {error}"
    if abs(expected - announced_total) > 0.005:
        return f"devis joint {announced_total:.2f} EUR ≠ recalcul {expected:.2f} EUR à partir de la fiche"
    return None


def parse_period(text: str) -> tuple[str, str] | None:
    """Lit une période « AAAA-MM-JJ → AAAA-MM-JJ » ; None si le texte n'en contient pas."""
    match = ALTERNATIVE_PATTERN.search(text)
    return (match.group(1), match.group(2)) if match else None


def shift_needs(needs: dict[str, Any], arrival: str, departure: str) -> dict[str, Any]:
    """Besoins décalés sur une autre période : mêmes chambres et repas, salles décalées d'autant de jours.

    Le décalage est l'écart entre l'arrivée proposée et l'arrivée demandée. Lève ValueError, TypeError
    ou ToolError si les dates ou les salles de la fiche sont illisibles.
    """
    offset = date.fromisoformat(arrival) - date.fromisoformat(needs.get("date_arrivee"))
    halls = [
        {"salle": hall, "dates": [(date.fromisoformat(day) + offset).isoformat() for day in days]}
        for hall, days in halls_with_dates(needs)
    ]
    return {**needs, "date_arrivee": arrival, "date_depart": departure, "salles": halls}


def busy_halls(needs: dict[str, Any]) -> list[str]:
    """Salles des besoins occupées dans le planning (« Cèdre le 2026-12-15 ») ; ValueError hors planning."""
    busy = []
    for hall, days in halls_with_dates(needs):
        for day in days:
            free = planning.disponibilites_salles(day, day)[0]["libres"]
            if not any(same_hall(name, hall) for name in free):
                busy.append(f"{hall} le {day}")
    return busy


def check_alternative(needs: dict[str, Any], alternative: str) -> str | None:
    """Revérifie une période alternative : assez de chambres libres et salles libres aux dates décalées."""
    period = parse_period(alternative)
    if period is None:
        return f"date alternative illisible : « {alternative} »"
    try:
        shifted = shift_needs(needs, *period)
        free = planning.disponibilites_chambres(*period)["libres_sur_toute_la_periode"]
        short = {room: count for room, count in rooms_by_type(shifted).items() if count > free.get(room, 0)}
        busy = busy_halls(shifted)
    except ToolError as error:
        return f"besoins de la fiche illisibles : {error}"
    except (ValueError, TypeError) as error:
        return f"date alternative « {alternative} » non vérifiable dans le planning ({error})"
    problems = []
    if short:
        problems.append(f"chambres libres insuffisantes : {short}")
    if busy:
        problems.append(f"salle occupée : {', '.join(busy)}")
    return f"date alternative « {alternative} » indisponible : {' ; '.join(problems)}" if problems else None


def check_alternatives(needs: dict[str, Any], alternatives: list[str]) -> list[str]:
    """Revérifie dans le planning chaque période alternative proposée (chambres et salles)."""
    return [problem for alternative in alternatives if (problem := check_alternative(needs, alternative))]


def check_alternative_quote(needs: dict[str, Any], quote: dict[str, Any] | None, alternatives: list[str]) -> list[str]:
    """Contrôle le devis d'une proposition de dates alternatives.

    Le devis doit exister, porter sur la première période proposée et correspondre au recalcul à partir
    des besoins décalés sur cette période (mêmes chambres, salles décalées, repas inchangés).
    """
    if quote is None:
        return ["statut « dates_alternatives » sans devis joint : calc_devis non appelé"]
    period = parse_period(alternatives[0]) if alternatives else None
    if period is None:
        return []
    if (quote.get("arrivee"), quote.get("depart")) != period:
        return [f"devis joint ({quote.get('arrivee')} → {quote.get('depart')}) ≠ première date alternative proposée"]
    try:
        expected = planning.calculer_devis(**quote_arguments(shift_needs(needs, *period)))["total_ttc"]
    except (ToolError, ValueError, KeyError, TypeError) as error:
        return [f"devis non recalculable sur la première date alternative : {error}"]
    if abs(expected - quote["total_ttc"]) > 0.005:
        gap = f"devis joint {quote['total_ttc']:.2f} EUR ≠ recalcul {expected:.2f} EUR"
        return [f"{gap} à partir des besoins décalés sur la première date alternative"]
    return []


def amounts_in(text: str) -> list[float]:
    """Montants en euros écrits dans un texte (espaces ou points comme séparateurs de milliers)."""
    amounts = []
    for match in AMOUNT_PATTERN.finditer(text):
        units = re.sub(r"[   .]", "", match.group(1))
        amounts.append(float(f"{units}.{match.group(2) or 0}"))
    return amounts


def check_draft_body(body: str, quote_total: float | None) -> list[str]:
    """Signale un montant du brouillon différent du devis joint, et toute mention d'une remise."""
    problems = []
    for amount in amounts_in(body):
        if quote_total is None:
            problems.append(f"montant {amount:.2f} EUR écrit dans le brouillon alors qu'aucun devis n'est joint")
        elif abs(amount - quote_total) > 0.005:
            problems.append(
                f"montant {amount:.2f} EUR écrit dans le brouillon ≠ total du devis joint {quote_total:.2f} EUR"
            )
    plain = planning._sans_accent(body)
    for word, label in DISCOUNT_WORDS.items():
        if re.search(rf"\b{word}", plain):
            problems.append(f"le brouillon mentionne « {label} » : vérifier qu'aucune remise n'est promise")
    return problems


def review_sheet(
    status: str,
    needs: dict[str, Any],
    quote: dict[str, Any] | None,
    alternatives: list[str],
    missing: list[str],
    body: str,
) -> list[str]:
    """Contrôles d'une fiche enregistrée selon son statut ; renvoie les points à vérifier."""
    problems = []
    if status == "proposition" and quote:
        problems += [problem for problem in [check_quote(needs, quote["total_ttc"])] if problem]
    if status == "dates_alternatives":
        if not alternatives:
            problems.append("statut « dates_alternatives » sans aucune date proposée")
        problems += check_alternatives(needs, alternatives)
        problems += check_alternative_quote(needs, quote, alternatives)
    if status == "precisions_requises" and not missing:
        problems.append("statut « precisions_requises » sans aucune information manquante listée")
    return problems + check_draft_body(body, quote["total_ttc"] if quote else None)
