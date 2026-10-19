r"""Crée la base parc.db et la boîte mail fictive à partir de donnees/.

Base SQLite (tables de référence en lecture seule, protégées par déclencheurs) :
    catalogue             familles de machines et prestations forfaitaires
    machines              export du parc (60 machines, 5 agences)
    contrats              37 contrats de location
    demandes_non_servies  refus de location faute de disponibilité
    controles             échéancier des contrôles réglementaires
    factures              factures en attente de paiement
    habilitations         habilitations des intervenants
    documents             bons de livraison et de reprise, comptes rendus d'atelier,
                          fiches de sécurité (texte intégral et références extraites)
    brouillons            seule table modifiable : propositions de modification
                          soumises à validation humaine (statut « brouillon » imposé)

Boîte mail : boite/inbox/ reçoit les 18 demandes des agences et les 7 contestations.

Usage :
    ..\.venv\Scripts\python init_donnees.py [--base parc.db] [--boite boite]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import boite_kit

DOSSIER = Path(__file__).parent
DONNEES = DOSSIER / "donnees"
BASE_DEFAUT = DOSSIER / "parc.db"

# Colonnes TEXT par défaut ; montants et compteurs convertis.
TABLES_CSV = {
    "catalogue": ("progiciel/catalogue_tarifs.csv", {"tarif_ht_eur": float}),
    "machines": ("progiciel/export_parc.csv", {"compteur_heures": int}),
    "contrats": ("progiciel/contrats_location.csv",
                 {"duree_prevue_jours": int, "duree_facturee_jours": int, "montant_ht_eur": float}),
    "demandes_non_servies": ("progiciel/demandes_non_servies.csv", {"duree_souhaitee_jours": int}),
    "controles": ("atelier/echeancier_controles.csv", {}),
    "factures": ("facturation/factures_impayees.csv", {"montant_ttc_eur": float, "nombre_relances": int}),
    "habilitations": ("rh_securite/habilitations.csv", {}),
}
CLES = {"catalogue": "code", "machines": "reference_machine", "contrats": "contrat_id", "factures": "facture_id"}

DOCUMENTS = [
    ("plateforme/bons_livraison", None),
    ("atelier/comptes_rendus_retour", "compte_rendu_retour"),
    ("rh_securite/fiches_securite", "fiche_securite"),
]

SCHEMA_SUPPLEMENTAIRE = """
CREATE TABLE documents (
    reference         TEXT PRIMARY KEY,
    type              TEXT NOT NULL,
    date_document     TEXT,
    contrat_id        TEXT,
    reference_machine TEXT,
    fichier           TEXT NOT NULL,
    texte             TEXT NOT NULL
);

CREATE TABLE brouillons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT NOT NULL CHECK (type IN ('statut_machine', 'blocage_machine', 'correction_facture',
                  'relance', 'dossier_litige', 'planning', 'alerte', 'autre')),
    cible         TEXT NOT NULL,
    contenu       TEXT NOT NULL,
    justification TEXT NOT NULL,
    sources       TEXT NOT NULL DEFAULT '[]',
    statut        TEXT NOT NULL DEFAULT 'brouillon' CHECK (statut = 'brouillon'),
    cree_le       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""

DECLENCHEURS = """
CREATE TRIGGER {t}_sans_ajout BEFORE INSERT ON {t}
BEGIN SELECT RAISE(ABORT, 'table {t} en lecture seule : passer par un brouillon'); END;
CREATE TRIGGER {t}_sans_maj BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, 'table {t} en lecture seule : passer par un brouillon'); END;
CREATE TRIGGER {t}_sans_suppr BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, 'table {t} en lecture seule : passer par un brouillon'); END;
"""


def _valeur(v: str, conversion):
    if v == "":
        return None
    return conversion(v) if conversion else v


def charger_csv(cx: sqlite3.Connection, table: str, chemin: Path, conversions: dict) -> int:
    with chemin.open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    colonnes = list(lignes[0].keys())
    definitions = []
    for c in colonnes:
        type_sql = {float: "REAL", int: "INTEGER"}.get(conversions.get(c), "TEXT")
        definitions.append(f'"{c}" {type_sql}{" PRIMARY KEY" if CLES.get(table) == c else ""}')
    cx.execute(f"CREATE TABLE {table} ({', '.join(definitions)})")
    cx.executemany(
        f"INSERT INTO {table} VALUES ({', '.join('?' * len(colonnes))})",
        [[_valeur(l[c], conversions.get(c)) for c in colonnes] for l in lignes],
    )
    return len(lignes)


def lire_document(chemin: Path, type_defaut: str | None) -> tuple:
    texte = chemin.read_text(encoding="utf-8")
    premiere = texte.splitlines()[0]
    if type_defaut is None:
        type_doc = "bon_reprise" if premiere.startswith("BON DE REPRISE") else "bon_livraison"
    else:
        type_doc = type_defaut
    date = re.search(r"(?m)^Date(?: de retour)? : (\d{2})/(\d{2})/(\d{4})", texte)
    contrat = re.search(r"LOC-\d{4}-\d{4}", texte)
    machine = re.search(r"\b(?:MPE|NCI|NAR|ECH|GEL|BUN|CHE|CPR)-\d{3}\b", texte)
    return (
        chemin.stem.split("_")[0],
        type_doc,
        f"{date[3]}-{date[2]}-{date[1]}" if date else None,
        contrat[0] if contrat else None,
        machine[0] if machine else None,
        str(chemin.relative_to(DONNEES)).replace("\\", "/"),
        texte,
    )


def creer_base(base: Path = BASE_DEFAUT) -> dict:
    if base.exists():
        base.unlink()
    effectifs = {}
    cx = sqlite3.connect(base)
    try:
        for table, (fichier, conversions) in TABLES_CSV.items():
            effectifs[table] = charger_csv(cx, table, DONNEES / fichier, conversions)
        cx.executescript(SCHEMA_SUPPLEMENTAIRE)
        docs = [lire_document(p, t) for dossier, t in DOCUMENTS for p in sorted((DONNEES / dossier).glob("*.txt"))]
        cx.executemany("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", docs)
        effectifs["documents"] = len(docs)
        for table in [*TABLES_CSV, "documents"]:
            cx.executescript(DECLENCHEURS.format(t=table))
        cx.commit()
    finally:
        cx.close()
    return effectifs


def creer_boite(racine: Path = boite_kit.RACINE) -> int:
    if racine.exists():
        shutil.rmtree(racine)
    for dossier in ("inbox", "outbox", "archive"):
        (racine / dossier).mkdir(parents=True)
    sources = sorted((DONNEES / "plateforme").glob("demande_*.eml")) + sorted(
        (DONNEES / "facturation" / "contestations").glob("contestation_*.eml")
    )
    for source in sources:
        (racine / "inbox" / source.name).write_bytes(boite_kit.normaliser_eml(source))
    (racine / "etat.json").write_text(json.dumps({}), encoding="utf-8")
    return len(sources)


def main() -> None:
    parser = argparse.ArgumentParser(description="Base du parc et boîte mail fictives")
    parser.add_argument("--base", type=Path, default=BASE_DEFAUT)
    parser.add_argument("--boite", type=Path, default=boite_kit.RACINE)
    args = parser.parse_args()
    effectifs = creer_base(args.base)
    n = creer_boite(args.boite)
    print(f"Base créée : {args.base}")
    print("  " + ", ".join(f"{t} {n}" for t, n in effectifs.items()))
    print(f"Boîte créée : {args.boite} ({n} messages)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
