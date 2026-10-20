# E01 : questions clients du cabinet Derval & Associés (jeu fictif)

## Fichiers d'entrée

- faq-cabinet-derval.md : FAQ interne fictive, 19 questions-réponses réparties en 5 sections numérotées (§ 1 à § 5). Les numéros de section sont stables.
- questions-clients.csv : 20 questions clients fictives reçues pendant une semaine (identifiant, nom, numéro de dossier, question), CSV UTF-8 avec en-tête. Ce lot sert de base à la synthèse hebdomadaire.
- questions-clients-semaine-2.csv : 10 questions de la semaine suivante (Q21 à Q30), même structure. Ce lot sert à rejouer le prompt sur un nouveau lot.

## Script de niveau 1

`draft_answers.py` lit un CSV de questions (avec pandas), envoie chaque question au modèle avec `prompt-systeme.md` et la FAQ, puis écrit un brouillon par question et un récapitulatif `recap.md` dans le dossier `drafts/`.

Installation (une fois, depuis `exercices/middle/`) :

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Configuration dans `exercices/.env` :

- `ANTHROPIC_API_KEY` ou `GEMINI_API_KEY` : au moins une clé.
- `LLM_PROVIDER` (facultatif) : `anthropic` ou `gemini`. Sans valeur, le premier fournisseur dont la clé est présente, dans cet ordre.
- `LLM_MODEL` (facultatif) : modèle à utiliser. Par défaut : `claude-opus-5-5` ou `gemini-3.5-flash`.

Le fournisseur, le modèle et la température de cet exercice se règlent plutôt en tête de `draft_answers.py` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE`) : ces constantes priment sur le `.env`, qui est partagé par tous les exercices. `None` rend la main au `.env` ou à la valeur par défaut.

Utilisation (depuis ce dossier) :

```
python draft_answers.py questions-clients.csv
python draft_answers.py questions-clients-semaine-2.csv --output drafts-semaine-2
python draft_answers.py questions-clients.csv --limit 2
pytest
```
