# E07. Kit avancé : demandes de réservation de groupe d'un hôtel

Données du palier middle (10 demandes, planning des chambres et des salles, grille tarifaire) chargées dans une boîte mail locale et une base SQLite, servies par un serveur MCP avec un calcul de devis écrit en code. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `donnees/` | copie des données middle (`eml/`, `planning_chambres.csv`, `planning_salles.csv`, `grille_tarifaire.md`) |
| `init_donnees.py` | recrée `boite/` (10 demandes non lues) et `hotel.db` (planning, grille transcrite, pré-réservations vides) |
| `boite_kit.py` | boîte au format de `../fausse-boite-mail` avec un dossier `brouillons/` ; envoi désactivé |
| `planning.py` | disponibilités, devis, pré-réservations ; validation humaine en ligne de commande |
| `serveur_mcp.py` | serveur MCP `hotel-reservations-groupe` |
| `test_kit.py` | démarre le serveur et appelle chaque outil |

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E07-demandes-reservation-hotel
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E07 fonctionnel`. Le test réinitialise les données au début et à la fin.

Validation d'une pré-réservation par une personne (confirmation demandée dans le terminal) :

```powershell
..\.venv\Scripts\python planning.py lister
..\.venv\Scripts\python planning.py valider 1
```

## Outils exposés

| Type | Nom | Rôle |
|---|---|---|
| outil | `lister_demandes(non_lues?)`, `lire_demande(identifiant, marquer_lue?)` | demandes reçues |
| outil | `disponibilites_chambres(arrivee, depart)` | chambres libres par type, nuit par nuit |
| outil | `disponibilites_salles(date_debut, date_fin)` | salles libres et occupées par jour |
| outil | `calculer_devis(arrivee, depart, chambres, salles?, repas?)` | lignes, total TTC et tableau Markdown d'après la grille |
| outil | `enregistrer_fiche_besoins(identifiant_demande, fiche)` | fiche JSON dans `boite/fiches/` |
| outil | `enregistrer_brouillon(identifiant_demande, corps, sujet?, devis_markdown?)` | brouillon, devis joint en `devis.md` |
| outil | `lister_brouillons()` | relecture des brouillons |
| outil | `pre_reserver(identifiant_demande, arrivee, depart, chambres, salles?)` | pré-réservation au statut `a_valider` si les chambres et salles sont libres, planning inchangé |
| outil | `lister_pre_reservations(statut?)` | pré-réservations enregistrées |
| ressource | `hotel://grille-tarifaire` | grille complète et règles de calcul |
| prompt | `traiter_demande(identifiant)` | enchaînement type pour une demande |

Formats : dates `AAAA-MM-JJ` ; `chambres` = `{"double": 4, "twin": 2}` ; `salles` = `[{"salle": "Érable", "jours": 1}]` ; `repas` = `[{"prestation": "diner", "couverts": 50, "nombre": 1}]` (prestations : `dejeuner_buffet`, `diner`, `pause_cafe`). Les disponibilités ne tiennent compte que du planning, pas des pré-réservations en attente. Les outils de liste renvoient `{"nombre": n, "<éléments>": [...]}` ; `nombre` vaut 0 pour une liste vide. Aucun outil d'envoi.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter, puis redémarrer Claude Desktop :

```json
{
  "mcpServers": {
    "hotel-reservations-groupe": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E07-demandes-reservation-hotel\\serveur_mcp.py"]
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
KIT = r"C:\dev\exercices\avance\E07-demandes-reservation-hotel"

options = ClaudeAgentOptions(
    mcp_servers={"hotel": {"command": PYTHON, "args": [KIT + r"\serveur_mcp.py"]}},
    # Outils autorisés sans confirmation ; pre_reserver est retiré : l'agent lit et prépare des brouillons
    allowed_tools=[
        "mcp__hotel__lister_demandes", "mcp__hotel__lire_demande",
        "mcp__hotel__disponibilites_chambres", "mcp__hotel__disponibilites_salles",
        "mcp__hotel__calculer_devis", "mcp__hotel__enregistrer_fiche_besoins",
        "mcp__hotel__enregistrer_brouillon", "mcp__hotel__lister_brouillons",
    ],
    disallowed_tools=["mcp__hotel__pre_reserver"],
)


async def main() -> None:
    async for message in query(prompt="Traiter les demandes de groupe non lues.", options=options):
        print(message)


asyncio.run(main())
```
