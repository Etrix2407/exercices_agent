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

`check_applications.py` lance l'agent `verification_doc` (prompt : `prompt_sys_verification_doc.md`) sur chaque dossier de `candidats/` (les 8 dossiers de l'énoncé). L'agent lit la grille, liste et lit les pièces, puis renvoie un JSON ; pour un dossier incomplet, il écrit un brouillon de relance (l'outil `write_file` ne reçoit que le texte et l'enregistre lui-même sous `relance_<dossier>.txt`). Il ne classe pas les candidats et n'envoie aucun courriel.

Installation (depuis `exercices/middle`) :

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Fichier `.env` à la racine de `exercices/` :

- `GEMINI_API_KEY` : requise avec les réglages actuels (`LLM_PROVIDER = "gemini"` en tête de `check_applications.py`). `ANTHROPIC_API_KEY` ne sert que si l'on passe ces réglages à `anthropic` ou à `None`.
- `LLM_PROVIDER` (facultatif) : `anthropic` ou `gemini` ; pris en compte seulement si la constante du script vaut `None`. Sans valeur, le premier fournisseur dont la clé est présente.
- `LLM_MODEL` (facultatif) : modèle à utiliser, même remarque ; sans valeur, le modèle par défaut du fournisseur.

Le fournisseur, le modèle et la température de cet exercice se règlent en tête de `check_applications.py` (`LLM_PROVIDER = "gemini"`, `LLM_MODEL = "gemini-3.5-flash-lite"`, `LLM_TEMPERATURE = 0.2`) : ces constantes priment sur le `.env`, qui est partagé par tous les exercices. `None` rend la main au `.env` ou à la valeur par défaut.

Commandes (depuis ce dossier) :

```
..\.venv\Scripts\python check_applications.py                   # les 8 dossiers de candidats/
..\.venv\Scripts\python check_applications.py --only marc-dubois # un seul dossier
..\.venv\Scripts\python check_applications.py --grid ma-grille.json --output output-test
..\.venv\Scripts\python check_applications.py --candidates fixtures\candidats --output output\fixtures
..\.venv\Scripts\python -m pytest -q                             # tests, sans réseau
```

Dossiers de test : `fixtures/candidats/` contient des dossiers PDF qui ne font pas partie de l'énoncé (`leroy`, `marchal`, et `pieges` : PDF vide, tronqué ou corrompu). Le lot par défaut ne les traite pas ; on les lance à part avec `--candidates fixtures\candidats` (de préférence avec un autre `--output`, par exemple `output\fixtures`, ignoré par git).

Sorties dans `output/` (ignoré par git) :

- `synthese.md` : tableau Dossier, Candidat, Statut, Pièces manquantes, Incohérences, Brouillon (relance ou transmission écrite pour le dossier), suivi des points à vérifier. Réécrite après chaque dossier (écriture atomique) : si le lot s'interrompt, elle reste lisible et indique l'avancement.
- `relance_<dossier>.txt` : un brouillon de relance par dossier incomplet, à relire par le gestionnaire. Une relance de plus de 120 mots est signalée dans les points à vérifier.
- `transmission_<dossier>.txt` : pour chaque dossier complet **sans point à vérifier**, un brouillon de courriel au propriétaire qui liste les pièces par rubrique de la grille. Le nom du propriétaire est à compléter (`[à compléter]`). Un dossier complet avec des points à vérifier n'a pas de transmission (« transmission non écrite : points à vérifier »).
- `resultats.json` : résultat de chaque dossier (JSON de l'agent complété par les contrôles du script), pour la traçabilité.
- `journal_outils.txt` : chaque appel d'outil de l'agent (heure, dossier, outil, argument), réécrit à chaque exécution.

Statuts de la synthèse :

- `complet`, `incomplet`, `à vérifier` : décision de l'agent selon la grille (une pièce illisible ou refusée donne « à vérifier », jamais « complet »).
- `hors périmètre` : le dossier n'est pas une candidature à la location.
- `erreur` : l'agent n'a pas pu conclure (erreur du modèle, réponse JSON invalide, erreur inattendue du script) ; le motif est dans les points à vérifier.
- `non traité` : le lot a été arrêté avant ce dossier ; le relancer avec `--only`.

Arrêt du lot : un quota épuisé (quota du jour Gemini, limite Anthropic persistante) ou une configuration refusée (clé invalide, modèle introuvable) arrête le lot. Le dossier en cours passe en `erreur`, les suivants en `non traité`, et la synthèse est quand même écrite. Un quota par minute ou une erreur serveur passagère de Gemini est réessayé quelques fois, avec un message dans le terminal ; un appel sans réponse au bout de 5 minutes est abandonné.

Contrôles du script sur la réponse de l'agent : relance présente si et seulement si le dossier est incomplet (une relance contraire au statut est supprimée), sources citées qui ne correspondent à aucun fichier du dossier, relance de plus de 120 mots. Chaque écart est ajouté aux points à vérifier.

Pièces PDF : `read_file` lit aussi les `.pdf` (texte extrait page par page avec pypdf, 5 Mo maximum). Un PDF sans texte extractible (scan), protégé ou corrompu n'est pas compté comme manquant : il est signalé dans les points à vérifier et le dossier ne peut pas être « complet ». Un PDF qui contient du contenu actif est refusé sans être lu (pièce potentiellement malveillante, à vérifier par le gestionnaire sans l'ouvrir) : JavaScript, lancement de programme, fichier joint, formulaire XFA, contenu multimédia actif, ou action automatique à l'ouverture qui ouvre un lien ou un document distant. Un simple lien cliquable n'est pas refusé. `read_file` refuse aussi les fichiers et dossiers cachés (nom commençant par « . »).
