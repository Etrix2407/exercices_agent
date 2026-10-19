# E09. Kit avancé : pré-instruction des sinistres habitation

Données du palier middle (8 déclarations, conditions générales, 8 conditions particulières, barème de franchise) chargées dans une base SQLite et servies par quatre serveurs MCP, un par périmètre d'agent. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `init_donnees.py` | construit `donnees/sinistres.db` depuis `../../middle/E09-instruction-sinistres-assurance` |
| `donnees/jours_feries.json` | jours fériés utilisés pour le calcul des jours ouvrés (liste modifiable) |
| `commun.py` | accès en lecture seule à la base, recherche par mots-clés, calcul de dates |
| `serveur_declarations.py` | serveur `e09-declarations` |
| `serveur_contrat.py` | serveur `e09-contrat` |
| `serveur_bareme.py` | serveur `e09-bareme` |
| `serveur_sorties.py` | serveur `e09-sorties` |
| `orchestration_squelette.py` | répartition des serveurs et des outils par rôle, fonctions à écrire |
| `test_kit.py` | démarre chaque serveur et appelle chaque outil |

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E09-instruction-sinistres-assurance
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E09 fonctionnel`. La base est fournie ; `init_donnees.py` la remet dans son état initial. Les sorties sont écrites dans `sorties\` (autre dossier : variable `E09_SORTIES`).

## Outils exposés

| Serveur | Outils | Ressource | Prompt |
|---|---|---|---|
| `e09-declarations` | `lister_declarations`, `lire_declaration(numero_dossier)`, `compter_jours_ouvres(date_debut, date_fin)` | `modele://extraction` | `extraire_declaration` |
| `e09-contrat` | `rechercher_contrat(texte)`, `lire_conditions_particulieres(numero_contrat)`, `garanties_contrat(numero_contrat)`, `lire_article_cg(numero)`, `rechercher_conditions_generales(mots_cles, maximum)` | `cg://sommaire` | `verifier_couverture` |
| `e09-bareme` | `lire_bareme`, `calculer_franchise(nature, montant_estime, options)`, `calculer_montant_indicatif(nature, montant_estime, plafond, options)` | `bareme://franchises` | `calculer_montants` |
| `e09-sorties` | `ecrire_fiche`, `ecrire_brouillon_courrier`, `journaliser`, `lire_journal`, `lister_sorties` | `modele://fiche` | `rediger_courrier` |

Les trois premiers serveurs sont en lecture seule (base ouverte en `mode=ro`, annotation `readOnlyHint`). Le quatrième n'écrit que des fichiers locaux : aucun courrier n'est envoyé.

Les options passées aux calculs sont des codes du barème (`lire_bareme`, colonne `option`) ; les conditions particulières les décrivent en texte libre, la correspondance reste à faire par l'agent. Un code inconnu est refusé.

Chaque serveur met quelques secondes à démarrer sous Windows (import du SDK `mcp`) : ouvrir les connexions une fois par exécution et les réutiliser d'un dossier à l'autre plutôt que de relancer les serveurs à chaque agent. Les outils de recherche et de liste renvoient un objet `{"nombre": n, ...}`, y compris quand rien n'est trouvé.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter :

```json
{
  "mcpServers": {
    "e09-declarations": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E09-instruction-sinistres-assurance\\serveur_declarations.py"]
    },
    "e09-contrat": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E09-instruction-sinistres-assurance\\serveur_contrat.py"]
    },
    "e09-bareme": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E09-instruction-sinistres-assurance\\serveur_bareme.py"]
    },
    "e09-sorties": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E09-instruction-sinistres-assurance\\serveur_sorties.py"],
      "env": { "E09_SORTIES": "C:\\dev\\exercices\\avance\\E09-instruction-sinistres-assurance\\sorties" }
    }
  }
}
```

Claude Desktop ne connaît qu'un seul agent : cette configuration sert à essayer les outils, pas à séparer les rôles.

## Agent SDK

Avec le SDK d'agent Python (`claude-agent-sdk`), déclarer les serveurs puis un sous-agent par rôle, limité à ses outils (nom complet `mcp__<serveur>__<outil>`).

Installation depuis le dossier `avance\` : `.venv\Scripts\python -m pip install claude-agent-sdk` ; authentification par la variable d'environnement `ANTHROPIC_API_KEY`. Lancer le script depuis le dossier du kit (chemins relatifs).


```python
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

PY = r"..\.venv\Scripts\python.exe"
options = ClaudeAgentOptions(
    mcp_servers={
        "e09-declarations": {"command": PY, "args": ["serveur_declarations.py"]},
        "e09-contrat": {"command": PY, "args": ["serveur_contrat.py"]},
        "e09-bareme": {"command": PY, "args": ["serveur_bareme.py"]},
        "e09-sorties": {"command": PY, "args": ["serveur_sorties.py"]},
    },
    agents={
        "redaction": AgentDefinition(
            description="Rédige le courrier à l'assuré à partir de la synthèse de couverture",
            prompt="...",
            tools=["mcp__e09-sorties__ecrire_brouillon_courrier", "mcp__e09-sorties__journaliser"],
        ),
        # extraction, couverture : même principe, voir ROLES dans orchestration_squelette.py
    },
)
```

Une orchestration écrite à la main (appels API avec la liste d'outils de chaque rôle) convient aussi : `orchestration_squelette.py` fixe la répartition et laisse le reste à écrire.
