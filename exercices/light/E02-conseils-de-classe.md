# E02. Préparation des conseils de classe

Niveau : 0
Secteur : enseignement secondaire

## Contexte

Le lycée Jean-Rostand compte 32 classes. Avant chaque conseil de classe, le professeur principal rassemble les appréciations de huit à douze collègues pour chacun des 28 élèves, puis rédige une appréciation générale par élève et une synthèse de la classe. Les appréciations sont saisies dans un logiciel de vie scolaire et exportées en tableur. La rédaction prend trois à quatre heures par classe et par trimestre. Les appréciations générales se répètent d'un élève à l'autre et certains signaux (baisse dans plusieurs matières, absences) sont repérés tard.

## Flux actuel

1. Export du tableur des appréciations et des moyennes par matière.
2. Lecture élève par élève, prise de notes.
3. Rédaction de l'appréciation générale de chaque élève.
4. Rédaction d'une synthèse de classe pour l'ouverture du conseil.

## Objectif

Mettre en place une conversation pré-promptée qui, à partir de l'export d'une classe, produit des propositions d'appréciations générales et une synthèse de classe, et une routine qui rejoue le même gabarit à chaque fin de trimestre.

## Entrées

- Un export fictif au format CSV : 28 élèves, 9 matières, moyenne, appréciation par matière, nombre de demi-journées d'absence. Inclure des cas typés : élève en forte progression, élève en baisse généralisée, élève avec absences nombreuses, élève sans difficulté.
- Une charte de rédaction fictive de l'établissement (ton, longueur maximale, formulations à éviter).

## Sorties attendues

- Une proposition d'appréciation générale par élève (300 caractères au plus), conforme à la charte.
- Une liste d'élèves à signaler au conseil, avec le motif factuel (baisse, absences).
- Une synthèse de classe de 10 lignes au plus.

## Outils nécessaires

- Assistant conversationnel avec instructions système et fichiers joints.
- Routine ou tâche planifiée, ou procédure documentée pour relancer la même conversation sur un nouvel export.

## Contraintes

- Ne pas ajouter de faits absents des appréciations des collègues.
- Ne formuler aucun jugement sur la personnalité ou la situation familiale.
- Le professeur principal valide et modifie chaque appréciation avant saisie.

## Critères de réussite

- Toutes les appréciations respectent la longueur et la charte.
- Chaque élève en baisse généralisée ou avec absences nombreuses figure dans la liste de signalement.
- Aucune appréciation ne contient d'information absente de l'export (contrôle sur 5 élèves tirés au hasard).
- Le même prompt appliqué à une deuxième classe fictive produit un résultat de structure identique.

## Pistes d'extension

- Ajouter l'historique du trimestre précédent pour qualifier l'évolution.
- Produire une version courte pour le bulletin et une version détaillée pour le conseil.
- Passer au niveau 1 avec un script qui traite toutes les classes d'un dossier.
