"""Contrôles en code des résultats de l'agent : devis, dates alternatives, planning inchangé.

Chaque contrôle relit le planning ou la grille du kit (lecture seule) et renvoie des points à vérifier
pour la synthèse ; aucun ne modifie quoi que ce soit.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from typing import Any

import init_donnees
import planning
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import quote_arguments, rooms_by_type

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


def check_alternatives(needs: dict[str, Any], alternatives: list[str]) -> list[str]:
    """Revérifie dans le planning que chaque période alternative a assez de chambres libres."""
    problems = []
    try:
        rooms = rooms_by_type(needs)
    except ToolError as error:
        return [f"chambres de la fiche illisibles : {error}"]
    for alternative in alternatives:
        match = ALTERNATIVE_PATTERN.search(alternative)
        if not match:
            problems.append(f"date alternative illisible : « {alternative} »")
            continue
        try:
            free = planning.disponibilites_chambres(*match.groups())["libres_sur_toute_la_periode"]
        except ValueError as error:
            problems.append(f"date alternative hors planning : « {alternative} » ({error})")
            continue
        short = {room: count for room, count in rooms.items() if count > free.get(room, 0)}
        if short:
            problems.append(f"date alternative « {alternative} » sans assez de chambres libres : {short}")
    return problems


def check_alternative_quote(quote: dict[str, Any], alternatives: list[str]) -> str | None:
    """Vérifie que le devis joint porte bien sur la première période alternative proposée."""
    match = ALTERNATIVE_PATTERN.search(alternatives[0]) if alternatives else None
    if match and (quote.get("arrivee"), quote.get("depart")) == match.groups():
        return None
    return f"devis joint ({quote.get('arrivee')} → {quote.get('depart')}) ≠ première date alternative proposée"
