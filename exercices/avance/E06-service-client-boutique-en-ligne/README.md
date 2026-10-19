# E06. Kit avancé : service client d'une boutique en ligne

Données du palier middle (25 courriels, 50 commandes, suivi transporteur, modèles de réponse, politique de retour) chargées dans une boîte mail locale, une base SQLite et une API HTTP locale de suivi, servies par un serveur MCP. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `donnees/` | copie des données middle (`eml/`, `commandes.json`, `suivi_transporteur.json`, modèles, politique) |
| `init_donnees.py` | recrée `boite/` (25 courriels non lus) et `commandes.db` |
| `boite_kit.py` | boîte au format de `../fausse-boite-mail` avec un dossier `brouillons/` ; envoi désactivé |
| `api_suivi.py` | API HTTP locale du transporteur (bibliothèque standard), `GET /suivi/<numero_suivi>` |
| `serveur_mcp.py` | serveur MCP `boutique-service-client` |
| `test_kit.py` | démarre l'API et le serveur, appelle chaque outil |

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E06-service-client-boutique-en-ligne
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E06 fonctionnel`. Le test réinitialise les données au début et à la fin.

Pour un agent, démarrer l'API de suivi dans un terminal séparé avant le serveur MCP :

```powershell
..\.venv\Scripts\python api_suivi.py --port 8765
```

Vérification : `http://127.0.0.1:8765/suivi/ETX261002BE` dans un navigateur. Autre port : variable `SUIVI_API_URL` du serveur MCP.

## Outils exposés

| Type | Nom | Rôle |
|---|---|---|
| outil | `lister_courriels(non_lus?, chercher?)` | courriels reçus, du plus ancien au plus récent |
| outil | `lire_courriel(identifiant, marquer_lu?)` | courriel complet |
| outil | `chercher_commande(numero)` | commande, articles, numéro de suivi |
| outil | `commandes_client(email_ou_nom)` | commandes d'un client |
| outil | `suivi_colis(numero_suivi)` | appel HTTP à l'API de suivi |
| outil | `enregistrer_brouillon(identifiant_courriel, corps, sujet?)` | brouillon dans `boite/brouillons/` |
| outil | `poser_etiquette(identifiant_courriel, type_demande, priorite, numero_commande?, escalade?, raison?)` | classement dans `boite/etiquettes.json` |
| outil | `lister_brouillons()`, `lister_etiquettes()` | relecture des sorties |
| ressource | `boutique://politique-retour`, `boutique://modeles-reponse` | textes de référence |
| prompt | `traiter_courriel(identifiant)` | enchaînement type pour un courriel |

Les outils de liste renvoient `{"nombre": n, "<éléments>": [...]}` ; `nombre` vaut 0 pour une liste vide. La base est ouverte en `mode=ro`. Aucun outil d'envoi : `boite/outbox/` reste vide.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter, puis redémarrer Claude Desktop (l'API de suivi doit tourner) :

```json
{
  "mcpServers": {
    "boutique-service-client": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E06-service-client-boutique-en-ligne\\serveur_mcp.py"],
      "env": { "SUIVI_API_URL": "http://127.0.0.1:8765" }
    }
  }
}
```

## Agent SDK (Python)

Installation depuis le dossier `avance\` : `.venv\Scripts\python -m pip install claude-agent-sdk` ; authentification par la variable d'environnement `ANTHROPIC_API_KEY`.

```python
import asyncio

from claude_agent_sdk import ClaudeAgentOptions, query

PYTHON = r"C:\dev\exercices\avance\.venv\Scripts\python.exe"
KIT = r"C:\dev\exercices\avance\E06-service-client-boutique-en-ligne"

options = ClaudeAgentOptions(
    mcp_servers={"boutique": {"command": PYTHON, "args": [KIT + r"\serveur_mcp.py"]}},
    allowed_tools=["mcp__boutique__*"],
)


async def main() -> None:
    async for message in query(prompt="Traiter les courriels non lus.", options=options):
        print(message)


asyncio.run(main())
```

Les noms d'outils vus par l'agent prennent la forme `mcp__boutique__lister_courriels`.
