"""Construit les données du kit E07 à partir de donnees/ : boîte mail et base hotel.db.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python init_donnees.py
Recrée boite/ (10 demandes non lues, aucun brouillon) et hotel.db (planning, grille, pré-réservations vides).
"""

import csv
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from boite_kit import charger_boite

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "donnees"
BOITE = ICI / "boite"
BASE = ICI / "hotel.db"

SCHEMA = """
CREATE TABLE saisons (saison TEXT PRIMARY KEY, debut TEXT NOT NULL, fin TEXT NOT NULL);
CREATE TABLE types_chambre (type TEXT PRIMARY KEY, nombre INTEGER NOT NULL, personnes INTEGER NOT NULL);
CREATE TABLE tarifs_chambre (
    type TEXT NOT NULL REFERENCES types_chambre(type),
    saison TEXT NOT NULL REFERENCES saisons(saison),
    prix_nuit REAL NOT NULL,
    PRIMARY KEY (type, saison)
);
CREATE TABLE salles (salle TEXT PRIMARY KEY, capacite INTEGER NOT NULL, prix_jour REAL NOT NULL);
CREATE TABLE prestations (code TEXT PRIMARY KEY, libelle TEXT NOT NULL, unite TEXT NOT NULL, prix REAL NOT NULL);
CREATE TABLE occupation_chambres (
    date_nuit TEXT NOT NULL, type TEXT NOT NULL, reference TEXT NOT NULL, nombre INTEGER NOT NULL
);
CREATE TABLE occupation_salles (date TEXT NOT NULL, salle TEXT NOT NULL, reference TEXT NOT NULL, creneau TEXT NOT NULL);
CREATE TABLE pre_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demande TEXT NOT NULL,
    arrivee TEXT NOT NULL,
    depart TEXT NOT NULL,
    chambres TEXT NOT NULL,      -- JSON {type: nombre}
    salles TEXT NOT NULL,        -- JSON [{salle, date}]
    statut TEXT NOT NULL DEFAULT 'a_valider',
    cree_le TEXT NOT NULL,
    valide_le TEXT
);
CREATE INDEX idx_occ_ch ON occupation_chambres(date_nuit);
CREATE INDEX idx_occ_sa ON occupation_salles(date);
"""

# Transcription de donnees/grille_tarifaire.md (euros TTC)
SAISONS = [
    ("basse", "2026-11-01", "2026-12-14"),
    ("haute", "2026-12-15", "2027-01-05"),
    ("intermediaire", "2027-01-06", "2027-01-31"),
]
TYPES = [("simple", 30, 1), ("double", 35, 2), ("twin", 15, 2), ("suite", 5, 2)]
TARIFS = {
    "simple": (95, 135, 110),
    "double": (120, 165, 140),
    "twin": (120, 165, 140),
    "suite": (210, 290, 240),
}
SALLES = [("Cèdre", 120, 650), ("Érable", 60, 380), ("Lys", 20, 180)]
PRESTATIONS = [
    ("petit_dejeuner", "Petit-déjeuner", "par personne logée et par nuit", 16),
    ("dejeuner_buffet", "Déjeuner buffet", "par couvert et par repas", 32),
    ("diner", "Dîner 3 services", "par couvert et par repas", 68),
    ("pause_cafe", "Pause café", "par personne et par pause", 9),
]


def lire_csv(nom: str) -> list[dict]:
    with (DONNEES / nom).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def creer_base() -> tuple[int, int]:
    BASE.unlink(missing_ok=True)
    chambres = lire_csv("planning_chambres.csv")
    salles = lire_csv("planning_salles.csv")
    with closing(sqlite3.connect(BASE)) as cx, cx:
        cx.executescript(SCHEMA)
        cx.executemany("INSERT INTO saisons VALUES (?, ?, ?)", SAISONS)
        cx.executemany("INSERT INTO types_chambre VALUES (?, ?, ?)", TYPES)
        for type_, prix in TARIFS.items():
            for (saison, _, _), p in zip(SAISONS, prix):
                cx.execute("INSERT INTO tarifs_chambre VALUES (?, ?, ?)", (type_, saison, p))
        cx.executemany("INSERT INTO salles VALUES (?, ?, ?)", SALLES)
        cx.executemany("INSERT INTO prestations VALUES (?, ?, ?, ?)", PRESTATIONS)
        cx.executemany(
            "INSERT INTO occupation_chambres VALUES (?, ?, ?, ?)",
            [(l["date_nuit"], l["type_chambre"], l["reference"], int(l["nombre_chambres"])) for l in chambres],
        )
        cx.executemany(
            "INSERT INTO occupation_salles VALUES (?, ?, ?, ?)",
            [(l["date"], l["salle"], l["reference"], l["creneau"]) for l in salles],
        )
    return len(chambres), len(salles)


def initialiser() -> None:
    n_mails = charger_boite(DONNEES / "eml", BOITE, "grand-cedre.example")
    n_ch, n_sa = creer_base()
    print(f"Boîte : {n_mails} demandes dans {BOITE}")
    print(f"Base : {n_ch} lignes de planning chambres, {n_sa} lignes de planning salles dans {BASE}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    initialiser()
