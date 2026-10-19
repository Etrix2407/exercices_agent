# E11. Revue des contrats fournisseurs

Niveau : 3
Secteur : juridique

## Contexte

Le service juridique de la société Albret Distribution (deux juristes) relit tous les contrats proposés par les fournisseurs avant signature : environ 40 contrats par mois, de 5 à 30 pages. Le service dispose d'une grille de référence qui fixe, pour chaque clause sensible (durée, reconduction tacite, résiliation, pénalités, responsabilité, juridiction, confidentialité, révision des prix), la position acceptable, la position de repli et les positions refusées. Les acheteurs attendent en moyenne 12 jours le retour du juridique. La plupart des contrats sont standards et ne posent de problème que sur une ou deux clauses.

## Flux actuel

1. L'acheteur transmet le contrat au service juridique.
2. Un juriste lit le contrat en entier et compare chaque clause à la grille.
3. Il rédige une note de revue avec les clauses à renégocier et des propositions de rédaction.
4. L'acheteur négocie avec le fournisseur.

## Objectif

Concevoir un système de plusieurs agents :

- un agent d'extraction qui découpe le contrat et identifie les clauses de la grille ;
- un agent d'analyse qui compare chaque clause à la grille et la classe (conforme, repli, refusée, absente) ;
- un agent de rédaction qui propose une reformulation pour chaque clause refusée ;
- un agent contradicteur qui relit la note et signale les affirmations non étayées par le texte du contrat.

## Entrées

- Une grille de référence fictive (10 clauses, trois positions chacune).
- 5 contrats fictifs en Markdown ou texte, de 4 à 10 pages, contenant des clauses conformes, des clauses à risque et au moins une clause importante absente.

## Sorties attendues

- Une note de revue par contrat : tableau des clauses avec classement, citation exacte du passage du contrat, référence à la grille, proposition de reformulation pour les clauses refusées.
- Une synthèse d'une page pour l'acheteur : niveau de risque global et clauses à négocier en priorité.
- La liste des remarques de l'agent contradicteur et leur traitement.

## Outils nécessaires

- Langage et modèle au choix ; orchestration au choix.
- Outils : lecture des contrats et de la grille, recherche de passages dans le texte, écriture des notes.

## Contraintes

- Chaque classement cite le passage exact du contrat ; une citation introuvable dans le texte source invalide le classement.
- Aucune note n'est transmise à l'acheteur sans validation par un juriste.
- Les agents ne communiquent pas avec le fournisseur.

## Critères de réussite

- Toutes les clauses en position refusée dans les 5 contrats sont détectées.
- Chaque clause absente est signalée comme absente.
- 100 % des citations figurent mot pour mot dans le contrat (vérification par un script).
- Sur une note de revue de test, l'agent contradicteur relève les classements et les citations que le texte du contrat n'étaye pas.

## Pistes d'extension

- Comparer deux versions successives d'un même contrat et ne revoir que les clauses modifiées.
- Produire la note au format traitement de texte avec suggestions de modification.
- Mesurer l'écart de résultat entre deux modèles différents sur le même lot.
