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

## Agent de traitement des demandes

L'agent traite chaque demande de la boîte et prépare une fiche et un brouillon de réponse, sans rien réserver ni envoyer. Son code est rangé dans `agent/`, séparé du kit (qui reste inchangé) :

```
agent/
├── __main__.py              lancement : python -m agent
├── process_requests.py      orchestrateur et ligne de commande : une session d'agent par demande
├── checks.py                contrôles en code : devis, dates alternatives, brouillon, planning inchangé
├── synthesis.py             résultats et synthèse : format Markdown, écriture atomique, fusion cumulative
├── mcp_bridge.py            les cinq outils de l'agent, branchés sur le serveur MCP du kit
├── prompt_sys_reservation.md
├── llm_providers/           boucle d'agent Gemini ou Claude (un fichier par SDK)
├── output/                  sorties (ignorées par git)
└── tests/                   tests sans réseau ni modèle ; fakes.py : faux kit partagé
```

Architecture : une boucle d'agent (`agent/llm_providers/`, Gemini ou Claude) appelle cinq outils définis dans `agent/mcp_bridge.py`, qui relaient vers le serveur MCP `hotel-reservations-groupe` du kit, démarré en stdio le temps du traitement.

| Outil | Rôle | Outil(s) du serveur |
|---|---|---|
| `read_email(demande_id)` | lit le courriel de la demande en cours, encadré comme une donnée | `lire_demande` |
| `read_planning(date_debut, date_fin, besoins?)` | disponibilités en lecture seule ; avec `besoins`, chambres manquantes, salles occupées et verdict `disponible` | `disponibilites_chambres`, `disponibilites_salles` |
| `read_grille()` | grille tarifaire | ressource `hotel://grille-tarifaire` |
| `calc_devis(besoins)` | devis calculé en code d'après la grille (aucun montant fixé par le modèle) | `calculer_devis` |
| `write_draft(fiche_json)` | fiche et brouillon ; un seul appel par demande | `enregistrer_fiche_besoins`, `enregistrer_brouillon` |

Le devis du dernier `calc_devis` est joint par le code (`devis.md`) pour les statuts `proposition` et `dates_alternatives`, jamais pour `precisions_requises`, `hors_perimetre` ou `erreur`. Avec le statut `erreur`, `write_draft` n'écrit ni fiche ni brouillon : un brouillon valide d'un traitement précédent n'est jamais écrasé. `pre_reserver` n'est jamais exposé à l'agent : le planning reste inchangé.

### Installation

Le `requirements.txt` du dossier `avance\` contient tout : SDK MCP, SDK des fournisseurs (`google-genai`, `anthropic`), `python-dotenv` et `pytest`.

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
```

Clés lues dans le fichier partagé `exercices\.env` : `GEMINI_API_KEY` ou `ANTHROPIC_API_KEY`. Avec les réglages actuels (`LLM_PROVIDER = "anthropic"`, `LLM_MODEL = "claude-haiku-4-5"`), `ANTHROPIC_API_KEY` est requise ; passer `LLM_PROVIDER` à `"gemini"` (et `LLM_MODEL` à un modèle Gemini) pour utiliser `GEMINI_API_KEY`.

### Réglages

Trois constantes en tête de `agent/process_requests.py` : `LLM_PROVIDER` (`"gemini"` ou `"anthropic"`), `LLM_MODEL` et `LLM_TEMPERATURE` (`None` : valeur par défaut du modèle ; ignorée par Claude). Elles priment sur les variables `LLM_PROVIDER` et `LLM_MODEL` du `.env` ; avec `None`, le choix se fait selon les clés présentes.
`MAX_STEPS` fixe le nombre maximal de tours du modèle par demande ; la même valeur est insérée dans le prompt.

### Lancer

Depuis le dossier du kit :

```powershell
..\.venv\Scripts\python -m agent --reset --only demande_01_mariage
..\.venv\Scripts\python -m agent --reset
..\.venv\Scripts\python -m pytest          # tests de l'agent (pytest.ini : agent/tests)
```

`--reset` recrée la boîte et le planning avant le traitement et repart d'une synthèse vide ; `--only` limite à une demande (identifiant vérifié avant le démarrage du serveur) ; `--output` change le dossier de sortie (par défaut `agent\output`).
Comme le serveur MCP, l'agent respecte les variables `KIT_BASE` (base du planning) et `KIT_BOITE` (boîte et brouillons).

### Sorties

- `agent\output\synthese.md` : tableau par demande (statut, séjour, informations manquantes, dates alternatives, devis TTC, brouillon) et points à vérifier ;
- `agent\output\resultats.json` : résultats bruts ;
- `agent\output\journal_outils.txt` : chaque appel d'outil et chaque refus ;
- `boite\fiches\` : fiches JSON ; `boite\brouillons\` : brouillons, avec `devis.md` joint le cas échéant.

`synthese.md` et `resultats.json` sont réécrits après chaque demande ; tant que le lot n'est pas fini, la synthèse porte la ligne « Avancement : n/N demandes traitées (lot en cours) ».
La synthèse est cumulative : les demandes analysées lors des lancements précédents restent ; une demande traitée à nouveau est mise à jour (colonnes « Traité le » et « Changements » : statut, dates, effectif, chambres, devis, informations manquantes). Un échec ne remplace pas un résultat valide déjà enregistré : il est seulement signalé. Le nouveau brouillon d'une demande traitée à nouveau remplace l'ancien sous le même numéro (`bNNN`), et sa fiche JSON est réécrite. Un Ctrl+C conserve les demandes déjà traitées.
L'écriture passe par un fichier temporaire : un fichier ouvert dans l'éditeur n'est jamais à moitié écrit.

Statuts possibles : `proposition`, `precisions_requises`, `dates_alternatives`, `hors_perimetre`, `erreur`, et `non_traitee` (demande non traitée parce que le lot s'est arrêté : quota épuisé, configuration refusée ou serveur MCP arrêté ; relancer avec `--only`). Si le lot s'arrête juste après un `write_draft` réussi, la fiche et le brouillon de la demande en cours sont conservés.

### Contrôles automatiques

- devis `proposition` recalculé à partir des besoins de la fiche et comparé au total joint ;
- chaque date alternative revérifiée dans le planning : chambres libres, et salles libres aux dates décalées d'autant que le séjour ;
- `dates_alternatives` : devis exigé, sur la première date alternative, et recalculé à partir des besoins décalés (mêmes chambres, salles décalées, repas inchangés) ;
- `precisions_requises` sans aucune information manquante listée ;
- corps du brouillon : montant différent du total du devis joint, mots « remise », « réduction » ou « geste commercial » ;
- empreinte SHA-256 du contenu du planning et des pré-réservations comparée avant et après : « Planning inchangé » dans la synthèse.

Les écarts sont ajoutés aux points à vérifier de la synthèse.

Le quota gratuit de Gemini est limité (requêtes par minute et par jour) : lancer par étapes avec `--only`.
