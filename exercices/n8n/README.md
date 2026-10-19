# Piste n8n : un agent dans un workflow visuel

n8n est un outil d'automatisation par workflows visuels : des nœuds reliés entre eux, chacun exécutant une étape (déclencheur, lecture de fichier, requête HTTP, transformation, écriture). Le nœud « AI Agent » place un modèle de langage et ses outils à un endroit précis du workflow.

Cette piste rend visible la différence entre workflow et agent :

- les étapes du workflow sont fixées à l'avance, dans l'ordre du dessin ;
- le nœud AI Agent décide lui-même, à l'exécution, quels outils appeler, dans quel ordre et combien de fois ;
- le reste du workflow encadre l'agent : ce qui entre (déclencheur, données préparées) et ce qui sort (fichier, brouillon) ne dépend pas du modèle.

C'est aussi une voie *low-code* : la boucle d'agent, l'appel au modèle et la déclaration des outils sont fournis par n8n. Le code se limite à de petits nœuds de transformation, ou au serveur MCP de la variante B.

Énoncé associé : [N01. Assistant des demandes du service client (n8n)](N01-assistant-demandes-n8n.md).

## Prérequis

- Node.js 24 (`node --version`) : les versions récentes de n8n (2.4x) l'exigent.
- Un navigateur.
- Le kit `..\avance\E06-service-client-boutique-en-ligne\` et le venv du palier avancé (`..\avance\.venv`, voir `..\avance\README.md`) pour l'API de suivi et les variantes B et C.
- Un modèle : clé API Anthropic, ou Ollama installé localement (voir plus bas).

Docker n'est pas nécessaire. Il ne sert que pour exposer un webhook n8n sur Internet (tunnel public), ce qu'aucune variante ne demande.

## Installation locale

```powershell
npx n8n
```

Au premier lancement, `npx` télécharge n8n dans le cache npm (plusieurs centaines de Mo ; compter de 10 à 40 minutes selon la connexion), sans installation globale. Pour préparer le poste à l'avance, lancer `npx --yes n8n --version` : le téléchargement se fait sans démarrer le serveur. Même avec le cache rempli, chaque `npx n8n` vérifie le paquet avant de démarrer : compter environ une minute. Ouvrir ensuite http://localhost:5678 et créer le compte propriétaire de l'instance (stocké dans la base locale de n8n, aucun service externe).

Points utiles :

- Les données de n8n (base SQLite, identifiants chiffrés, workflows) sont dans `%USERPROFILE%\.n8n`.
- n8n présente l'installation npm comme destinée au développement et aux tests ; elle est dépréciée à partir de n8n 3.0, où l'image Docker officielle prend le relais.
- n8n 2.x limite l'accès des nœuds de fichiers (« Read/Write Files from Disk ») à des dossiers autorisés, par défaut `~/.n8n-files` seulement. Pour lire les données du kit et écrire les résultats, définir la variable avant le lancement, avec les dossiers séparés par un point-virgule (le dossier de sortie est créé à l'avance) :

```powershell
$env:N8N_RESTRICT_FILE_ACCESS_TO = "C:\chemin\vers\avance\E06-service-client-boutique-en-ligne\donnees;C:\chemin\vers\sorties-n8n"
npx n8n
```

- Arrêter n8n par Ctrl+C dans le terminal.

## Choix du modèle

Le nœud AI Agent reçoit un sous-nœud « Chat Model ».

| Option | Sous-nœud | Réglage |
|---|---|---|
| API Anthropic | Anthropic Chat Model | créer un identifiant (*credential*) Anthropic avec la clé API, choisir le modèle dans la liste |
| Modèle local | Ollama Chat Model | Ollama lancé sur le poste, URL de base `http://localhost:11434`, modèle compatible avec l'appel d'outils (par exemple `qwen3` ou `llama3.1`, récupéré au préalable avec `ollama pull`) |

Avec un modèle local, l'appel d'outils est moins fiable : prévoir des descriptions d'outils précises et peu d'outils à la fois.

## Variantes

Les trois variantes s'appuient sur les données du kit E06 (boutique en ligne fictive Maison Lenoir : 25 courriels, 50 commandes, API de suivi transporteur). Elles se font dans l'ordre ; chacune réutilise le workflow de la précédente.

