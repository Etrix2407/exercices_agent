# Serveur MCP exemple : base SQLite

Serveur MCP en Python qui donne à un agent un accès en lecture seule à `../sqlite/entreprise.db`. Écrit avec le SDK Python officiel `mcp` 2.x (classe `MCPServer`, nouveau nom de `FastMCP`), transport stdio, protocole 2026-07-28.

## Ce que le serveur expose

| Type | Nom | Rôle |
|---|---|---|
| outil | `rechercher_clients(texte)` | clients par fragment de nom, ville, contact ou code |
| outil | `commandes_client(code_client)` | commandes d'un client et statut de facture |
| outil | `detail_commande(numero)` | en-tête, lignes et facture d'une commande |
| outil | `factures_impayees(code_client?, en_retard_seulement?)` | factures non payées |
| outil | `stocks_sous_seuil()` | produits sous le seuil d'alerte |
| outil | `tickets(statut?, code_client?)` | tickets support filtrés |
| outil | `requete_sql(sql)` | une instruction SELECT libre, 200 lignes au plus |
| ressource | `schema://entreprise` | schéma SQL complet |
| prompt | `relance_factures(code_client)` | consigne de préparation d'une relance |

Les outils de liste renvoient `{"nombre": n, "<éléments>": [...]}` : une liste vide reste visible pour le modèle. Les jokers SQL `%` et `_` saisis dans `rechercher_clients` sont pris littéralement. Tous les outils portent l'annotation `readOnlyHint`. La base est ouverte en `mode=ro` : même une requête `requete_sql` mal filtrée ne peut pas écrire.

## Installation

Depuis le dossier `avance\` :

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
py -3.12 sqlite\creer_base.py
```

## Lancer et tester

```powershell
cd serveur-mcp-exemple
..\.venv\Scripts\python client_test.py
```

`client_test.py` démarre `serveur.py` en sous-processus (stdio), liste outils, ressource et prompt, appelle chaque outil et vérifie qu'une requête `DELETE` est refusée. Sortie attendue en dernière ligne : `OK : serveur MCP fonctionnel`.

Lancement seul (le serveur attend des messages JSON-RPC sur l'entrée standard, rien ne s'affiche) :

```powershell
..\.venv\Scripts\python serveur.py
```

Autre base : variable d'environnement `ENTREPRISE_DB`.

## MCP Inspector

Interface web de test fournie par le projet MCP (Node.js requis) :

```powershell
npx @modelcontextprotocol/inspector "C:\chemin\vers\avance\.venv\Scripts\python.exe" "C:\chemin\vers\avance\serveur-mcp-exemple\serveur.py"
```

Dans le navigateur ouvert : « Connect », puis onglets Tools (appeler `stocks_sous_seuil`), Resources (`schema://entreprise`) et Prompts (`relance_factures`).

## Claude Desktop

Copier le bloc de `claude_desktop_config.exemple.json` dans `%APPDATA%\Claude\claude_desktop_config.json` (menu Paramètres, Développeur, Modifier la configuration), remplacer les chemins par des chemins absolus, puis redémarrer Claude Desktop. Le serveur apparaît sous le nom `entreprise-sqlite` dans la liste des connecteurs.

Les barres obliques inverses sont doublées dans le JSON (`C:\\dev\\...`).

## Pistes d'extension

- Ajouter un outil d'écriture (création de ticket) avec `destructive_hint` et une confirmation côté client.
- Exposer chaque table comme ressource paramétrée (`table://{nom}`).
- Brancher la fausse boîte mail comme second serveur MCP et faire coopérer les deux.
- Passer en transport HTTP (`serveur.run("streamable-http")`) pour un client distant.
