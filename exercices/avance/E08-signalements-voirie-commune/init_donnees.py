"""Construit les données du kit E08 à partir de donnees/ : boîte des signalements et base voirie.db.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python init_donnees.py
Recrée boite/ (30 signalements non lus, aucun brouillon) et voirie.db (référentiel, 8 tickets existants).
"""

import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from boite_kit import charger_boite

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "donnees"
BOITE = ICI / "boite"
BASE = ICI / "voirie.db"

SCHEMA = """
CREATE TABLE voies (
    nom_normalise TEXT PRIMARY KEY,
    type TEXT NOT NULL,          -- rue, place, avenue... ou repere
    alias TEXT NOT NULL,         -- variantes séparées par |
    repere TEXT                  -- pour un point de repère : voie de rattachement
);
CREATE TABLE tickets (
    id TEXT PRIMARY KEY,
    service TEXT NOT NULL CHECK (service IN ('voirie', 'eclairage', 'proprete', 'espaces_verts')),
    categorie TEXT,
    adresse TEXT NOT NULL,
    adresse_a_preciser INTEGER NOT NULL DEFAULT 0,
    urgent INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    message_origine TEXT,
    date_ouverture TEXT NOT NULL,
    statut TEXT NOT NULL CHECK (statut IN ('ouvert', 'en_cours', 'clos'))
);
CREATE TABLE commentaires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL REFERENCES tickets(id),
    texte TEXT NOT NULL,
    message_origine TEXT,
    date TEXT NOT NULL
);
CREATE TABLE alertes_accueil (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL REFERENCES tickets(id),
    message TEXT NOT NULL,
    date TEXT NOT NULL
);
"""


def creer_base() -> tuple[int, int]:
    BASE.unlink(missing_ok=True)
    with (DONNEES / "referentiel_voirie.csv").open(encoding="utf-8", newline="") as f:
        voies = list(csv.DictReader(f))
    tickets = json.loads((DONNEES / "tickets_existants.json").read_text(encoding="utf-8"))
    with closing(sqlite3.connect(BASE)) as cx, cx:
        cx.executescript(SCHEMA)
        cx.executemany(
            "INSERT INTO voies VALUES (?, ?, ?, ?)",
            [(v["nom_normalise"], v["type"], v["alias"], v["repere"] or None) for v in voies],
        )
        cx.executemany(
            "INSERT INTO tickets (id, service, adresse, description, date_ouverture, statut) VALUES (?, ?, ?, ?, ?, ?)",
            [(t["id"], t["service"], t["adresse"], t["description"], t["date_ouverture"], t["statut"]) for t in tickets],
        )
    return len(voies), len(tickets)


def initialiser() -> None:
    n_mails = charger_boite(DONNEES / "eml", BOITE, "saint-aubin-les-pres.example")
    n_voies, n_tickets = creer_base()
    print(f"Boîte : {n_mails} signalements dans {BOITE}")
    print(f"Base : {n_voies} entrées de référentiel, {n_tickets} tickets dans {BASE}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    initialiser()
