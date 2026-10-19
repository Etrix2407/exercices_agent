"""Construit les données du kit E06 à partir de donnees/ : boîte mail et base des commandes.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python init_donnees.py
Recrée boite/ (25 courriels non lus, aucun brouillon) et commandes.db.
"""

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from boite_kit import charger_boite

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "donnees"
BOITE = ICI / "boite"
BASE = ICI / "commandes.db"

SCHEMA = """
CREATE TABLE commandes (
    numero TEXT PRIMARY KEY,
    date_commande TEXT NOT NULL,
    statut TEXT NOT NULL,
    client_nom TEXT NOT NULL,
    client_email TEXT NOT NULL,
    total_eur REAL NOT NULL,
    date_livraison TEXT,
    transporteur TEXT,
    numero_suivi TEXT
);
CREATE TABLE articles (
    commande TEXT NOT NULL REFERENCES commandes(numero),
    reference TEXT NOT NULL,
    libelle TEXT NOT NULL,
    quantite INTEGER NOT NULL,
    prix_unitaire_eur REAL NOT NULL
);
CREATE INDEX idx_commandes_email ON commandes(client_email);
"""


def creer_base() -> int:
    BASE.unlink(missing_ok=True)
    commandes = json.loads((DONNEES / "commandes.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(BASE)) as cx, cx:
        cx.executescript(SCHEMA)
        for c in commandes:
            cx.execute(
                "INSERT INTO commandes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (c["numero"], c["date_commande"], c["statut"], c["client"]["nom"], c["client"]["email"],
                 c["total_eur"], c["date_livraison"], c["transporteur"], c["numero_suivi"]),
            )
            for a in c["articles"]:
                cx.execute(
                    "INSERT INTO articles VALUES (?, ?, ?, ?, ?)",
                    (c["numero"], a["reference"], a["libelle"], a["quantite"], a["prix_unitaire_eur"]),
                )
    return len(commandes)


def initialiser() -> None:
    n_mails = charger_boite(DONNEES / "eml", BOITE, "maison-lenoir.test")
    n_cmd = creer_base()
    print(f"Boîte : {n_mails} courriels dans {BOITE}")
    print(f"Base : {n_cmd} commandes dans {BASE}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    initialiser()
