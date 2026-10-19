# E12. Traitement nocturne des demandes de rendez-vous : kit avancé

Agent hébergé Managed Agents (bêta), déclenché depuis le poste local. Le conteneur de la session lit le lot et le référentiel montés en fichiers ; les créneaux et les propositions restent dans une base SQLite locale, atteinte par des outils personnalisés que le script local exécute et dont il renvoie le résultat. Données entièrement fictives.

## Contenu

| Fichier | Rôle |
|---|---|
| `donnees/` | lot de 40 demandes, référentiel des 22 spécialités, 122 créneaux (copie du jeu de données de l'énoncé) |
| `init_donnees.py` | crée `planning.db` : tables `demandes`, `specialites`, `creneaux` en lecture seule (déclencheurs), table `propositions` limitée au statut « brouillon », un créneau par proposition au plus |
| `outils_planning.py` | fonctions de lecture et d'écriture de brouillons, définitions des outils personnalisés (`OUTILS_SESSION`), aiguillage `executer_outil` |
| `serveur_mcp.py` | serveur MCP local (stdio) sur la même base : 6 outils de lecture, 2 outils de brouillon, aucun outil de confirmation |
| `lancer_session.py` | création ou réutilisation de l'agent et de l'environnement, téléversement du lot, session avec plafond de dépense, suivi du flux d'événements, relais des outils personnalisés, arrêt sur durée ou tokens, récupération des sorties, rapport |
| `planification/` | déclenchement nocturne : `lancer_nuit.cmd` et `planifier_windows.ps1` (planificateur de tâches, sans droits d'administrateur), `lancer_nuit.sh` et `crontab.exemple` |
| `test_kit.py` | vérification complète sans appel à l'API |

## Installation et vérification

Depuis ce dossier, avec l'environnement Python du palier avancé :

```powershell
..\.venv\Scripts\python -m pip install anthropic
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Ligne attendue : `OK : kit E12 fonctionnel (aucun appel à l'API)`.

## Simulation

```powershell
..\.venv\Scripts\python lancer_session.py
```

Le mode `--simulation` est le mode par défaut : aucun appel réseau. Un client simulé reproduit les appels du SDK et rejoue une suite d'événements fictifs (messages, requêtes au modèle, demande d'autorisation, appels d'outils personnalisés). La boucle de suivi est celle du mode réel ; les outils appelés s'exécutent sur une copie neuve de la base. Le rejeu ne traite que deux demandes : il montre la mécanique, pas la solution. `--tokens-max 10000` montre l'interruption sur limite.

Sorties dans `sorties/<horodatage>/` : `propositions.csv` (fichier récupéré de la session), `propositions_base_locale.csv` (export des brouillons, une ligne par demande), `rapport_session.json`, `evenements.jsonl`.

## Mode réel

```powershell
$env:ANTHROPIC_API_KEY = "..."   # clé de développement, ou profil « ant auth login »
..\.venv\Scripts\python lancer_session.py --reel --duree-max 1800 --tokens-max 3000000 --budget-centimes 500
```

Consommation facturée. Le premier lancement crée l'agent et l'environnement et note leurs identifiants dans `etat_agent.json` ; les lancements suivants les réutilisent, et une modification de la consigne ou des outils produit une nouvelle version du même agent. Les brouillons s'accumulent dans `planning.db` : relancer `init_donnees.py` pour repartir du lot initial.

## Points techniques

- Agent, environnement, session : l'agent porte le modèle, la consigne et les outils ; l'environnement est un conteneur sans réseau sortant ; la session épingle une version de l'agent.
- Flux ouvert avant l'envoi de la consigne, pour ne perdre aucun événement.
- Arrêt sur `session.status_idle` seulement si la raison n'est pas `requires_action` (attente d'un résultat d'outil).
- Outils personnalisés : `agent.custom_tool_use` reçu, exécution locale, `user.custom_tool_result` renvoyé avec `is_error` en cas de refus.
- Outils de liste du serveur MCP : résultat `{"nombre": n, "<éléments>": [...]}`, une liste vide reste visible pour le modèle.
- Saisies contrôlées : `lister_creneaux_libres` refuse une spécialité absente du référentiel (noms exacts rappelés) et une date hors format AAAA-MM-JJ ; une liste vide signifie donc qu'aucun créneau n'est libre. Côté MCP, la priorité est typée (valeurs admises dans le schéma).
- Permissions : politique `auto` sur les outils du conteneur ; toute demande d'autorisation reçoit `deny`, personne ne surveillant l'exécution.
- Trois limites : plafond de dépense de la session (appliqué par la plateforme), durée et tokens (appliqués par le script avec `user.interrupt`, puis fermeture du flux après un délai de grâce).
- Consommation : tokens comptés sur `span.model_request_end` pendant la session, valeurs de référence lues ensuite dans `session.usage`.
- Serveur MCP distant : une session hébergée n'atteint pas un serveur local. Pour lui confier `serveur_mcp.py`, le servir en HTTP sur une adresse publique en HTTPS et le déclarer dans `mcp_servers` de l'agent ; le relais par outils personnalisés évite cette exposition.

## Non couvert par les tests

Le mode réel n'est pas exécuté par `test_kit.py`. Les noms de paramètres et les champs des événements envoyés sont confrontés aux signatures et aux types du SDK `anthropic` installé, sans requête. La reprise du flux après une coupure réseau n'est pas traitée.
