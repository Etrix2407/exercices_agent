# E04. Dossiers de candidature locative (données fictives)

Logement fictif LOG-DEL-0417, loyer de 950,00 EUR hors charges. Date de référence du contrôle : 14/10/2026.

## Fichiers d'entrée (51)

- grille.json : pièces exigées, fraîcheur, règle du garant, règle de statut.
- candidats/ : 8 sous-dossiers, 50 fichiers .txt au total :
  - lea-vanderstraeten (7 fichiers).
  - marc-dubois (5 fichiers).
  - sophie-lambert (8 fichiers).
  - karim-benali (6 fichiers).
  - nathalie-fontaine (6 fichiers).
  - thomas-verhoeven (6 fichiers).
  - ines-claes (6 fichiers).
  - olivier-mertens (6 fichiers).

## Script de niveau 1

`check_applications.py` lance l'agent `verification_doc` (prompt : `prompt_sys_verification_doc.md`) sur chaque dossier de `candidats/`. L'agent lit la grille, liste et lit les pièces, puis renvoie un JSON ; pour un dossier incomplet, il écrit un brouillon de relance. Il ne classe pas les candidats et n'envoie aucun courriel.

Installation (depuis `exercices/middle`) :

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Fichier `.env` à la racine de `exercices/` :

- `ANTHROPIC_API_KEY` ou `API_KEY_GEMINI` : clé d'API du fournisseur.
- `LLM_PROVIDER` (facultatif) : `anthropic` ou `gemini` ; sans valeur, le premier fournisseur dont la clé est présente.
- `LLM_MODEL` (facultatif) : modèle à utiliser ; sans valeur, le modèle par défaut du fournisseur.

Le fournisseur, le modèle et la température de cet exercice se règlent plutôt en tête de `check_applications.py` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE`) : ces constantes priment sur le `.env`, qui est partagé par tous les exercices. `None` rend la main au `.env` ou à la valeur par défaut.

Commandes (depuis ce dossier) :

```
..\.venv\Scripts\python check_applications.py                   # tous les dossiers
..\.venv\Scripts\python check_applications.py --only marc-dubois # un seul dossier
..\.venv\Scripts\python check_applications.py --grid ma-grille.json --output output-test
..\.venv\Scripts\python -m pytest -q                             # tests, sans réseau
```

Sorties dans `output/` (ignoré par git) :

- `synthese.md` : tableau Dossier, Candidat, Statut (complet, incomplet, à vérifier), Pièces manquantes, Incohérences, Relance.
- `relance_<dossier>.txt` : un brouillon de relance par dossier incomplet, à relire par le gestionnaire.
- `transmission_<dossier>.txt` : pour chaque dossier complet, un brouillon de courriel au propriétaire qui liste les pièces par rubrique de la grille. Le nom du propriétaire est à compléter (`[à compléter]`).
- `resultats.json` : réponse JSON de l'agent pour chaque dossier, pour la traçabilité.
- `journal_outils.txt` : chaque appel d'outil de l'agent (heure, dossier, outil, argument), réécrit à chaque exécution.

Pièces PDF : `read_file` lit aussi les `.pdf` (texte extrait page par page avec pypdf, 5 Mo maximum). Un PDF sans texte extractible (scan), protégé ou corrompu n'est pas compté comme manquant : il est signalé dans les points à vérifier.
