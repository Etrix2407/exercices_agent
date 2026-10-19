r"""Crée la base SQLite planning.db à partir des fichiers de donnees/.

Tables :
    specialites   référentiel (courrier d'adressage requis, délais cibles en jours)
    demandes      lot de la nuit (40 demandes fictives)
    creneaux      créneaux libres sur quatre semaines
    propositions  brouillons écrits par l'agent (une ligne par demande au plus)

Les tables demandes, specialites et creneaux sont protégées par des déclencheurs :
aucune modification ni suppression n'est possible, même par erreur de l'agent.
La table propositions n'accepte que le statut « brouillon » : la confirmation
d'un rendez-vous reste hors de portée de l'agent.

Usage :
    ..\.venv\Scripts\python init_donnees.py [--base chemin.db]
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

DOSSIER = Path(__file__).parent
DONNEES = DOSSIER / "donnees"
BASE_DEFAUT = DOSSIER / "planning.db"

SCHEMA = """
CREATE TABLE specialites (
    nom                  TEXT PRIMARY KEY,
    courrier_requis      INTEGER NOT NULL CHECK (courrier_requis IN (0, 1)),
    delai_urgent_j       INTEGER NOT NULL,
    delai_prioritaire_j  INTEGER NOT NULL,
    delai_standard_j     INTEGER NOT NULL
);

CREATE TABLE demandes (
    id_demande           TEXT PRIMARY KEY,
    date_depot           TEXT NOT NULL,
    canal                TEXT NOT NULL,
    identifiant_patient  TEXT NOT NULL,
    nom_fictif           TEXT NOT NULL,
    niss_fictif          TEXT NOT NULL,
    specialite_demandee  TEXT,
    motif                TEXT NOT NULL,
    courrier_adressage   INTEGER NOT NULL CHECK (courrier_adressage IN (0, 1))
);

CREATE TABLE creneaux (
    id_creneau     TEXT PRIMARY KEY,
    specialite     TEXT NOT NULL REFERENCES specialites (nom),
    date           TEXT NOT NULL,
    heure          TEXT NOT NULL,
    duree_minutes  INTEGER NOT NULL,
    statut         TEXT NOT NULL
);

-- id_creneau UNIQUE : un créneau ne peut figurer que dans une seule proposition.
CREATE TABLE propositions (
    id_demande          TEXT PRIMARY KEY REFERENCES demandes (id_demande),
    specialite_retenue  TEXT NOT NULL REFERENCES specialites (nom),
    priorite            TEXT NOT NULL CHECK (priorite IN ('urgent', 'prioritaire', 'standard', 'incertaine')),
    justification       TEXT NOT NULL,
    pieces_manquantes   TEXT NOT NULL DEFAULT '',
    id_creneau          TEXT UNIQUE REFERENCES creneaux (id_creneau),
    motif_sans_creneau  TEXT NOT NULL DEFAULT '',
    a_revoir            INTEGER NOT NULL DEFAULT 0 CHECK (a_revoir IN (0, 1)),
    statut              TEXT NOT NULL DEFAULT 'brouillon' CHECK (statut = 'brouillon'),
    cree_le             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""

DECLENCHEURS = """
CREATE TRIGGER {t}_sans_maj BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, 'table {t} en lecture seule'); END;
CREATE TRIGGER {t}_sans_suppr BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, 'table {t} en lecture seule'); END;
"""


def lire_referentiel(chemin: Path) -> list[tuple]:
    """Extrait le tableau des spécialités du fichier Markdown."""
    lignes = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if len(cellules) == 5 and re.fullmatch(r"\d+", cellules[2] or ""):
            nom, courrier, urgent, prioritaire, standard = cellules
            lignes.append((nom, 1 if courrier == "oui" else 0, int(urgent), int(prioritaire), int(standard)))
    return lignes


def lire_csv(chemin: Path) -> list[dict]:
    with chemin.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def creer_base(base: Path = BASE_DEFAUT) -> Path:
    if base.exists():
        base.unlink()
    specialites = lire_referentiel(DONNEES / "referentiel_specialites.md")
    demandes = lire_csv(DONNEES / "demandes_jour.csv")
    creneaux = lire_csv(DONNEES / "planning_creneaux.csv")

    cx = sqlite3.connect(base)
    try:
        cx.executescript(SCHEMA)
        cx.executemany("INSERT INTO specialites VALUES (?, ?, ?, ?, ?)", specialites)
        cx.executemany(
            "INSERT INTO demandes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    d["id_demande"], d["date_depot"], d["canal"], d["identifiant_patient"], d["nom_fictif"],
                    d["niss_fictif"], d["specialite_demandee"] or None, d["motif"],
                    1 if d["courrier_adressage"] == "oui" else 0,
                )
                for d in demandes
            ],
        )
        cx.executemany(
            "INSERT INTO creneaux VALUES (?, ?, ?, ?, ?, ?)",
            [(c["id_creneau"], c["specialite"], c["date"], c["heure"], int(c["duree_minutes"]), c["statut"]) for c in creneaux],
        )
        for table in ("specialites", "demandes", "creneaux"):
            cx.executescript(DECLENCHEURS.format(t=table))
        cx.commit()
    finally:
        cx.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description="Création de la base fictive des demandes et créneaux")
    parser.add_argument("--base", type=Path, default=BASE_DEFAUT)
    args = parser.parse_args()
    base = creer_base(args.base)
    with sqlite3.connect(base) as cx:
        n = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("specialites", "demandes", "creneaux")}
    cx.close()
    print(f"Base créée : {base}")
    print(f"  {n['specialites']} spécialités, {n['demandes']} demandes, {n['creneaux']} créneaux")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
