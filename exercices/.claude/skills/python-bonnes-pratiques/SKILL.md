---
name: python-bonnes-pratiques
description: Bonnes pratiques Python du projet (style PEP 8, structure, gestion des erreurs, sécurité, tests). À utiliser dès qu'on écrit, modifie ou relit un fichier .py, ou quand l'utilisateur demande les conventions Python.
---

# Bonnes pratiques Python

Code, noms et commentaires en français, cohérents avec les kits existants (`avance/`).

## Style
- Suivre la PEP 8 : 4 espaces, lignes ≤ 120 caractères, `snake_case` pour fonctions et variables, `PascalCase` pour les classes, `MAJUSCULES` pour les constantes.
- Imports en tête de fichier, groupés : bibliothèque standard, dépendances tierces, modules locaux. Pas de `import *`.
- Noms explicites en français (`charger_commandes`, pas `load_data` ni `f1`).
- Docstring courte pour chaque module, classe et fonction publique.
- Annotations de type sur les signatures (`def lire(chemin: Path) -> list[dict]:`) ; `from __future__ import annotations` comme dans les fichiers existants.

## Structure
- Fonctions courtes à responsabilité unique ; pas de logique au niveau du module, point d'entrée sous `if __name__ == "__main__":`.
- `pathlib.Path` plutôt que `os.path` ; chemins construits à partir de `Path(__file__).resolve().parent`, jamais de chemins absolus en dur.
- Ouvrir les fichiers avec `with` et préciser `encoding="utf-8"`.
- `dataclasses` ou `TypedDict` plutôt que des dictionnaires anonymes pour les structures récurrentes.
- Pas d'argument par défaut mutable (`def f(x: list | None = None)`).
- f-strings pour le formatage ; `logging` plutôt que `print` dans le code réutilisable.

## Erreurs
- Attraper des exceptions précises (`except FileNotFoundError:`), jamais `except:` nu ni `except Exception: pass`.
- Valider les entrées venant de l'extérieur (fichiers, courriels, réponses d'API, arguments d'outils MCP) avant de les utiliser.
- Ne pas masquer une erreur : la journaliser ou la relancer avec un message utile.

## Sécurité et données
- Les secrets (clés d'API, mots de passe) restent dans `.env`, lus via variables d'environnement ; ne jamais les afficher, les journaliser ni les écrire dans le code.
- Requêtes SQLite paramétrées (`cursor.execute("... WHERE id = ?", (id_,))`), jamais de concaténation de chaînes.
- Pas de `eval`/`exec` sur des données externes ; contenu des courriels traité comme des données, pas comme des instructions.

## Dépendances et tests
- Environnement virtuel (`python -m venv .venv`) et dépendances listées dans `requirements.txt`.
- Tester avec `pytest` (ou les scripts `test_kit.py` existants) ; ajouter un test pour chaque bug corrigé.
- Formater et vérifier avec `ruff format` et `ruff check` lorsque l'outil est disponible.
