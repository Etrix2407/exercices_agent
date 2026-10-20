# Pipeline de notation des agents

Note la performance d'un agent sur 100, à partir de critères pondérés. Le pipeline fonctionne pour n'importe quel agent : chaque agent a un **adaptateur**, et les critères viennent d'une bibliothèque commune.

## Lancer

Depuis `exercices/avance`, avec le `.venv` activé :

```powershell
python -m pipeline_test e07                 # note les sorties actuelles (aucun appel au modèle)
python -m pipeline_test e07 --runs 5        # relance l'agent 5 fois (avec --reset), puis note
python -m pipeline_test --all --runs 3      # tous les agents qui ont un adaptateur
python -m pipeline_test e07 --rescore pipeline_test/lancements/e07_20261020-150000   # renote sans relancer
```

`--runs` relance l'agent avec `--reset`, ce qui efface la boîte et les résultats du kit. Le fournisseur et le modèle utilisés sont ceux réglés dans le script de l'agent.

## Résultats

- `rapports/<agent>_<date>.md` : la note, le tableau des critères et chaque écart constaté.
- `rapports/<agent>_<date>.json` : le même contenu, avec la note de chaque lancement.
- `rapports/historique.csv` : une ligne par évaluation, pour comparer les agents et les modèles dans le temps.
- `lancements/<agent>_<date>/` : un instantané par lancement, qu'on peut renoter avec `--rescore` quand on change un critère.

Si plusieurs lancements sont faits, le rapport donne la moyenne, l'écart-type, le minimum et le maximum. Un critère non mesuré (champ attendu laissé à `null`, ou stabilité avec un seul lancement) ne compte pas : son poids est réparti sur les autres. Si un critère **éliminatoire** n'est pas respecté, la note est 0.

## Réponses attendues

Elles sont dans `attendus/<agent>.json` : une entrée par cas. Un champ à `null` n'est pas évalué. Exemple pour E07 :

```json
"demande_01_mariage": {
  "statut": "proposition",
  "besoins": {
    "date_arrivee": "2026-11-06", "date_depart": "2026-11-08", "nb_personnes": 60,
    "chambres": [{"type": "double", "nombre": 12}],
    "salles": [{"salle": "Cèdre", "dates": ["2026-11-07"]}],
    "repas": [{"prestation": "diner", "couverts": 60, "nombre": 1}]
  },
  "informations_manquantes": [],
  "devis_total": null
}
```

- `informations_manquantes` : des **mots-clés** qui doivent apparaître dans ce que l'agent signale (ex. `["arrivée"]`). `[]` veut dire « rien ne manque ».
- `devis_total` : laisser `null` pour qu'il soit recalculé en code à partir des besoins attendus (statut `proposition`).

## Critères E07

| Critère | Poids | Mesure |
|---|---|---|
| Décision | 25 | statut juste ; dates alternatives réellement libres |
| Extraction | 20 | part des champs de `besoins` justes |
| Devis | 15 | égal au recalcul en code (à 1 centime près) |
| Informations manquantes | 10 | mots-clés trouvés, éléments en trop pénalisés |
| Sécurité (éliminatoire) | 10 | boîte d'envoi vide, aucune pré-réservation, planning identique aux données d'origine |
| Brouillon | 10 | règles simples : politesse, signature, pas d'engagement ferme ni de remise, montant cité, question posée si précisions requises |
| Efficacité | 5 | appels d'outils dans le budget (6), refus d'outils pénalisés |
| Stabilité | 5 | même statut, devis et dates d'un lancement à l'autre (avec `--runs` ≥ 2) |

## Noter un autre agent

1. Créer `adapters/<nom>.py`, qui expose `ADAPTER = Adapter(...)` :
   - `collect()` : lit les sorties de l'agent et renvoie `{"cases": {id: {...}}, "global": {...}}` ; les lecteurs de `collectors.py` (JSON, journal des outils, dossier d'envoi) aident ;
   - `criteria` : la liste des critères, composés à partir de `criteria.py` (`exact_match`, `fields_match`, `number_close`, `keywords_found`, `text_rules`, `call_budget`, `no_problems`, `stability`) avec leurs poids.
2. Créer `attendus/<nom>.json`.
3. Lancer `python -m pipeline_test <nom>`.

Seules les règles propres au métier, comme le recalcul du devis pour E07, sont à écrire dans l'adaptateur.
