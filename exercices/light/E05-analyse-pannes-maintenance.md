# E05. Analyse des pannes récurrentes d'une ligne de production

Niveau : 1
Secteur : industrie, maintenance

## Contexte

L'usine Fonderies Marchal produit des pièces moulées sur quatre lignes. Les techniciens de maintenance saisissent chaque intervention dans un journal : date, machine, symptôme en texte libre, action réalisée, durée d'arrêt. Le journal compte environ 2 500 entrées par an. Le responsable maintenance prépare chaque mois une revue des pannes pour décider des actions préventives, mais le texte libre rend le regroupement difficile : une même panne est décrite de dix façons différentes. Les pannes récurrentes ne sont identifiées qu'après plusieurs arrêts coûteux.

## Flux actuel

1. Saisie des interventions par les techniciens.
2. Export mensuel du journal en CSV.
3. Lecture et regroupement manuels par le responsable.
4. Présentation en réunion mensuelle.

## Objectif

Développer un agent local qui lit le journal du mois, classe les symptômes dans les catégories du service, identifie les pannes récurrentes par machine et produit une note de revue mensuelle.

## Entrées

- Un journal fictif d'environ 120 interventions sur un mois, 4 lignes, 12 machines, avec des descriptions variées d'une même panne (« fuite hydraulique », « perte de pression vérin », « huile au sol sous presse 3 »).
- Une liste fictive des catégories de panne du service (8 à 10 catégories).

## Sorties attendues

- Le journal enrichi d'une colonne « catégorie » (CSV).
- Une note de revue en Markdown : temps d'arrêt par ligne et par catégorie, trois machines les plus touchées, pannes répétées au moins trois fois sur une même machine, pistes d'actions préventives formulées comme points à étudier.

## Outils nécessaires

- Langage et modèle au choix.
- Outils de l'agent : lecture du CSV, calculs statistiques (fonction écrite en code et exposée comme outil), écriture des sorties.

## Contraintes

- Les calculs (sommes, comptages) sont faits par du code, pas par le modèle.
- Toute catégorie attribuée avec un doute est marquée « à confirmer ».
- La note sert de support de réunion ; les décisions restent au responsable maintenance.

## Critères de réussite

- Au moins 90 % des interventions sont classées dans la bonne catégorie (contrôle sur un échantillon étiqueté à la main).
- Les totaux de temps d'arrêt sont exacts.
- Toutes les pannes répétées au moins trois fois sur une même machine apparaissent dans la note.

## Pistes d'extension

- Comparer deux mois successifs et signaler les tendances.
- Proposer une nouvelle catégorie lorsque plusieurs symptômes ne correspondent à aucune catégorie existante.
- Passer au niveau 2 en créant une demande d'intervention préventive dans un outil de tickets local.
