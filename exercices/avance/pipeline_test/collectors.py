"""Lecteurs génériques des sorties d'un agent, pour construire un instantané (snapshot) dans un adaptateur."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

# Format du journal des kits : « 13:50:09 INFO [demande_05] read_email … ».
JOURNAL_LINE = re.compile(r"^(\d{2}:\d{2}:\d{2}) (\w+) \[([^\]]+)\] (\S+)")


def read_json(path: Path, default: Any) -> Any:
    """Contenu JSON du fichier, ou default s'il est absent ou illisible."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def index_by(items: list[dict], key: str) -> dict[str, dict]:
    """Transforme une liste de résultats en {identifiant: résultat}."""
    return {str(item[key]): item for item in items if isinstance(item, dict) and key in item}


def tool_journal(path: Path, pattern: re.Pattern[str] = JOURNAL_LINE) -> dict[str, dict]:
    """Compte par cas les appels d'outils (lignes INFO), les refus (WARNING/ERROR) et la durée en secondes.

    pattern : groupes (heure, niveau, identifiant du cas, outil).
    """
    stats: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return stats
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        hour, level, case_id, _tool = match.groups()
        entry = stats.setdefault(case_id, {"appels_outils": 0, "refus_outils": 0, "_heures": []})
        if level == "INFO":
            entry["appels_outils"] += 1
        else:
            entry["refus_outils"] += 1
        entry["_heures"].append(datetime.strptime(hour, "%H:%M:%S"))
    for entry in stats.values():
        hours = entry.pop("_heures")
        entry["duree_s"] = int((max(hours) - min(hours)).total_seconds())
    return stats


def folder_files(path: Path) -> list[str]:
    """Noms des fichiers d'un dossier (ex. boîte d'envoi qui doit rester vide)."""
    return sorted(item.name for item in path.iterdir()) if path.is_dir() else []


def load_module(path: Path, name: str) -> ModuleType:
    """Importe un module d'un kit par son chemin, sous un nom unique : pas de conflit entre kits homonymes."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Module introuvable : {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
