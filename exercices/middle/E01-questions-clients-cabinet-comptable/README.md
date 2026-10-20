# E01 : questions clients du cabinet Derval & Associés (jeu fictif)

## Fichiers d'entrée

- faq-cabinet-derval.md : FAQ interne fictive, 19 questions-réponses réparties en 5 sections numérotées (§ 1 à § 5). Les numéros de section sont stables.
- questions-clients.csv : 20 questions clients fictives reçues pendant une semaine (identifiant, nom, numéro de dossier, question), CSV UTF-8 avec en-tête. Ce lot sert de base à la synthèse hebdomadaire.
- questions-clients-semaine-2.csv : 10 questions de la semaine suivante (Q21 à Q30), même structure. Ce lot sert à rejouer le prompt sur un nouveau lot.

## Script de niveau 1

`draft_answers.py` lit un CSV de questions (avec pandas), envoie chaque question au modèle avec `prompt-systeme.md` et la FAQ, puis écrit un brouillon par question et un récapitulatif `recap.md` dans le dossier `drafts/`. Dans le message envoyé au modèle, la question client est encadrée par des balises `<<< Début de la question client … >>>` / `<<< Fin de la question client >>>` : c'est une donnée, jamais une consigne.

Installation (une fois, depuis `exercices/middle/`) :

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Fournisseur et modèle

Les réglages de cet exercice sont fixés en tête de `draft_answers.py` et priment sur `exercices/.env` (partagé par tous les exercices) :

- `LLM_PROVIDER = "gemini"` ;
- `LLM_MODEL = "gemini-3.5-flash-lite"` : c'est le modèle réellement utilisé (il est rappelé au lancement et en tête de `recap.md`) ;
- `LLM_TEMPERATURE = 0.2` : étiquetage plus régulier d'un lot à l'autre (ignorée par Claude).

Avec ces réglages, **`GEMINI_API_KEY` est requise** dans `exercices/.env` ; `ANTHROPIC_API_KEY` ne sert pas. Pour revenir au `.env`, mettre une constante à `None` : `LLM_PROVIDER` et `LLM_MODEL` du `.env` s'appliquent alors (sans valeur : le premier fournisseur dont la clé est présente, Anthropic puis Gemini, avec `claude-opus-5-5` ou `gemini-3.5-flash` par défaut).

### Utilisation (depuis `exercices/middle/`, venv activé)

```
.venv\Scripts\activate
python E01-questions-clients-cabinet-comptable\draft_answers.py E01-questions-clients-cabinet-comptable\questions-clients.csv
python E01-questions-clients-cabinet-comptable\draft_answers.py E01-questions-clients-cabinet-comptable\questions-clients-semaine-2.csv --output E01-questions-clients-cabinet-comptable\drafts-semaine-2
python E01-questions-clients-cabinet-comptable\draft_answers.py E01-questions-clients-cabinet-comptable\questions-clients.csv --limit 2
python E01-questions-clients-cabinet-comptable\draft_answers.py --check
python E01-questions-clients-cabinet-comptable\draft_answers.py --check-only
python -m pytest E01-questions-clients-cabinet-comptable
```

Sans argument, le script lit `questions-clients.csv` et écrit dans `drafts/` (chemins relatifs au dossier de l'exercice). Les chemins passés en argument sont relatifs au dossier courant.

Options :

- `--limit N` : ne traiter que les N premières questions (pour tester).
- `--check` : après le lot, compare les étiquettes de `recap.md` à `expected_labels.csv` (Q01 à Q30) et affiche « n/N étiquettes conformes » puis la liste des écarts.
- `--check-only` : même comparaison sur le `recap.md` existant du dossier `--output`, sans appeler le modèle (aucune clé requise).

### Erreurs et arrêt du lot

- Une erreur ponctuelle (réponse vide, refus, délai de 5 minutes dépassé, erreur serveur persistante) met la question en `erreur` dans `recap.md` ; le lot continue.
- Un quota épuisé (par exemple le quota du jour de Gemini) ou une configuration refusée (clé invalide, modèle introuvable) **arrête le lot tout de suite** : la question en cours est en `erreur`, les suivantes en `non_traitee`, et `recap.md` est quand même écrit. Relancer plus tard ou changer `LLM_MODEL`.
- Une étiquette autre que « traitable » ou « à transmettre au comptable » apparaît en `non conforme` dans `recap.md`.
- Les brouillons `.md` du dossier de sortie qui ne correspondent à aucune question du lot sont listés en « Fichiers orphelins » dans `recap.md` (rien n'est supprimé).
- Fichier introuvable, CSV vide, mauvais encodage (UTF-8 attendu), colonnes manquantes ou identifiants invalides (caractères autres que lettres, chiffres, `-` et `_`, doublons même à la casse près, identifiant `recap`) : arrêt avec un message clair, avant tout appel au modèle.