| Variante | Contenu | Niveau |
|---|---|---|
| A | workflow n8n avec un nœud AI Agent et des outils natifs de n8n | 1 à 2 |
| B | le nœud AI Agent utilise un serveur MCP externe via le nœud MCP Client Tool | 2 |
| C | un workflow n8n est exposé comme serveur MCP et appelé depuis Claude Desktop ou l'Agent SDK | 2 à 3 |

### Variante A : nœud AI Agent et outils natifs

Démarrer l'API de suivi du kit dans un terminal séparé :

```powershell
cd ..\avance\E06-service-client-boutique-en-ligne
..\.venv\Scripts\python api_suivi.py --port 8765
```

Construire le workflow :

1. Déclencheur : « Manual Trigger » (exécution à la demande) ou « Chat Trigger » (fenêtre de conversation intégrée à l'éditeur, pratique pour les essais).
2. Lecture des courriels : « Read/Write Files from Disk » avec un chemin absolu en barres obliques, par exemple `C:/chemin/vers/avance/E06-service-client-boutique-en-ligne/donnees/eml/*.eml`, puis « Extract from File » pour obtenir le texte. Un chemin relatif dépend du dossier depuis lequel n8n a été lancé, et dans un motif relatif la barre oblique inverse est lue comme un caractère d'échappement.
3. Nœud AI Agent, avec :
   - un Chat Model (voir plus haut) ;
   - un message système qui décrit la tâche, les types de demande et les interdits ;
   - des outils natifs : « HTTP Request Tool » vers `http://127.0.0.1:8765/suivi/{numero_suivi}` ; « Call n8n Workflow Tool » vers un petit sous-workflow qui lit `commandes.json` et renvoie la commande demandée ; éventuellement « Code Tool » pour un calcul (délai de retour, par exemple).
4. Sortie : un nœud « Convert to File » puis « Read/Write Files from Disk » qui écrit un fichier par courriel (type, priorité, commande, brouillon), dans le dossier de sortie déclaré dans `N8N_RESTRICT_FILE_ACCESS_TO`.

Repérer, dans l'onglet d'exécution du nœud AI Agent, la suite des appels d'outils décidés par le modèle : c'est la partie agent du workflow. Le reste ne varie pas d'une exécution à l'autre.

Version plus proche du niveau 1 : remplacer l'outil HTTP par la lecture directe de `suivi_transporteur.json`, sans API.

### Variante B : serveur MCP externe via MCP Client Tool

Le nœud « MCP Client Tool » se branche comme outil du nœud AI Agent et lui donne accès aux outils d'un serveur MCP. Il parle MCP en HTTP (Streamable HTTP, ou SSE pour les anciens serveurs), pas en stdio. Les serveurs des kits avancés sont lancés en stdio : il faut les relancer en Streamable HTTP.

Avec le SDK `mcp` 2.x, le changement tient en une ligne, à la place de `serveur.run("stdio")` :

```python
serveur.run("streamable-http", host="127.0.0.1", port=8000, stateless_http=True)
```

Le point d'accès est alors `http://127.0.0.1:8000/mcp`. Écrire `127.0.0.1` et non `localhost` dans n8n : Node.js peut résoudre `localhost` en adresse IPv6 (`::1`), sur laquelle le serveur n'écoute pas. Pour ne pas modifier le kit E06, le lanceur `lanceur_http_e06.py` de ce dossier importe le serveur du kit tel quel et ne change que le transport :

```powershell
# terminal 1 : API de suivi
cd ..\avance\E06-service-client-boutique-en-ligne
..\.venv\Scripts\python api_suivi.py --port 8765

# terminal 2 : serveur MCP E06 en Streamable HTTP (depuis le dossier n8n)
..\avance\.venv\Scripts\python lanceur_http_e06.py --port 8000
```

Vérification sans n8n : `..\avance\.venv\Scripts\python test_lanceur_http.py` démarre l'API et le serveur sur d'autres ports (8766 et 8001), appelle trois outils en lecture et affiche `OK : serveur E06 joignable en Streamable HTTP`.

Dans n8n :

1. Ajouter un outil « MCP Client Tool » au nœud AI Agent.
2. Transport : HTTP Streamable ; URL : `http://127.0.0.1:8000/mcp` ; authentification : aucune (serveur local).
3. Outils à inclure : tous, ou une sélection (par exemple sans `enregistrer_brouillon` et `poser_etiquette` pour une première exécution en lecture seule).
4. Retirer les outils natifs de la variante A qui font double emploi.

Le serveur n'écoute que sur `127.0.0.1` et refuse les requêtes dont l'en-tête Host n'est pas local. Si n8n tourne dans Docker, l'adresse `host.docker.internal` est refusée : garder n8n en local, ou lancer le serveur avec `--host 0.0.0.0` et régler le paramètre `transport_security` du SDK.

Comparer avec la variante A : la logique métier (requêtes SQL, base en lecture seule, absence d'outil d'envoi) est désormais portée par le serveur MCP et non par le workflow. Le même serveur sert Claude Desktop, l'Agent SDK ou n8n.

### Variante C : exposer un workflow n8n comme serveur MCP

Deux mécanismes existent.

**Nœud « MCP Server Trigger ».** Un workflow qui commence par ce déclencheur devient un serveur MCP. Les outils branchés sur le déclencheur (par exemple « Call n8n Workflow Tool » vers le workflow de la variante A ou B) sont exposés aux clients MCP. Le nœud affiche deux URL : une URL de test, active pendant l'écoute dans l'éditeur, et une URL de production, active une fois le workflow publié. Transports : Streamable HTTP et SSE. Authentification : aucune, *bearer* ou en-tête.

**Serveur MCP de l'instance.** Dans Settings > Instance-level MCP, activer l'accès MCP, puis rendre chaque workflow visible (menu du workflow > Settings > Available in MCP). L'URL se termine par `/mcp-server/http` ; l'authentification se fait par OAuth ou par jeton d'accès généré dans la boîte de dialogue « Connect a client ». Les clients peuvent alors rechercher et exécuter les workflows autorisés.

Appel depuis l'Agent SDK (Python), avec l'URL et le jeton du MCP Server Trigger ; installation depuis le dossier `avance\` : `.venv\Scripts\python -m pip install claude-agent-sdk` ; authentification par la variable d'environnement `ANTHROPIC_API_KEY`.

```python
import asyncio

from claude_agent_sdk import ClaudeAgentOptions, query

options = ClaudeAgentOptions(
    mcp_servers={
        "n8n": {
            "type": "http",
            "url": "http://localhost:5678/mcp/<chemin-du-trigger>",  # URL affichée par le nœud
            "headers": {"Authorization": "Bearer <jeton>"},
        }
    },
    allowed_tools=["mcp__n8n__*"],
)



async def main() -> None:
    async for message in query(prompt="Traiter les courriels non lus.", options=options):
        print(message)


asyncio.run(main())
```

Appel depuis Claude Desktop : passer par la passerelle `mcp-remote` (relais entre stdio et HTTP), dans `%APPDATA%\Claude\claude_desktop_config.json`, puis redémarrer Claude Desktop :

```json
{
  "mcpServers": {
    "n8n": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:5678/mcp/<chemin-du-trigger>",
               "--header", "Authorization: Bearer ${AUTH_TOKEN}"],
      "env": { "AUTH_TOKEN": "<jeton>" }
    }
  }
}
```

La variante C inverse les rôles : n8n n'est plus l'agent mais un fournisseur d'outils, et l'agent tourne ailleurs. Si le workflow exposé contient lui-même un nœud AI Agent, deux agents coopèrent : un agent appelant et un agent spécialisé dans n8n, d'où le niveau 3.

## Fichiers du dossier

| Fichier | Rôle |
|---|---|
| `N01-assistant-demandes-n8n.md` | énoncé de l'exercice |
| `lanceur_http_e06.py` | serveur MCP du kit E06 en Streamable HTTP, sans modifier le kit |
| `test_lanceur_http.py` | vérification du lanceur : démarrage, trois appels d'outils, arrêt |

## Références

- Installation npm : https://docs.n8n.io/hosting/installation/npm/
- MCP Client Tool : https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/
- MCP Server Trigger : https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/
- Serveur MCP de l'instance : https://docs.n8n.io/advanced-ai/accessing-n8n-mcp-server/
