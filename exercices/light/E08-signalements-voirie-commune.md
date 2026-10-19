# E08. Traitement des signalements de voirie d'une commune

Niveau : 2
Secteur : collectivité locale

## Contexte

La commune de Saint-Aubin-les-Prés (24 000 habitants) reçoit les signalements des habitants par courriel et par un formulaire du site : nid-de-poule, éclairage en panne, dépôt sauvage, arbre dangereux, tag. Environ 300 signalements arrivent par mois. L'agent d'accueil les recopie dans l'outil de tickets des services techniques en choisissant le service concerné (voirie, éclairage, propreté, espaces verts). Les adresses sont souvent imprécises (« en face de la boulangerie de la place »), les doublons fréquents, et l'habitant ne reçoit pas toujours d'accusé de réception.

## Flux actuel

1. Réception du signalement par courriel ou formulaire.
2. Saisie manuelle dans l'outil de tickets, choix du service.
3. Recherche de doublons de mémoire.
4. Accusé de réception envoyé de façon irrégulière.

## Objectif

Développer un agent qui lit les nouveaux signalements, détermine la catégorie et le service, normalise l'adresse, détecte les doublons, crée le ticket et prépare l'accusé de réception.

## Entrées

- Une boîte de test locale ou un dossier de fichiers .eml contenant 30 signalements fictifs, dont des doublons et des adresses imprécises.
- Un référentiel fictif des rues et des lieux-dits de la commune (CSV), avec quelques points de repère (place, école, boulangerie).
- Un outil de tickets local : base SQLite avec une petite API ou un serveur MCP local exposant « créer ticket », « chercher tickets ouverts », « ajouter commentaire ».

## Sorties attendues

- Un ticket par signalement nouveau : catégorie, service, adresse normalisée, description, lien vers le message d'origine.
- Pour un doublon : un commentaire ajouté au ticket existant, sans nouveau ticket.
- Un brouillon d'accusé de réception par signalement, avec le numéro de ticket.

## Outils nécessaires

- Langage et modèle au choix.
- Outils de l'agent : lecture de la boîte ou des fichiers, recherche dans le référentiel des rues, création et recherche de tickets, écriture des brouillons.

## Contraintes

- L'agent ne clôture ni ne supprime aucun ticket.
- Une adresse non retrouvée dans le référentiel donne lieu à un ticket marqué « adresse à préciser ».
- Les signalements relevant d'un danger immédiat (fil électrique au sol, arbre tombé sur la chaussée) sont marqués « urgent » et signalés à l'agent d'accueil, qui appelle lui-même le service d'astreinte.

## Critères de réussite

- Au moins 27 signalements sur 30 sont affectés au bon service.
- Les doublons sont tous détectés et rattachés au ticket existant.
- Les adresses imprécises dont le repère existe dans le référentiel sont correctement résolues.
- Les signalements de danger immédiat sont marqués « urgent ».

## Pistes d'extension

- Ajouter des coordonnées géographiques fictives et regrouper les signalements proches.
- Produire chaque lundi un tableau des tickets ouverts depuis plus de 15 jours par service.
- Tester la résistance de l'agent à un signalement contenant des instructions destinées au modèle.
