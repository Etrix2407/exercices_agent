# E05. Analyse des pannes d'une ligne de production (données fictives, mars 2026)

Usine fictive Fonderies Marchal : 4 lignes, 12 machines, 120 interventions.

## Fichiers

- journal_pannes_mois.csv : 120 interventions de mars 2026 (identifiant, date, heure, ligne, machine, symptôme en texte libre, action, durée d'arrêt, technicien). Pas de colonne catégorie.
- categories_panne.csv : les 9 catégories du service, avec une description générale.
- echantillon_etiquete.csv : 20 interventions étiquetées à la main (identifiant, catégorie), pour le contrôle de 90 %.
