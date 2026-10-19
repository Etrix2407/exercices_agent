# E10. Préparation de l'arrivée des nouveaux collaborateurs

Niveau : 3
Secteur : ressources humaines

## Contexte

Le groupe Vandamme Ingénierie (650 personnes, cinq sites) recrute environ 15 personnes par mois. Chaque arrivée mobilise plusieurs services : les RH (contrat, dossier administratif, visite médicale), l'informatique (poste, comptes, accès aux applications selon le métier), les services généraux (badge, bureau, place de parking) et le manager (planning de la première semaine, parrain). La coordination passe par des courriels et un tableur partagé. Une arrivée sur trois présente un manque le premier jour : poste non prêt, badge absent, accès manquants. Les nouveaux arrivants reçoivent des informations dispersées et parfois contradictoires.

## Flux actuel

1. Les RH saisissent l'arrivée dans le tableur après signature du contrat.
2. Envoi de courriels séparés à chaque service.
3. Relances manuelles à l'approche de la date d'arrivée.
4. Le manager prépare le planning de la première semaine de son côté.

## Objectif

Concevoir un système de plusieurs agents qui, à partir d'une fiche d'arrivée, coordonne la préparation :

- un agent RH qui vérifie la complétude du dossier administratif et planifie la visite médicale ;
- un agent informatique qui déduit du métier la liste des comptes et accès à demander, selon un référentiel ;
- un agent logistique qui prépare les demandes de badge, de bureau et de matériel ;
- un orchestrateur qui suit l'avancement, relance les tâches en retard et produit le livret d'accueil personnalisé.

## Entrées

- 6 fiches d'arrivée fictives (nom, poste, site, date, manager, type de contrat).
- Un référentiel fictif métier vers accès (applications, groupes, matériel).
- Une liste fictive des bureaux et places disponibles par site.
- Un fichier d'état des tâches (JSON ou SQLite) simulant les réponses des services, modifiable à la main pour simuler les retards.

## Sorties attendues

- Pour chaque arrivée : la liste des demandes générées par service, avec échéance.
- Un tableau d'avancement mis à jour à chaque exécution, avec les tâches en retard et les relances proposées.
- Un livret d'accueil personnalisé (Markdown) : programme de la première semaine, contacts, informations pratiques du site.

## Outils nécessaires

- Langage et modèle au choix ; orchestration au choix.
- Outils : lecture des fiches et référentiels, lecture et mise à jour du fichier d'état, écriture des demandes et du livret ; envoi de courriels possible vers un serveur de messagerie de test local.

## Contraintes

- Les demandes d'accès sont déduites uniquement du référentiel ; tout accès hors référentiel est soumis au manager.
- Aucun agent ne modifie le contrat ni les données de rémunération, qui ne figurent d'ailleurs pas dans les entrées.
- Les relances destinées aux services restent à l'état de brouillon jusqu'à validation par les RH.

## Critères de réussite

- Pour les 6 arrivées, les demandes d'accès correspondent exactement au référentiel.
- Une tâche passée en retard dans le fichier d'état déclenche une relance à l'exécution suivante.
- Le livret d'accueil ne contient que des informations présentes dans les entrées.
- L'ajout d'un nouveau métier dans le référentiel ne demande aucune modification du code.

## Pistes d'extension

- Exécuter l'orchestrateur chaque matin par une tâche planifiée locale.
- Ajouter un agent qui répond aux questions du nouvel arrivant à partir du livret et du règlement intérieur fictif.
- Gérer les départs avec le flux inverse (restitution du matériel, fermeture des accès).
