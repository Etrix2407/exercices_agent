# E11. Kit avancé : revue des contrats fournisseurs

Données du palier middle (5 contrats, grille de référence, note de test) chargées dans une base SQLite avec un index par mots, et servies par trois serveurs MCP découpés par rôle. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `init_donnees.py` | construit `donnees/contrats.db` depuis `../../middle/E11-revue-contrats-fournisseurs` |
| `commun.py` | accès en lecture seule, découpage en phrases, recherche, vérification de citation |
| `serveur_contrats.py` | serveur `e11-contrats` |
| `serveur_grille.py` | serveur `e11-grille` |
| `serveur_notes.py` | serveur `e11-notes` |
| `orchestration_squelette.py` | répartition des serveurs et des outils par rôle, fonctions à écrire |
| `test_kit.py` | démarre chaque serveur et appelle chaque outil |

La base contient une table `sections` (une ligne par article, plus Parties, Préambule et Signatures) et une table `index_mots` (mot normalisé sans accent, section, nombre d'occurrences).

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E11-revue-contrats-fournisseurs
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E11 fonctionnel`. La base est fournie ; `init_donnees.py` la recrée. Les sorties sont écrites dans `sorties\` (autre dossier : variable `E11_SORTIES`).

## Outils exposés

| Serveur | Outils | Ressource | Prompt |
|---|---|---|---|
| `e11-contrats` (lecture) | `lister_contrats`, `lire_contrat(contrat)`, `sommaire_contrat(contrat)`, `lire_article(contrat, numero_article)`, `rechercher_passages(contrat, mots_cles, maximum)`, `verifier_citation(contrat, citation)`, `verifier_citations_note(contrat, texte_note)` | `contrats://liste` | `extraire_clauses` |
| `e11-grille` (lecture) | `lire_grille`, `lire_clause_grille(code)`, `calculer_echeances_contrat(date_debut, duree_mois, preavis_mois, reconduction_mois)` | `grille://reference` | `classer_clause` |
| `e11-notes` (brouillons) | `ecrire_note_revue`, `ecrire_synthese_acheteur`, `enregistrer_remarque`, `traiter_remarque`, `lister_remarques`, `lister_notes`, `lire_note` | `modele://note-revue` | `contredire_note` |

Un contrat se désigne par son identifiant (`contrat-01`) ou son numéro (`CTR-2026-0412`).

`verifier_citation` cherche la citation mot pour mot ; seuls les écarts d'espaces et de retours à la ligne sont tolérés. En cas d'échec, la réponse indique si la citation passerait en neutralisant apostrophes et guillemets typographiques, et donne la phrase la plus proche du contrat avec un taux de similarité. Une citation exacte de moins de cinq mots est signalée par un avertissement. `verifier_citations_note` applique la même vérification à toutes les citations d'une note : texte entre « », et texte entre guillemets droits ou anglais d'au moins quatre mots.

Les projets de contrat ne sont pas datés : la `date_debut` de `calculer_echeances_contrat` est une hypothèse (date de signature envisagée), à indiquer comme telle dans la note.

Chaque serveur met quelques secondes à démarrer sous Windows (import du SDK `mcp`) : ouvrir les connexions une fois par exécution et les réutiliser d'un dossier à l'autre plutôt que de relancer les serveurs à chaque agent. Les outils de recherche et de liste renvoient un objet `{"nombre": n, ...}`, y compris quand rien n'est trouvé.

Les notes et synthèses écrites commencent par la mention « brouillon, non validé par un juriste » ; rien n'est transmis.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter :

```json
{
  "mcpServers": {
    "e11-contrats": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E11-revue-contrats-fournisseurs\\serveur_contrats.py"]
    },
    "e11-grille": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E11-revue-contrats-fournisseurs\\serveur_grille.py"]
    },
    "e11-notes": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E11-revue-contrats-fournisseurs\\serveur_notes.py"],
      "env": { "E11_SORTIES": "C:\\dev\\exercices\\avance\\E11-revue-contrats-fournisseurs\\sorties" }
    }
  }
}
```

## Agent SDK

Avec le SDK d'agent Python (`claude-agent-sdk`), déclarer les serveurs puis un sous-agent par rôle, limité à ses outils (nom complet `mcp__<serveur>__<outil>`).

Installation depuis le dossier `avance\` : `.venv\Scripts\python -m pip install claude-agent-sdk` ; authentification par la variable d'environnement `ANTHROPIC_API_KEY`. Lancer le script depuis le dossier du kit (chemins relatifs).


```python
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

PY = r"..\.venv\Scripts\python.exe"
options = ClaudeAgentOptions(
    mcp_servers={
        "e11-contrats": {"command": PY, "args": ["serveur_contrats.py"]},
        "e11-grille": {"command": PY, "args": ["serveur_grille.py"]},
        "e11-notes": {"command": PY, "args": ["serveur_notes.py"]},
    },
    agents={
        "contradicteur": AgentDefinition(
            description="Relit une note de revue et signale les affirmations non étayées par le contrat",
            prompt="...",
            tools=[
                "mcp__e11-contrats__lire_article",
                "mcp__e11-contrats__verifier_citations_note",
                "mcp__e11-grille__lire_clause_grille",
                "mcp__e11-notes__lire_note",
                "mcp__e11-notes__enregistrer_remarque",
            ],
        ),
        # extraction, analyse, redaction : même principe, voir ROLES dans orchestration_squelette.py
    },
)
```

`verifier_citations_note` peut aussi être appelé directement en Python, hors agent, comme contrôle final d'une note.
