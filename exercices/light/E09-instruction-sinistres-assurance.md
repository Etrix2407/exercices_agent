# E09. Pré-instruction des déclarations de sinistre habitation

Niveau : 3
Secteur : assurance

## Contexte

La mutuelle Prévia Habitat assure 60 000 logements. Les déclarations de sinistre (dégât des eaux, bris de vitre, vol, incendie) arrivent par courriel ou formulaire, avec photos décrites, factures et parfois un constat amiable. Un gestionnaire ouvre le dossier, extrait les informations, vérifie que le contrat couvre le sinistre (garanties, franchise, plafonds, exclusions), demande les pièces manquantes, puis oriente le dossier : règlement simple, expertise ou refus. Le délai moyen avant le premier contact avec l'assuré est de 6 jours. Les gestionnaires indiquent que la vérification des garanties occupe une grande partie du temps et produit des erreurs quand les contrats ont des options.

## Flux actuel

1. Réception de la déclaration et des pièces.
2. Extraction manuelle des informations (date, nature, montant estimé, pièces fournies).
3. Lecture du contrat et des conditions générales pour vérifier la couverture.
4. Courrier à l'assuré : pièces à fournir, ou proposition, ou annonce d'expertise.

## Objectif

Concevoir un système de plusieurs agents qui coopèrent pour préparer le dossier à l'intention du gestionnaire :

- un agent d'extraction qui structure la déclaration ;
- un agent de couverture qui confronte la déclaration au contrat et aux conditions générales ;
- un agent de rédaction qui prépare le courrier à l'assuré ;
- un orchestrateur qui enchaîne les étapes, gère les cas incomplets et assemble la fiche finale.

## Entrées

- 8 déclarations fictives (texte), avec descriptions de pièces jointes.
- Des conditions générales fictives (5 à 8 pages en Markdown) et 8 conditions particulières de contrat (options, franchise, plafonds).
- Un barème de franchise fictif.

## Sorties attendues

- Une fiche de pré-instruction par dossier : informations extraites, garanties applicables avec référence de l'article, franchise, plafond, pièces manquantes, orientation proposée (règlement simple, expertise, refus probable) et justification.
- Un brouillon de courrier à l'assuré.
- Un journal des échanges entre agents.

## Outils nécessaires

- Langage et modèle au choix ; framework d'agents au choix (SDK d'agent avec sous-agents, orchestration écrite à la main, etc.).
- Outils : lecture des déclarations et des contrats, recherche dans les conditions générales, calcul de franchise en code, écriture des sorties.

## Contraintes

- Aucun agent ne décide d'un refus ou d'un paiement : l'orientation est une proposition au gestionnaire.
- Chaque affirmation sur la couverture cite l'article des conditions générales ou particulières.
- Chaque agent n'a accès qu'aux outils de son rôle (l'agent de rédaction ne lit pas les contrats, il reçoit la synthèse de l'agent de couverture).

## Critères de réussite

- Les orientations proposées sont justes, au regard des conditions générales et particulières, pour au moins 7 dossiers sur 8.
- Tout dossier relevant d'une exclusion est identifié avec l'article correspondant.
- Les franchises calculées sont exactes.
- Le journal permet de retracer quel agent a produit chaque élément de la fiche.

## Pistes d'extension

- Ajouter un agent relecteur chargé de contester la fiche avant transmission au gestionnaire.
- Comparer une architecture à agent unique et une architecture à plusieurs agents sur le même lot (qualité, coût en tokens, temps).
- Exécuter les agents en parallèle sur plusieurs dossiers.
