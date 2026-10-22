# Pipeline de notation des agents

Note la performance d'un agent sur 100, à partir de critères pondérés. Ce dossier contient la partie **commune** à tous les exercices. Ce qui est propre à un exercice se trouve dans le dossier `evaluation/` de cet exercice (par exemple `avance/E07-demandes-reservation-hotel/evaluation/`).

## Lancer

Depuis le dossier `exercices`, avec un venv qui a les dépendances de l'agent (par exemple `avance\.venv`) :

```powershell
python -m pytest pipeline_test              # test global : note de chaque agent, échec sous 80/100
python -m pipeline_test e07                 # rapport détaillé sur les sorties actuelles (aucun appel au modèle)
python -m pipeline_test e07 --runs 5        # relance l'agent 5 fois (avec --reset), puis note
python -m pipeline_test --all --runs 3      # tous les exercices qui ont un dossier evaluation/
python -m pipeline_test e07 --rescore avance/E07-demandes-reservation-hotel/evaluation/lancements/20261020-150000
```

`--runs` relance l'agent avec `--reset`, ce qui efface la boîte et les résultats de l'exercice. Le fournisseur et le modèle utilisés sont ceux réglés dans le script de l'agent.

## Organisation

| Commun (`pipeline_test/`) | Rôle |
|---|---|
| `engine.py` | note pondérée sur 100, critères éliminatoires, statistiques sur plusieurs lancements |
| `criteria.py` | critères réutilisables : `exact_match`, `fields_match`, `number_close`, `keywords_found`, `text_rules`, `call_budget`, `no_problems`, `stability` |
| `collectors.py` | lecteurs des sorties : JSON, journal des outils, dossier d'envoi, chargement d'un module d'exercice |
| `registry.py` | trouve chaque `evaluation/adapter.py` sous `exercices/` |
| `report.py` | rapports Markdown et JSON, historique CSV |
| `tests/` | tests du moteur et test global de la note |
| `historique.csv` | une ligne par évaluation, tous exercices confondus |

| Propre à l'exercice (`<exercice>/evaluation/`) | Rôle |
|---|---|
| `adapter.py` | lit les sorties de l'agent et déclare ses critères et leurs poids |
| `attendus.json` | réponses attendues, une entrée par cas (`null` = non évalué) |
| `README.md` | critères de l'exercice |
| `rapports/` | rapports de l'exercice |
| `lancements/` | un instantané par lancement, renotable avec `--rescore` (ignoré par git) |

## Notes

- Si plusieurs lancements sont faits, le rapport donne la moyenne, l'écart-type, le minimum et le maximum.
- Un critère non mesuré (champ attendu à `null`, stabilité avec un seul lancement) ne compte pas : son poids est réparti sur les autres.
- Si un critère **éliminatoire** n'est pas respecté, la note est 0.
- Un cas attendu que l'agent n'a pas traité vaut 0 sur chaque critère qui l'aurait évalué.
- Système multi-agents : si l'adaptateur déclare des `groups` (`Group(nom, critères, filtre des cas)`), chaque sous-agent reçoit sa note et la note globale est leur moyenne (exemple : G01).

## Ajouter un exercice

1. Créer `<exercice>/evaluation/adapter.py`, qui expose `ADAPTER = Adapter(...)` :
   - `name` : nom court, unique (ex. `e04`) ;
   - `kit_dir` et `run_commands` : dossier de l'agent et commandes lancées l'une après l'autre pour un lancement complet (pour `--runs`). `collectors.venv_python(KIT_DIR)` donne le Python du venv du niveau (`middle/.venv`, `avance/.venv`) ;
   - `collect()` : renvoie `{"cases": {id: {...}}, "global": {"modele": ..., ...}}` ;
   - `criteria` : critères composés à partir de `criteria.py`, avec leurs poids.
2. Créer `<exercice>/evaluation/attendus.json`, ainsi que `.gitignore` (`lancements/`).
3. Lancer `python -m pytest pipeline_test` : le nouvel agent est noté automatiquement.

Seules les règles propres au métier sont à écrire dans l'adaptateur. Pour E07, c'est le recalcul du devis et la vérification des dates libres.
