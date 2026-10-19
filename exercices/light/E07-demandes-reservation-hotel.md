# E07. Demandes de réservation de groupe dans un hôtel

Niveau : 2
Secteur : hôtellerie

## Contexte

L'hôtel Le Grand Cèdre dispose de 85 chambres et de trois salles de séminaire. Les réservations individuelles passent par une centrale en ligne, mais les demandes de groupe (mariages, séminaires, voyages organisés) arrivent par courriel, rédigées librement : dates parfois approximatives, nombre de personnes, types de chambres, besoin de salle, repas. Une seule personne au service commercial traite ces demandes. Elle vérifie les disponibilités dans le planning, calcule un devis selon la grille tarifaire, puis répond. Le délai de réponse atteint quatre jours en haute saison et une partie des demandes part chez un concurrent.

## Flux actuel

1. Lecture de la demande, relecture pour en extraire les besoins.
2. Consultation du planning des chambres et des salles.
3. Calcul du devis dans un tableur.
4. Rédaction d'une réponse avec proposition et conditions.

## Objectif

Développer un agent qui lit les demandes de groupe arrivées dans une boîte de test, extrait les besoins dans un format structuré, interroge les disponibilités, calcule un devis indicatif et prépare un brouillon de réponse avec le devis en pièce jointe.

## Entrées

- Une boîte de messagerie de test locale contenant 10 demandes fictives, dont 2 incomplètes (dates manquantes) et 1 incompatible avec les disponibilités.
- Un planning fictif des chambres et des salles (fichier iCalendar, CSV ou base SQLite) sur trois mois.
- Une grille tarifaire fictive (chambre par type et par saison, salle à la journée, forfaits repas).

## Sorties attendues

- Pour chaque demande : une fiche structurée (JSON) des besoins extraits.
- Un devis indicatif (Markdown ou PDF) calculé à partir de la grille.
- Un brouillon de réponse : proposition, ou demande de précisions, ou proposition de dates alternatives.

## Outils nécessaires

- Langage et modèle au choix.
- Outils de l'agent : lecture de la boîte de test, consultation du planning, fonction de calcul du devis écrite en code, écriture de brouillons. Exposition possible via un serveur MCP local.

## Contraintes

- L'agent ne bloque aucune chambre ni aucune salle dans le planning ; il lit uniquement.
- Les prix proviennent exclusivement de la grille ; aucune remise n'est proposée.
- Le service commercial relit chaque brouillon et décide de l'envoi.

## Critères de réussite

- Les besoins extraits des 10 demandes sont exacts (dates, effectifs, types de chambres, salle, repas).
- Les deux demandes incomplètes produisent une demande de précisions et aucun devis.
- La demande incompatible reçoit une proposition de dates alternatives réellement disponibles dans le planning.
- Les montants des devis sont identiques à un calcul manuel de contrôle.

## Pistes d'extension

- Ajouter une option de pré-réservation soumise à validation explicite dans le terminal.
- Relancer automatiquement en brouillon les demandes sans réponse du client après 7 jours.
- Passer au niveau 3 avec un agent dédié au devis et un agent dédié à la rédaction.
