r"""Construit donnees/contrats.db à partir des fichiers du palier middle.

Tables : contrats, sections (une ligne par article ou partie), grille, notes_test,
index_mots (index inversé par mot normalisé, pour la recherche de passages).

Usage :
    ..\.venv\Scripts\python init_donnees.py [chemin_du_dossier_middle]

Par défaut, le dossier source est ../../middle/E11-revue-contrats-fournisseurs.
"""

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from commun import mots

ICI = Path(__file__).parent
SOURCE_DEFAUT = ICI.parent.parent / "middle" / ICI.name
BASE = ICI / "donnees" / "contrats.db"

SCHEMA = """
CREATE TABLE contrats (id TEXT PRIMARY KEY, numero TEXT, fichier TEXT, fournisseur TEXT, texte TEXT);
CREATE TABLE sections (contrat_id TEXT, ordre INTEGER, article INTEGER, titre TEXT, texte TEXT);
CREATE TABLE grille (code TEXT PRIMARY KEY, intitule TEXT, critere TEXT, acceptable TEXT, repli TEXT, refusee TEXT);
CREATE TABLE notes_test (fichier TEXT PRIMARY KEY, texte TEXT);
CREATE TABLE index_mots (mot TEXT, contrat_id TEXT, ordre INTEGER, occurrences INTEGER);
CREATE INDEX idx_mot ON index_mots (mot);
"""


def decouper_contrat(texte: str) -> list[dict]:
    """Une section par titre « ## » ou « ### Article n. Titre » ; le texte suit le titre."""
    sections, courante = [], None
    for ligne in texte.splitlines():
        m_article = re.match(r"### Article (\d+)\. (.+)", ligne)
        m_partie = re.match(r"## (.+)", ligne)
        if m_article or m_partie:
            courante = {
                "article": int(m_article[1]) if m_article else None,
                "titre": (m_article[2] if m_article else m_partie[1]).strip(),
                "lignes": [],
            }
            sections.append(courante)
        elif courante is not None:
            courante["lignes"].append(ligne)
    for ordre, s in enumerate(sections, 1):
        s["ordre"] = ordre
        s["texte"] = "\n".join(s.pop("lignes")).strip()
    return [s for s in sections if s["texte"]]


def lire_grille(texte: str) -> list[dict]:
    clauses = []
    for bloc in re.split(r"\n## ", texte)[1:]:
        entete, _, corps = bloc.partition("\n")
        code, _, intitule = entete.partition(". ")
        champs = dict(re.findall(r"- \*\*(.+?)\*\* : (.+)", corps))
        clauses.append({
            "code": code.strip(), "intitule": intitule.strip(), "critere": champs.get("Critère"),
            "acceptable": champs.get("Acceptable"), "repli": champs.get("Repli"), "refusee": champs.get("Refusée"),
        })
    return clauses


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_DEFAUT
    if not (source / "contrats").exists():
        sys.exit(f"Dossier source introuvable : {source}")
    BASE.parent.mkdir(exist_ok=True)
    BASE.unlink(missing_ok=True)
    cx = sqlite3.connect(BASE)
    cx.executescript(SCHEMA)
    for chemin in sorted((source / "contrats").glob("*.md")):
        texte = chemin.read_text(encoding="utf-8")
        ident = re.match(r"contrat-\d+", chemin.stem)[0]
        numero = re.search(r"n° (CTR-\d{4}-\d{4})", texte)[1]
        fournisseur = re.search(r", et (.+?), dont le siège", texte)
        cx.execute("INSERT INTO contrats VALUES (?, ?, ?, ?, ?)",
                   (ident, numero, chemin.name, fournisseur[1] if fournisseur else None, texte))
        for s in decouper_contrat(texte):
            cx.execute("INSERT INTO sections VALUES (?, ?, ?, ?, ?)", (ident, s["ordre"], s["article"], s["titre"], s["texte"]))
            for mot, n in Counter(mots(s["titre"] + " " + s["texte"])).items():
                cx.execute("INSERT INTO index_mots VALUES (?, ?, ?, ?)", (mot, ident, s["ordre"], n))
    for clause in lire_grille((source / "grille_reference.md").read_text(encoding="utf-8")):
        cx.execute("INSERT INTO grille VALUES (:code, :intitule, :critere, :acceptable, :repli, :refusee)", clause)
    for chemin in sorted((source / "notes_test").glob("*.md")):
        cx.execute("INSERT INTO notes_test VALUES (?, ?)", (chemin.name, chemin.read_text(encoding="utf-8")))
    cx.commit()
    n = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("contrats", "sections", "grille", "notes_test", "index_mots")}
    cx.close()
    print(f"Base créée : {BASE}")
    print(", ".join(f"{t} {v}" for t, v in n.items()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
