# E12. Traitement nocturne des demandes de rendez-vous de consultation

Niveau : 4
Secteur : administration hospitalière

## Contexte

Le centre hospitalier du Val-de-Lierre propose 22 spécialités en consultation externe. Les demandes de rendez-vous arrivent par le site, par courriel des médecins traitants et par courrier numérisé : environ 900 par semaine. Le secrétariat central les trie le matin, vérifie la présence du courrier d'adressage quand la spécialité l'exige, détermine le délai souhaitable selon le motif et propose un créneau. Les demandes de la veille ne sont souvent traitées qu'en fin de matinée, et le tri occupe trois secrétaires pendant deux heures. Le centre souhaite qu'un traitement préparatoire s'exécute la nuit, hors des postes de travail, et que le secrétariat trouve le matin un lot de propositions prêtes à valider.

## Flux actuel

1. Collecte des demandes des différents canaux dans un dossier commun.
2. Tri par spécialité, contrôle des pièces requises.
3. Évaluation du délai souhaitable selon le motif, avec un référentiel interne par spécialité.
4. Recherche d'un créneau et proposition au patient.

## Objectif

Déployer un agent hébergé (Managed Agents) qui, déclenché chaque nuit depuis un script local, reçoit le lot de demandes de la journée, les traite dans son environnement d'exécution et restitue un fichier de propositions. Le poste local ne sert qu'à déclencher la session, envoyer les fichiers et récupérer les résultats.

## Entrées

- Un lot fictif de 40 demandes (texte), avec spécialité demandée ou à déduire, motif, présence ou absence de courrier d'adressage. Les données patient sont entièrement inventées.
- Un référentiel fictif par spécialité : pièces requises, délai cible selon le niveau de priorité.
- Un planning fictif de créneaux disponibles par spécialité sur quatre semaines (CSV).

## Sorties attendues

- Un fichier de propositions (CSV ou JSON) : identifiant de demande, spécialité, priorité proposée avec justification, pièces manquantes, créneau proposé ou motif d'absence de créneau.
- Un rapport de session : nombre de demandes traitées, nombre de propositions, nombre de demandes à revoir, durée et consommation de tokens de la session.

## Outils nécessaires

- Accès à l'API Claude avec une clé de développement et à la fonction Managed Agents.
- Script local (langage au choix) qui crée ou réutilise la définition de l'agent, ouvre une session, transmet les fichiers, suit l'avancement et récupère les sorties.
- Outils de l'agent dans son environnement : exécution de code pour lire les fichiers et calculer les créneaux, écriture du fichier de sortie.

## Contraintes

- L'agent propose ; il ne confirme aucun rendez-vous et n'écrit dans aucun planning réel.
- Toute demande dont la priorité est incertaine est marquée « à revoir par le secrétariat ».
- Le script local s'arrête proprement si la session dépasse une durée ou un budget de tokens fixé à l'avance.

## Critères de réussite

- Le déclenchement de bout en bout tient en une commande et ne demande aucune intervention.
- Les 40 demandes figurent dans le fichier de sortie, sans doublon ni perte.
- Les demandes sans courrier d'adressage requis sont toutes signalées.
- Aucun créneau n'est proposé deux fois.
- Le rapport de session indique la consommation réelle relevée par l'API.

## Pistes d'extension

- Planifier le déclenchement avec le planificateur de tâches du système.
- Conserver l'état entre deux nuits pour reprendre les demandes restées « à revoir ».
- Comparer coût et durée entre l'exécution hébergée et une exécution locale du même agent avec le SDK.
