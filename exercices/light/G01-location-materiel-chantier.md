# G01. Bréval Location : identifier et prioriser les agents d'une entreprise multiservice

Type : grand énoncé d'analyse, niveaux 0 à 4
Secteur : location et maintenance de matériel de chantier

## Consigne

Lire la description de l'organisation. Identifier les opportunités d'agents, les décrire, les classer par niveau et les prioriser. Choisir ensuite une ou deux opportunités et les réaliser avec des données fictives. Aucune solution n'est donnée : plusieurs analyses sont recevables si elles sont argumentées.

## 1. Présentation de l'organisation

Bréval Location loue du matériel de chantier et d'événementiel aux entreprises du bâtiment, aux collectivités et aux particuliers : mini-pelles, nacelles, échafaudages, groupes électrogènes, bungalows, petit outillage. L'entreprise emploie 310 personnes, réalise 48 millions d'euros de chiffre d'affaires et exploite 14 agences régionales, un atelier central de maintenance et une plateforme logistique. Le parc compte environ 9 000 machines et 30 000 articles de petit outillage.

Le système d'information repose sur un progiciel de gestion locative ancien (contrats, parc, facturation), un outil de gestion de la maintenance, une messagerie, un site web vitrine avec formulaire de devis, et de nombreux tableurs partagés. Le progiciel dispose d'exports CSV programmables et d'une API en lecture seule ; l'écriture se fait uniquement par l'interface.

## 2. Services et flux

### 2.1 Agences (110 personnes)

Chaque agence reçoit les demandes de location par téléphone (60 %), courriel (25 %) et formulaire web (15 %). Le chargé de location vérifie la disponibilité de la machine dans le progiciel, éventuellement dans les agences voisines, établit un devis, puis un contrat. Il organise la livraison avec la plateforme logistique.

Irritants relevés :

- Les demandes par courriel et formulaire sont traitées après les appels ; le délai moyen de réponse à un devis écrit est de 26 heures. Un tiers des devis web ne reçoit aucune relance.
- La disponibilité affichée dans le progiciel est fausse dans environ 10 % des cas : machine rentrée mais pas encore contrôlée, machine en panne non déclarée.
- Les clients demandent souvent « une machine pour faire tel travail » sans connaître la référence ; seuls les chargés expérimentés savent conseiller.

### 2.2 Plateforme logistique (45 personnes)

La plateforme planifie chaque jour 180 à 250 livraisons et reprises avec 22 camions. Le planificateur construit les tournées à la main dans un tableur à partir des demandes envoyées par les agences par courriel, la veille avant 16 h.

Irritants relevés :

