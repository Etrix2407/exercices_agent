"""Fonctions partagées par les serveurs du kit E10 : lecture des référentiels, état partagé, dates.

Les référentiels (CSV, YAML, JSON de donnees/) sont relus à chaque appel : une ligne ajoutée
dans un fichier est prise en compte sans redémarrer les serveurs ni modifier le code.
"""

import csv
import json
import os
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

ICI = Path(__file__).parent
DONNEES = Path(os.environ.get("E10_DONNEES", ICI / "donnees"))
ETAT = Path(os.environ.get("E10_ETAT", ICI / "etat" / "etat_partage.json"))
SORTIES = Path(os.environ.get("E10_SORTIES", ICI / "sorties"))


# --- Référentiels -----------------------------------------------------------------


def lire_csv(nom: str) -> list[dict]:
    with (DONNEES / nom).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def lire_json(nom: str) -> dict:
    return json.loads((DONNEES / nom).read_text(encoding="utf-8"))


def lire_yaml_simple(chemin: Path) -> dict:
    """Lecteur YAML minimal pour les fiches : « cle: valeur », « cle: [] » et listes « - élément »."""
    resultat, cle_liste = {}, None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if ligne.lstrip().startswith("- ") and cle_liste:
            resultat[cle_liste].append(ligne.lstrip()[2:].strip().strip('"'))
            continue
        cle, _, valeur = ligne.partition(":")
        valeur = valeur.strip()
        if valeur in ("", "[]"):
            resultat[cle.strip()], cle_liste = [], cle.strip()
        else:
            resultat[cle.strip()], cle_liste = valeur.strip('"'), None
    return resultat


def fiches() -> dict[str, dict]:
    return {f["id"]: f for f in map(lire_yaml_simple, sorted((DONNEES / "fiches_arrivee").glob("*.yaml")))}


# --- Dates -------------------------------------------------------------------------


def jours_feries() -> set[date]:
    chemin = DONNEES / "jours_feries.json"
    if chemin.exists():
        return {date.fromisoformat(j) for j in json.loads(chemin.read_text(encoding="utf-8"))["jours"]}
    return set()


def retrancher_jours_ouvres(depart: date, nombre: int) -> date:
    """Date située « nombre » jours ouvrés avant « depart »."""
    feries, j, n = jours_feries(), depart, 0
    while n < nombre:
        j -= timedelta(days=1)
        if j.weekday() < 5 and j not in feries:
            n += 1
    return j


# --- État partagé ------------------------------------------------------------------


def remplacer_fichier(source: Path, cible: Path, essais: int = 50) -> None:
    """os.replace avec nouvelles tentatives : sous Windows, un antivirus ou l'indexation peut ouvrir
    brièvement le fichier cible et provoquer un refus d'accès (WinError 5)."""
    for n in range(essais):
        try:
            os.replace(source, cible)
            return
        except PermissionError:
            if n == essais - 1:
                raise
            time.sleep(0.05)


@contextmanager
def etat_verrouille(ecriture: bool = True):
    """Ouvre l'état partagé sous verrou (fichier .lock) ; écrit le résultat de façon atomique.

    Plusieurs agents (donc plusieurs processus serveurs) peuvent lire et écrire le même fichier.
    """
    if not ETAT.exists():
        raise FileNotFoundError(f"État absent : {ETAT}. Lancer init_donnees.py.")
    verrou = ETAT.with_suffix(".lock")
    limite = time.monotonic() + 10
    while True:
        try:
            fd = os.open(verrou, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):  # Windows : verrou en cours de suppression
            if time.monotonic() > limite:
                raise TimeoutError(f"Verrou occupé : {verrou}. Le supprimer s'il est resté après un arrêt brutal.")
            time.sleep(0.05)
    try:
        etat = json.loads(ETAT.read_text(encoding="utf-8"))
        yield etat
        if ecriture:
            temporaire = ETAT.with_suffix(".tmp")
            temporaire.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
            remplacer_fichier(temporaire, ETAT)
    finally:
        os.close(fd)
        verrou.unlink(missing_ok=True)


def lire_etat() -> dict:
    with etat_verrouille(ecriture=False) as etat:
        return etat
