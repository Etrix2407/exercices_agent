r"""Construit donnees/sinistres.db à partir des fichiers du palier middle.

Usage :
    ..\.venv\Scripts\python init_donnees.py [chemin_du_dossier_middle]

Par défaut, le dossier source est ../../middle/E09-instruction-sinistres-assurance.
La base est recréée à chaque exécution (état initial identique).
"""

import csv
import re
import sqlite3
import sys
from pathlib import Path

ICI = Path(__file__).parent
SOURCE_DEFAUT = ICI.parent.parent / "middle" / ICI.name
BASE = ICI / "donnees" / "sinistres.db"

SCHEMA = """
CREATE TABLE declarations (
    numero_dossier TEXT PRIMARY KEY,
    fichier TEXT,
    date_reception TEXT,
    numero_contrat TEXT,
    declarant TEXT,
    adresse TEXT,
    date_sinistre TEXT,
    nature_declaree TEXT,
    lieu TEXT,
    montant_estime_texte TEXT,
    constat_amiable TEXT,
    texte TEXT
);
CREATE TABLE contrats (
    numero_contrat TEXT PRIMARY KEY,
    fichier TEXT,
    titulaire TEXT,
    logement TEXT,
    date_effet TEXT,
    formule TEXT,
    options TEXT,
    texte TEXT
);
CREATE TABLE garanties (
    numero_contrat TEXT,
    garantie TEXT,
    article_cg TEXT,
    statut TEXT,
    plafond_texte TEXT,
    plafond REAL
);
CREATE TABLE articles_cg (
    numero INTEGER PRIMARY KEY,
    titre TEXT,
    titre_partie TEXT,
    texte TEXT
);
CREATE TABLE bareme (
    nature TEXT,
    option TEXT,
    type_franchise TEXT,
    valeur REAL,
    minimum REAL,
    maximum REAL,
    article TEXT,
    regle TEXT
);
"""

CHAMPS_DECLARATION = {
    "Numéro de dossier": "numero_dossier",
    "Date de réception": "date_reception",
    "Numéro de contrat": "numero_contrat",
    "Nom du déclarant": "declarant",
    "Adresse du logement sinistré": "adresse",
    "Date du sinistre": "date_sinistre",
    "Nature du sinistre": "nature_declaree",
    "Lieu du sinistre": "lieu",
    "Montant estimé": "montant_estime_texte",
    "Constat amiable": "constat_amiable",
}


def nombre(texte: str) -> float | None:
    """« 15 000 € » -> 15000.0 ; « - » -> None."""
    chiffres = re.sub(r"[^\d,]", "", texte or "").replace(",", ".")
    return float(chiffres) if chiffres else None


def date_iso(texte: str) -> str:
    """« 07/09/2026 » -> « 2026-09-07 » ; autre valeur conservée telle quelle."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (texte or "").strip())
    return f"{m[3]}-{m[2]}-{m[1]}" if m else texte


def lire_declarations(source: Path) -> list[dict]:
    lignes = []
    for chemin in sorted((source / "declarations").glob("*.txt")):
        texte = chemin.read_text(encoding="utf-8")
        champs = {"fichier": chemin.name, "texte": texte}
        for ligne in texte.splitlines():
            cle, _, valeur = ligne.partition(" : ")
            if cle.strip() in CHAMPS_DECLARATION:
                champs[CHAMPS_DECLARATION[cle.strip()]] = valeur.strip()
        for cle in ("date_reception", "date_sinistre"):
            champs[cle] = date_iso(champs.get(cle, ""))
        lignes.append(champs)
    return lignes


def lire_contrat(chemin: Path) -> tuple[dict, list[dict]]:
    texte = chemin.read_text(encoding="utf-8")
    infos = {"fichier": chemin.name, "texte": texte}
    garanties = []
    for ligne in texte.splitlines():
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if len(cellules) == 2:
            cle, valeur = cellules
            correspondance = {
                "Numéro de contrat": "numero_contrat",
                "Titulaire": "titulaire",
                "Logement assuré": "logement",
                "Date d'effet": "date_effet",
                "Formule": "formule",
                "Options souscrites": "options",
            }
            if cle in correspondance:
                infos[correspondance[cle]] = date_iso(valeur) if cle == "Date d'effet" else valeur
        elif len(cellules) == 4 and cellules[1].startswith("art."):
            garanties.append(
                {
                    "garantie": cellules[0],
                    "article_cg": cellules[1],
                    "statut": cellules[2],
                    "plafond_texte": cellules[3],
                    "plafond": nombre(cellules[3]),
                }
            )
    for g in garanties:
        g["numero_contrat"] = infos["numero_contrat"]
    return infos, garanties


def lire_articles(source: Path) -> list[dict]:
    texte = (source / "conditions_generales.md").read_text(encoding="utf-8")
    articles, partie, courant = [], "", None
    for ligne in texte.splitlines():
        if ligne.startswith("## "):
            partie = ligne[3:].strip()
            continue
        m = re.match(r"### Article (\d+)\. (.+)", ligne)
        if m:
            courant = {"numero": int(m[1]), "titre": m[2].strip(), "titre_partie": partie, "lignes": []}
            articles.append(courant)
        elif courant is not None:
            courant["lignes"].append(ligne)
    for a in articles:
        a["texte"] = "\n".join(a.pop("lignes")).strip()
    return articles


def lire_bareme(source: Path) -> list[dict]:
    with (source / "baremes_franchise.csv").open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    for l in lignes:
        for cle in ("valeur", "minimum", "maximum"):
            l[cle] = float(l[cle]) if l[cle] else None
        l["option"] = l["option"] or None
    return lignes


def inserer(cx: sqlite3.Connection, table: str, lignes: list[dict]) -> None:
    for l in lignes:
        colonnes = ", ".join(l)
        marques = ", ".join("?" * len(l))
        cx.execute(f"INSERT INTO {table} ({colonnes}) VALUES ({marques})", tuple(l.values()))


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_DEFAUT
    if not (source / "declarations").exists():
        sys.exit(f"Dossier source introuvable : {source}")
    BASE.parent.mkdir(exist_ok=True)
    BASE.unlink(missing_ok=True)
    contrats, garanties = [], []
    for chemin in sorted((source / "conditions_particulieres").glob("*.md")):
        infos, gar = lire_contrat(chemin)
        contrats.append(infos)
        garanties += gar
    with sqlite3.connect(BASE) as cx:
        cx.executescript(SCHEMA)
        inserer(cx, "declarations", lire_declarations(source))
        inserer(cx, "contrats", contrats)
        inserer(cx, "garanties", garanties)
        inserer(cx, "articles_cg", lire_articles(source))
        inserer(cx, "bareme", lire_bareme(source))
        n = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("declarations", "contrats", "garanties", "articles_cg", "bareme")}
    cx.close()
    print(f"Base créée : {BASE}")
    print(", ".join(f"{t} {v}" for t, v in n.items()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
