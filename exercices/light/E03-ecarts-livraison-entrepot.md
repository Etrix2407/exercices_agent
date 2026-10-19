# E03. Rapprochement des bons de livraison en entrepôt

Niveau : 1
Secteur : logistique

## Contexte

La société Transeuro Stock exploite un entrepôt de 12 000 m² pour le compte de quatre distributeurs. Chaque jour, 30 à 50 camions livrent des marchandises. Le cariste qui réceptionne note les quantités reçues sur le bon de livraison papier, ensuite scanné et converti en texte. Le service administratif compare ces bons aux commandes d'achat transmises par les distributeurs. Les écarts (quantité manquante, référence erronée, colis abîmé) doivent être signalés sous 48 heures, faute de quoi le litige n'est plus recevable. Ce délai est dépassé pour environ 15 % des écarts.

## Flux actuel

1. Réception, saisie manuscrite des quantités sur le bon.
2. Numérisation, fichier texte déposé dans un dossier partagé.
3. Comparaison manuelle avec la commande d'achat (fichier CSV par distributeur).
4. Rédaction d'une fiche d'écart si nécessaire.

## Objectif

Développer un agent local qui lit les bons de livraison du jour, les rapproche des commandes et produit une fiche d'écart par livraison non conforme, ainsi qu'un récapitulatif journalier.

## Entrées

- Un dossier de 15 bons de livraison fictifs en texte, avec des formats différents selon le transporteur, des fautes de frappe et une mention manuscrite retranscrite (« 2 cartons abîmés »).
- Un fichier CSV de commandes d'achat (numéro de commande, référence, désignation, quantité commandée, distributeur).

## Sorties attendues

- Une fiche d'écart en Markdown ou JSON par livraison non conforme : numéro de commande, référence, quantité attendue, quantité reçue, nature de l'écart, date limite de signalement.
- Un récapitulatif journalier : nombre de livraisons, nombre de livraisons conformes, liste des écarts triés par date limite.

## Outils nécessaires

- Langage au choix ; modèle au choix (API, SDK d'agent ou modèle local).
- Outils exposés à l'agent : lecture des fichiers du dossier, lecture du CSV, écriture des fiches dans un dossier de sortie.

## Contraintes

- L'agent écrit uniquement dans le dossier de sortie ; il ne modifie ni les bons ni les commandes.
- Un bon illisible ou ambigu donne lieu à une fiche « à vérifier », sans supposition.
- Les fiches sont relues par un agent administratif avant envoi.

## Critères de réussite

- Tous les écarts entre bons de livraison et commandes sont détectés.
- Aucun faux écart sur les livraisons conformes.
- Chaque fiche contient une date limite exacte (réception + 48 heures).
- Le traitement complet se relance d'une seule commande.

## Pistes d'extension

- Confier la comparaison des quantités à du code déterministe et réserver le modèle à l'extraction du texte libre.
- Gérer les livraisons partielles d'une même commande sur plusieurs jours.
- Passer au niveau 2 en envoyant les fiches validées par courriel vers un serveur de messagerie de test local.
