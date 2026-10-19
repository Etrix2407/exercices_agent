# E04. Complétude des dossiers de candidature locative

Niveau : 1
Secteur : immobilier

## Contexte

L'agence Habitat Delorme gère 900 logements en location. Pour chaque logement libéré, l'agence reçoit 10 à 40 dossiers de candidature, déposés en ligne puis copiés dans un dossier par candidat. Un dossier est recevable s'il contient les pièces exigées par la grille interne : identité, justificatifs de revenus, avis d'imposition, attestation d'employeur ou équivalent, garant le cas échéant. Les gestionnaires passent l'essentiel de leur temps à vérifier la présence et la cohérence des pièces, puis à relancer les candidats incomplets. L'étude des dossiers complets reste du ressort du gestionnaire.

## Flux actuel

1. Le candidat dépose ses pièces.
2. Le gestionnaire ouvre chaque dossier et coche une grille papier.
3. Il rédige un courriel de relance listant les pièces manquantes.
4. Les dossiers complets sont présentés au propriétaire.

## Objectif

Développer un agent local qui parcourt les dossiers d'un logement, vérifie la complétude selon la grille, relève les incohérences simples (nom différent entre deux pièces, document trop ancien) et rédige un brouillon de relance pour chaque dossier incomplet.

## Entrées

- Une grille de pièces exigées, au format YAML ou JSON, fictive.
- 8 dossiers de candidats fictifs, chacun dans un sous-dossier contenant des fichiers texte qui simulent les pièces (contenu résumé, dates, montants). Prévoir des dossiers complets, incomplets et incohérents.

## Sorties attendues

- Un tableau de synthèse : candidat, statut (complet, incomplet, à vérifier), pièces manquantes, incohérences relevées.
- Un brouillon de courriel de relance par dossier incomplet, enregistré en fichier texte.

## Outils nécessaires

- Langage et modèle au choix.
- Outils de l'agent : lister un dossier, lire un fichier, lire la grille, écrire un fichier de sortie.

## Contraintes

- L'agent ne classe pas les candidats et ne donne aucun avis sur l'attribution du logement.
- Aucun envoi de courriel : uniquement des brouillons.
- Le gestionnaire valide chaque relance.

## Critères de réussite

- Le statut de chaque dossier est exact au regard de la grille.
- Toutes les pièces manquantes sont listées, sans pièce manquante inventée.
- Les incohérences de nom et de date sont toutes relevées.
- La grille peut être modifiée (ajout d'une pièce) sans changer le code de l'agent.

## Pistes d'extension

- Lire des fichiers PDF fictifs générés pour l'exercice.
- Journaliser chaque appel d'outil pour permettre de retracer le traitement.
- Ajouter un mode qui ne retraite que les dossiers modifiés depuis la dernière exécution.
