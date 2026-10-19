# Exercices pratiques : agents IA

Énoncés d'exercices portant sur des flux métiers fictifs. Chaque énoncé est réalisable sur un poste local avec des données inventées, sans dépendre d'un environnement d'entreprise ni d'un administrateur.

## Consignes générales

- Choisir librement le langage de programmation et le modèle (API, SDK d'agent, modèle local).
- Créer les données fictives décrites dans la section « Entrées » de l'énoncé ; aucune donnée réelle n'est utilisée.
- Lire l'énoncé en entier, remplir la fiche de cadrage (`fiche-cadrage-agent.docx` ou `.pdf`), la faire valider par le formateur, puis développer.
- Vérifier chaque critère de réussite avant de passer aux pistes d'extension.
- Un cas personnel peut remplacer un énoncé : le décrire selon la même structure (contexte, flux actuel, objectif, entrées, sorties, outils, contraintes, critères de réussite) et indiquer son niveau.

## Échelle des niveaux

| Niveau | Description |
|---|---|
| 0 | Conversation pré-promptée avec routine : instructions système, fichiers de référence, exécution récurrente. |
| 1 | Agent local simple : boucle d'agent sur le poste, outils limités aux fichiers locaux et à du code. |
| 2 | Agent local avec outils externes : messagerie, API, base de données, serveur MCP. |
| 3 | Plusieurs agents qui coopèrent : orchestrateur, sous-agents spécialisés, rôles et outils séparés. |
| 4 | Agent hébergé (Managed Agents) : exécution dans un environnement distant, déclenchée et suivie depuis le poste local. |

## Récapitulatif

| Code | Titre | Secteur | Niveau | Outils |
|---|---|---|---|---|
| [E01](light/E01-questions-clients-cabinet-comptable.md) | Réponses aux questions récurrentes | Cabinet comptable | 0 | Assistant avec instructions système, fichiers de référence, routine |
| [E02](light/E02-conseils-de-classe.md) | Préparation des conseils de classe | Enseignement secondaire | 0 | Assistant avec instructions système, export CSV, routine |
| [E03](light/E03-ecarts-livraison-entrepot.md) | Rapprochement des bons de livraison | Logistique | 1 | Lecture de fichiers texte et CSV, écriture de fiches |
| [E04](light/E04-dossiers-candidature-location.md) | Complétude des dossiers de candidature | Immobilier | 1 | Parcours de dossiers, grille YAML ou JSON, brouillons |
| [E05](light/E05-analyse-pannes-maintenance.md) | Analyse des pannes récurrentes | Industrie, maintenance | 1 | Lecture CSV, outil de calcul en code, note Markdown |
| [E06](light/E06-service-client-boutique-en-ligne.md) | Tri et brouillons du service client | Commerce en ligne | 2 | Messagerie de test (IMAP), base de commandes, API locale, MCP |
| [E07](light/E07-demandes-reservation-hotel.md) | Demandes de réservation de groupe | Hôtellerie | 2 | Messagerie de test, planning (iCalendar, CSV ou SQLite), calcul de devis |
| [E08](light/E08-signalements-voirie-commune.md) | Signalements de voirie | Collectivité locale | 2 | Messagerie ou fichiers .eml, référentiel des rues, outil de tickets local |
| [E09](light/E09-instruction-sinistres-assurance.md) | Pré-instruction des sinistres habitation | Assurance | 3 | Orchestrateur et trois agents, recherche documentaire, calcul en code |
| [E10](light/E10-arrivee-nouveaux-collaborateurs.md) | Arrivée des nouveaux collaborateurs | Ressources humaines | 3 | Orchestrateur et trois agents, fichier d'état, messagerie de test |
| [E11](light/E11-revue-contrats-fournisseurs.md) | Revue des contrats fournisseurs | Juridique | 3 | Quatre agents dont un contradicteur, vérification des citations |
| [E12](light/E12-demandes-rendez-vous-consultations.md) | Traitement nocturne des demandes de rendez-vous | Administration hospitalière | 4 | API Claude, Managed Agents, script local de déclenchement |
| [G01](light/G01-location-materiel-chantier.md) | Bréval Location : identifier et prioriser les agents | Location de matériel de chantier | 0 à 4 | Analyse, puis outils selon l'opportunité retenue |
| [N01](n8n/N01-assistant-demandes-n8n.md) | Piste n8n : assistant des demandes du service client | Commerce en ligne (données E06) | 1 à 3 | n8n (nœud AI Agent), MCP Client Tool, MCP Server Trigger |

## Piste n8n

Variante low-code : l'agent est un nœud « AI Agent » placé dans un workflow visuel n8n, ce qui montre la frontière entre étapes fixes et décisions de l'agent. Trois variantes de difficulté croissante (outils natifs, serveur MCP externe, workflow exposé comme serveur MCP) sur les données du kit E06. Installation locale avec Node.js (`npx n8n`), sans Docker. Voir [n8n/README.md](n8n/README.md) et l'énoncé [N01](n8n/N01-assistant-demandes-n8n.md).

## Paliers de matériel

| Palier | Contenu | Emplacement |
|---|---|---|
| Light | Énoncé seul ; les données fictives sont à créer. | `light/` |
| Middle | Un dossier par énoncé (E01 à E12, G01) avec les documents prêts à l'emploi : fichiers CSV, JSON et YAML, courriels `.eml`, dossiers de pièces en texte, référentiels et barèmes en Markdown. | `middle/` |
| Avancé | Outils locaux communs à tous les niveaux, autour d'un univers fictif unique (distributeur de fournitures de bureau) : base SQLite générée par graine, boîte de 30 courriels `.eml` avec module de lecture et d'envoi, serveur MCP stdio en lecture seule avec client de test, guide de connexion à un compte Gmail de test. Kits par énoncé (E06 à E12, G01) avec serveurs MCP propres à l'énoncé. | `avance/` |