- Les demandes arrivent dans des formats variables, parfois incomplètes (adresse de chantier imprécise, contact absent, contrainte d'accès non précisée).
- Les changements de dernière minute sont nombreux et passent par téléphone.
- Les chauffeurs remplissent un bon de livraison papier ; les réserves du client (machine sale, accessoire manquant) sont ressaisies au bureau avec deux à cinq jours de retard.

### 2.3 Atelier central et maintenance (70 personnes)

L'atelier contrôle chaque machine au retour de location, réalise l'entretien préventif et les réparations. Les contrôles réglementaires périodiques (nacelles, appareils de levage) sont obligatoires et tracés.

Irritants relevés :

- Le compte rendu de retour est saisi en texte libre ; les dommages imputables au client ne sont pas toujours documentés à temps pour être facturés. Environ 180 000 euros de réparations par an ne sont pas refacturés faute de preuve.
- Les échéances de contrôle réglementaire sont suivies dans un tableur séparé ; deux machines ont été louées l'an dernier avec un contrôle échu.
- Les techniciens cherchent les procédures et vues éclatées dans des PDF constructeur dispersés sur un serveur de fichiers (environ 4 000 documents).

### 2.4 Facturation et recouvrement (18 personnes)

La facturation est mensuelle pour les locations longues et à la restitution pour les courtes. Les litiges portent sur les durées facturées, le carburant, le nettoyage et les dommages.

Irritants relevés :

- 7 % des factures font l'objet d'une contestation, traitée par courriel ; chaque litige demande de rassembler contrat, bon de livraison, bon de retour et compte rendu d'atelier.
- Le délai moyen de paiement est de 67 jours ; les relances suivent un calendrier fixe sans tenir compte de l'historique du client.

### 2.5 Achats et gestion du parc (12 personnes)

Le service décide des achats et des cessions de machines. Il s'appuie sur un rapport trimestriel du taux d'utilisation, produit à la main en deux semaines à partir des exports du progiciel.

Irritants relevés :

- Le rapport arrive trop tard pour les décisions de saison.
- Les demandes de machines non disponibles (refus de location) ne sont pas enregistrées ; la demande non servie est inconnue.

### 2.6 Ressources humaines, qualité et sécurité (15 personnes)

Le service gère notamment les habilitations des chauffeurs et techniciens (permis, autorisations de conduite d'engins), les accidents et presque-accidents, et l'accueil des intérimaires, nombreux en saison.

Irritants relevés :

- Les habilitations expirées sont découvertes au moment du contrôle.
- Les fiches de presque-accident sont rares et rarement analysées.
- L'accueil sécurité des intérimaires se fait oralement, avec des contenus variables d'une agence à l'autre.

### 2.7 Direction

La direction souhaite « utiliser des agents IA » sans avoir défini de priorités. Elle impose trois conditions : aucune modification des données du progiciel sans validation humaine, un premier résultat mesurable en trois mois, un budget limité pour la première année.

## 3. Données disponibles pour l'exercice

Toutes les données sont à créer de façon fictive selon les besoins de l'opportunité choisie : extraits de catalogue, contrats, bons de livraison, comptes rendus d'atelier, échéancier de contrôles, courriels de clients, factures et litiges. Un serveur de messagerie de test local et une base SQLite suffisent à simuler les systèmes.

## 4. Questions d'analyse

### Repérage

1. Lister les tâches répétitives de chaque service. Lesquelles reposent sur la lecture de texte libre, de documents ou de courriels ?
2. Pour chaque irritant, déterminer s'il relève d'un agent, d'une automatisation classique sans modèle de langage, d'un changement d'organisation ou d'un correctif du progiciel.
3. Quelles opportunités traversent plusieurs services ? Quels flux se répètent d'un service à l'autre ?

### Description d'une opportunité

4. Quel est le déclencheur (message reçu, heure fixe, action d'un utilisateur) ?
5. Quelles sont les entrées, les sorties, et à qui sont-elles destinées ?
6. De quels outils l'agent a-t-il besoin ? En lecture ou en écriture ?
7. À quel niveau (0 à 4) correspond la solution la plus simple qui fonctionne ? Un niveau supérieur apporte-t-il quelque chose de mesurable ?
8. Où placer la validation humaine ? Quelles actions l'agent ne doit-il jamais faire seul ?

### Risques et limites

9. Quelles erreurs de l'agent seraient sans conséquence, lesquelles seraient coûteuses ?
10. Quelles entrées proviennent de l'extérieur (clients, fournisseurs) et pourraient contenir des instructions malveillantes destinées au modèle ? Quelles permissions limiter en conséquence ?
11. Quelles données l'agent doit-il voir, et lesquelles lui sont inutiles ?

### Priorisation

12. Estimer pour chaque opportunité le gain (temps, argent, qualité de service) à partir des chiffres de l'énoncé.
13. Estimer l'effort de réalisation et la dépendance aux systèmes existants (API en lecture seule, exports).
14. Quelles opportunités respectent les trois conditions de la direction ?
15. Classer les opportunités sur une matrice gain et effort et proposer un ordre de réalisation.

### Mesure

16. Quels indicateurs permettent de vérifier, après trois mois, que l'agent a atteint son objectif ?
17. Comment comparer avec la situation actuelle (mesure avant et après, échantillon de contrôle) ?

## 5. Livrables attendus

- Une cartographie des opportunités : service, irritant, description de l'agent, niveau, outils, validation humaine.
- Une matrice de priorisation argumentée.
- Une fiche de cadrage détaillée pour l'opportunité retenue (entrées, sorties, outils, contraintes, critères de réussite).
- Un prototype fonctionnel sur données fictives pour une ou deux opportunités.
