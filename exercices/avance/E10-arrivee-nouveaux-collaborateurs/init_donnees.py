r"""Prépare les données du kit E10 à partir du palier middle.

- copie les fichiers de référence (fiches, référentiel, bureaux, sites, paramètres) dans donnees/ ;
- crée le fichier d'état partagé etat/etat_partage.json à partir de etat_taches.json.

Usage :
    ..\.venv\Scripts\python init_donnees.py [chemin_du_dossier_middle]
    ..\.venv\Scripts\python init_donnees.py --etat-seulement
        (remet seulement l'état partagé à zéro, sans recopier les référentiels de donnees/ :
         un métier ajouté à la main dans le référentiel est conservé)

Par défaut, le dossier source est ../../middle/E10-arrivee-nouveaux-collaborateurs.
Relancer le script remet le fichier d'état dans son état initial.
"""

import json
import shutil
import sys
from pathlib import Path

ICI = Path(__file__).parent
SOURCE_DEFAUT = ICI.parent.parent / "middle" / ICI.name
FICHIERS = ("referentiel_metier_acces.csv", "bureaux_places.csv", "sites.csv", "parametres.json")


def main() -> None:
    arguments = [a for a in sys.argv[1:] if a != "--etat-seulement"]
    etat_seulement = "--etat-seulement" in sys.argv[1:]
    source = Path(arguments[0]) if arguments else SOURCE_DEFAUT
    if not (source / "fiches_arrivee").exists():
        sys.exit(f"Dossier source introuvable : {source}")
    donnees = ICI / "donnees"
    if not etat_seulement:
        (donnees / "fiches_arrivee").mkdir(parents=True, exist_ok=True)
        for nom in FICHIERS:
            shutil.copyfile(source / nom, donnees / nom)
        for fiche in sorted((source / "fiches_arrivee").glob("*.yaml")):
            shutil.copyfile(fiche, donnees / "fiches_arrivee" / fiche.name)

    taches = json.loads((source / "etat_taches.json").read_text(encoding="utf-8"))
    parametres = json.loads((source / "parametres.json").read_text(encoding="utf-8"))
    etat = {
        "date_execution": parametres["date_execution"],
        "arrivees": taches["arrivees"],
        "demandes": [],
        "propositions_bureau": [],
        "relances": [],
        "journal": [],
    }
    (ICI / "etat").mkdir(exist_ok=True)
    (ICI / "etat" / "etat_partage.json").write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
    if not etat_seulement:
        print(f"Données copiées dans {donnees}")
    print(f"État partagé initialisé : {len(etat['arrivees'])} arrivées")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
