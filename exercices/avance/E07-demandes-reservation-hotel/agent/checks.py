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

import init_donnees
import planning
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import halls_with_dates, quote_arguments, rooms_by_type

ALTERNATIVE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:→|->|au|à)\s*(\d{4}-\d{2}-\d{2})")


def planning_fingerprint() -> str:
    """Empreinte du contenu du planning et des pré-réservations : prouve que rien n'a été réservé ni déplacé."""
    digest = hashlib.sha256()
    with closing(sqlite3.connect(f"file:{init_donnees.BASE}?mode=ro", uri=True)) as connection:
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
            if not any(planning._sans_accent(name) == planning._sans_accent(hall) for name in free):
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
