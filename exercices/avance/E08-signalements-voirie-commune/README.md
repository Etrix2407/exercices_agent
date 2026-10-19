# E08. Kit avancé : signalements de voirie d'une commune

Données du palier middle (30 signalements, référentiel des voies et repères, 8 tickets existants) chargées dans une boîte mail locale et un outil de tickets SQLite, servis par un serveur MCP. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `donnees/` | copie des données middle (`eml/`, `referentiel_voirie.csv`, `tickets_existants.json`) |
| `init_donnees.py` | recrée `boite/` (30 signalements non lus) et `voirie.db` (référentiel, tickets, commentaires, alertes) |
| `boite_kit.py` | boîte au format de `../fausse-boite-mail` avec un dossier `brouillons/` ; envoi désactivé |
| `tickets.py` | outil de tickets et recherche dans le référentiel ; consultation en ligne de commande |
| `serveur_mcp.py` | serveur MCP `commune-signalements` |
| `test_kit.py` | démarre le serveur et appelle chaque outil |

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E08-signalements-voirie-commune
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E08 fonctionnel`. Le test réinitialise les données au début et à la fin.

Consultation de l'outil de tickets par une personne :

```powershell
..\.venv\Scripts\python tickets.py lister
..\.venv\Scripts\python tickets.py voir TK-2026-0411
..\.venv\Scripts\python tickets.py alertes
```

## Outils exposés

| Type | Nom | Rôle |
|---|---|---|
| outil | `lister_signalements(non_lus?)`, `lire_signalement(identifiant, marquer_lu?)` | signalements reçus |
| outil | `rechercher_voie(texte)` | voies, lieux-dits et repères cités dans un texte d'adresse |
| outil | `chercher_tickets_ouverts(service?, adresse?, texte?)` | tickets ouverts ou en cours |
| outil | `lire_ticket(ticket_id)` | détail et commentaires |
| outil | `creer_ticket(service, categorie, adresse, description, message_origine, adresse_a_preciser?, urgent?)` | nouveau ticket, un seul par message |
| outil | `ajouter_commentaire(ticket_id, texte, message_origine?)` | commentaire sur un ticket existant |
| outil | `alerter_accueil(ticket_id, message)` | alerte lue par l'agent d'accueil |
| outil | `enregistrer_brouillon(identifiant_signalement, corps, sujet?, destinataire?)` | brouillon dans `boite/brouillons/` |
| outil | `lister_brouillons()` | relecture des brouillons |
| ressource | `commune://referentiel-voies` | référentiel complet (CSV) |
| prompt | `traiter_signalement(identifiant)` | enchaînement type pour un signalement |

Services : `voirie`, `eclairage`, `proprete`, `espaces_verts`. Les outils de liste renvoient `{"nombre": n, "<éléments>": [...]}` ; `nombre` vaut 0 pour une liste vide. Aucun outil de clôture, de suppression ni d'envoi.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter, puis redémarrer Claude Desktop :

```json
{
  "mcpServers": {
    "commune-signalements": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E08-signalements-voirie-commune\\serveur_mcp.py"]
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
KIT = r"C:\dev\exercices\avance\E08-signalements-voirie-commune"

options = ClaudeAgentOptions(
    mcp_servers={"commune": {"command": PYTHON, "args": [KIT + r"\serveur_mcp.py"]}},
    allowed_tools=["mcp__commune__*"],
)


async def main() -> None:
    async for message in query(prompt="Traiter les signalements non lus.", options=options):
        print(message)


asyncio.run(main())
```

Les noms d'outils vus par l'agent prennent la forme `mcp__commune__creer_ticket`.
