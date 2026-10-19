"""Fonctions partagées par le kit E11 : accès à la base, découpage, recherche, vérification de citation."""

import difflib
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

ICI = Path(__file__).parent
BASE = Path(os.environ.get("E11_BASE", ICI / "donnees" / "contrats.db"))
SORTIES = Path(os.environ.get("E11_SORTIES", ICI / "sorties"))

MOTS_VIDES = set(
    "le la les un une des de du d l et ou a au aux en dans par pour sur sans est sont ce cette ces qui que "
    "ne pas il elle ils se sa son ses leur leurs tout toute tous".split()
)


def requete(sql: str, params: tuple = ()) -> list[dict]:
    """Lecture seule : la base est ouverte en mode=ro."""
    if not BASE.exists():
        raise FileNotFoundError(f"Base absente : {BASE}. Lancer init_donnees.py.")
    with closing(sqlite3.connect(f"{BASE.resolve().as_uri()}?mode=ro", uri=True)) as cx:
        cx.row_factory = sqlite3.Row
        return [dict(r) for r in cx.execute(sql, params)]


def normaliser(texte: str) -> str:
    """Minuscules, sans accents."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def mots(texte: str) -> list[str]:
    return [m for m in re.findall(r"[a-z0-9]+", normaliser(texte)) if m not in MOTS_VIDES and len(m) > 1]


def racine(mot: str) -> str:
    """Troncature à 6 lettres : rapproche résiliation / résilier, pénalité / pénalités."""
    return mot[:6]


def phrases(texte: str) -> list[str]:
    morceaux = re.split(r"(?<=[.;:!?])\s+|\n+", texte)
    return [m.strip() for m in morceaux if m.strip()]


# --- Vérification de citation ---------------------------------------------------------


def espaces(texte: str) -> str:
    return re.sub(r"\s+", " ", texte).strip()


def typographie(texte: str) -> str:
    """Neutralise apostrophes et guillemets typographiques, espaces insécables."""
    table = {"’": "'", "‘": "'", "“": '"', "”": '"', " ": " ", " ": " "}
    return espaces("".join(table.get(c, c) for c in texte))


def verifier(citation: str, sections: list[dict]) -> dict:
    """Cherche la citation mot pour mot (espaces multiples tolérés) dans les sections d'un contrat."""
    cible = espaces(citation.strip().strip("«»\"").strip())
    if not cible:
        return {"citation": citation, "exacte": False, "motif": "citation vide"}
    for s in sections:
        if cible in espaces(s["texte"]):
            resultat = {"citation": cible, "exacte": True, "article": s["article"], "titre": s["titre"]}
            if len(cible.split()) < 5:
                resultat["avertissement"] = "citation de moins de cinq mots : trop courte pour étayer un classement"
            return resultat
    resultat = {"citation": cible, "exacte": False}
    for s in sections:
        if typographie(cible) in typographie(s["texte"]):
            resultat.update(exacte_hors_typographie=True, article=s["article"], titre=s["titre"])
            return resultat
    resultat["exacte_hors_typographie"] = False
    meilleur = max(
        ((difflib.SequenceMatcher(None, cible, p).ratio(), p, s) for s in sections for p in phrases(s["texte"])),
        key=lambda x: x[0],
        default=None,
    )
    if meilleur:
        ratio, phrase, s = meilleur
        resultat["passage_le_plus_proche"] = {"article": s["article"], "titre": s["titre"], "texte": phrase,
                                              "similarite": round(ratio, 2)}
    return resultat


CITATION = re.compile(r"«\s*(.+?)\s*»|\"([^\"]+)\"|“([^”]+)”")


def extraire_citations(texte: str) -> list[str]:
    """Citations entre « » ; entre guillemets droits ou anglais, seulement à partir de quatre mots
    (un mot isolé entre guillemets, par exemple un classement, n'est pas une citation)."""
    citations = []
    for m in CITATION.finditer(texte):
        francais, droits, anglais = m.groups()
        if francais:
            citations.append(francais)
        elif len((droits or anglais).split()) >= 4:
            citations.append(droits or anglais)
    return citations
