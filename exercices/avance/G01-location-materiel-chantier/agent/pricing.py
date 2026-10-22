"""Calculs de prix en code, à partir de la grille du progiciel (jamais par le modèle).

La grille est relue à chaque appel : les fonctions ne reçoivent que les besoins.
Aucune remise n'est possible.
"""

from __future__ import annotations

import csv
from pathlib import Path

GRID_PATH = Path(__file__).resolve().parents[1] / "donnees" / "progiciel" / "catalogue_tarifs.csv"
TRANSPORT_CODE = "TRA"
# Prestations facturables au retour selon la grille (forfaits).
RETURN_FEE_CODES = ("NET", "CAR")


def load_grid(path: Path = GRID_PATH) -> dict[str, dict]:
    """Grille tarifaire {code: {libelle, type_ligne, unite, tarif_ht_eur}}."""
    with path.open(encoding="utf-8", newline="") as file:
        return {
            row["code"]: {
                "libelle": row["libelle"],
                "type_ligne": row["type_ligne"],
                "unite": row["unite"],
                "tarif_ht_eur": float(row["tarif_ht_eur"]),
            }
            for row in csv.DictReader(file)
        }


def calc_quote(family_code: str, days: int, path: Path = GRID_PATH) -> dict:
    """Devis HT : jours × tarif jour de la famille + transport aller et retour (forfait par contrat)."""
    grid = load_grid(path)
    line = grid.get(family_code)
    if line is None or line["type_ligne"] != "location":
        families = ", ".join(code for code, item in grid.items() if item["type_ligne"] == "location")
        raise ValueError(f"Famille inconnue : {family_code!r}. Codes possibles : {families}.")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError(f"Nombre de jours invalide : {days!r} (entier strictement positif attendu).")
    rental = round(days * line["tarif_ht_eur"], 2)
    transport = grid[TRANSPORT_CODE]["tarif_ht_eur"]
    return {
        "famille": family_code,
        "libelle": line["libelle"],
        "jours": days,
        "tarif_jour_ht": line["tarif_ht_eur"],
        "location_ht": rental,
        "transport_ht": transport,
        "total_ht": round(rental + transport, 2),
    }


def return_fee(code: str, path: Path = GRID_PATH) -> dict:
    """Forfait de retour de la grille (nettoyage lourd NET, carburant CAR)."""
    if code not in RETURN_FEE_CODES:
        raise ValueError(f"Forfait inconnu : {code!r}. Codes possibles : {', '.join(RETURN_FEE_CODES)}.")
    line = load_grid(path)[code]
    return {"code": code, "libelle": line["libelle"], "tarif_ht_eur": line["tarif_ht_eur"]}
