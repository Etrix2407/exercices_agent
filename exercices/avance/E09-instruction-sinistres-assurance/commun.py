"""Fonctions partagées par les serveurs du kit E09 : accès à la base, recherche, dates."""

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ICI = Path(__file__).parent
BASE = Path(os.environ.get("E09_BASE", ICI / "donnees" / "sinistres.db"))
SORTIES = Path(os.environ.get("E09_SORTIES", ICI / "sorties"))
JOURS_FERIES = ICI / "donnees" / "jours_feries.json"


def requete(sql: str, params: tuple = ()) -> list[dict]:
    """Lecture seule : la base est ouverte en mode=ro."""
    if not BASE.exists():
        raise FileNotFoundError(f"Base absente : {BASE}. Lancer init_donnees.py.")
    with closing(sqlite3.connect(f"{BASE.resolve().as_uri()}?mode=ro", uri=True)) as cx:
        cx.row_factory = sqlite3.Row
        return [dict(r) for r in cx.execute(sql, params)]


# --- Recherche par mots-clés ----------------------------------------------------

MOTS_VIDES = set("le la les un une des de du d l et ou a au aux en dans par pour sur sans est sont ce qui que ne pas".split())


def normaliser(texte: str) -> str:
    """Minuscules, sans accents."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def mots(texte: str) -> list[str]:
    return [m for m in re.findall(r"[a-z0-9]+", normaliser(texte)) if m not in MOTS_VIDES and len(m) > 1]


def rechercher(documents: list[dict], requete_texte: str, champ: str = "texte", maximum: int = 5) -> list[dict]:
    """Classe les documents par nombre d'occurrences des mots de la requête (préfixe de 5 lettres)."""
    termes = {m[:5] for m in mots(requete_texte)}
    resultats = []
    for doc in documents:
        jetons = [m[:5] for m in mots(doc[champ])]
        score = sum(jetons.count(t) for t in termes)
        couverts = sum(1 for t in termes if t in jetons)
        if score:
            resultats.append((couverts, score, doc))
    resultats.sort(key=lambda r: (-r[0], -r[1]))
    return [{**doc, "termes_trouves": c, "occurrences": s} for c, s, doc in resultats[:maximum]]


# --- Dates ----------------------------------------------------------------------


def jours_feries() -> set[date]:
    if JOURS_FERIES.exists():
        return {date.fromisoformat(j) for j in json.loads(JOURS_FERIES.read_text(encoding="utf-8"))["jours"]}
    return set()


def jour_ouvre(j: date, feries: set[date]) -> bool:
    return j.weekday() < 5 and j not in feries


def jours_ouvres_entre(debut: date, fin: date) -> int:
    """Nombre de jours ouvrés après « debut », jusqu'à « fin » incluse."""
    feries, n, j = jours_feries(), 0, debut
    while j < fin:
        j += timedelta(days=1)
        n += jour_ouvre(j, feries)
    return n


def ajouter_jours_ouvres(debut: date, nombre: int) -> date:
    feries, j, n = jours_feries(), debut, 0
    while n < nombre:
        j += timedelta(days=1)
        n += jour_ouvre(j, feries)
    return j


def lire_date(texte: str) -> date:
    """Accepte AAAA-MM-JJ ou JJ/MM/AAAA."""
    texte = texte.strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texte)
    return date(int(m[3]), int(m[2]), int(m[1])) if m else date.fromisoformat(texte)
