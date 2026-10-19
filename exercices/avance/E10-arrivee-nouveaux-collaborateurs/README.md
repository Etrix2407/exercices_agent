# E10. Kit avancé : préparation de l'arrivée des nouveaux collaborateurs

Données du palier middle (6 fiches d'arrivée, référentiel métier vers accès, bureaux, sites, paramètres, état des tâches) servies par trois serveurs MCP. Les agents se coordonnent au travers d'un fichier d'état partagé, protégé par un verrou. Python 3.12, SDK `mcp` 2.3, transport stdio. Aucun service externe.

## Contenu

| Fichier | Rôle |
|---|---|
| `init_donnees.py` | copie les référentiels du palier middle dans `donnees\` et crée `etat\etat_partage.json` |
| `donnees\` | fiches YAML, CSV, `parametres.json`, `jours_feries.json` (liste modifiable) |
| `etat\etat_partage.json` | état partagé : tâches par service, demandes, propositions de bureau, relances, journal |
| `commun.py` | lecture des référentiels, verrou et écriture atomique de l'état, calcul des jours ouvrés |
| `serveur_referentiel.py` | serveur `e10-referentiel` |
| `serveur_etat.py` | serveur `e10-etat` |
| `serveur_redaction.py` | serveur `e10-redaction` |
| `orchestration_squelette.py` | répartition des serveurs et des outils par rôle, fonctions à écrire |
| `test_kit.py` | démarre chaque serveur et appelle chaque outil |

## Lancer

Depuis le dossier `avance\` (venv installé, voir le README du dossier) :

```powershell
cd E10-arrivee-nouveaux-collaborateurs
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Dernière ligne attendue : `OK : kit E10 fonctionnel`. Le test travaille sur une copie temporaire de l'état. `init_donnees.py` remet l'état dans sa situation initiale.

Pour simuler une réponse ou un retard de service, modifier à la main `statut`, `echeance` ou `date_reponse` d'une tâche dans `etat\etat_partage.json`, ou la valeur `date_execution`, puis relancer l'orchestration. Les référentiels sont relus à chaque appel : une ligne ajoutée dans `donnees\referentiel_metier_acces.csv` est prise en compte sans redémarrage.

`init_donnees.py` recopie aussi les référentiels du palier middle dans `donnees\` : pour remettre l'état à zéro sans perdre un métier ajouté à la main, utiliser `..\.venv\Scripts\python init_donnees.py --etat-seulement`.

Variables d'environnement : `E10_DONNEES`, `E10_ETAT`, `E10_SORTIES`.

## Outils exposés

| Serveur | Outils | Ressource | Prompt |
|---|---|---|---|
| `e10-referentiel` (lecture) | `lister_arrivees`, `lire_fiche(id_arrivee)`, `lister_metiers`, `acces_metier(metier)`, `infos_site(code_site)`, `bureaux_site(code_site, zone)`, `calculer_echeances(date_arrivee)` | `parametres://arrivees` | `preparer_demandes` |
| `e10-etat` (coordination) | `lire_etat_arrivee`, `taches_en_retard(date_reference)`, `tableau_avancement(date_reference)`, `enregistrer_demande`, `mettre_a_jour_tache`, `proposer_bureau`, `journaliser` | `etat://partage` | `point_avancement` |
| `e10-redaction` (brouillons) | `ecrire_brouillon_relance`, `ecrire_livret`, `ecrire_tableau_avancement`, `lister_sorties` | `modele://livret` | `rediger_livret` |

Les relances sont des fichiers `.eml` écrits dans `sorties\brouillons\` et enregistrés dans l'état avec le statut `brouillon` ; rien n'est envoyé. Une seconde relance pour la même tâche est refusée tant que la première reste en brouillon (la validation RH se fait en modifiant `statut` dans l'état). `enregistrer_demande` contrôle le format de l'échéance et n'accepte un `code_acces` hors référentiel que pour le service `manager`.

Chaque serveur met quelques secondes à démarrer sous Windows (import du SDK `mcp`) : ouvrir les connexions une fois par exécution et les réutiliser d'un dossier à l'autre plutôt que de relancer les serveurs à chaque agent. Les outils de recherche et de liste renvoient un objet `{"nombre": n, ...}`, y compris quand rien n'est trouvé. Après validation, un brouillon peut être transmis au serveur SMTP local de `..\fausse-boite-mail\smtp_local.py`.

## Claude Desktop

Ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`, chemins absolus à adapter :

```json
{
  "mcpServers": {
    "e10-referentiel": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E10-arrivee-nouveaux-collaborateurs\\serveur_referentiel.py"]
    },
    "e10-etat": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E10-arrivee-nouveaux-collaborateurs\\serveur_etat.py"]
    },
    "e10-redaction": {
      "command": "C:\\dev\\exercices\\avance\\.venv\\Scripts\\python.exe",
      "args": ["C:\\dev\\exercices\\avance\\E10-arrivee-nouveaux-collaborateurs\\serveur_redaction.py"]
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
        "e10-referentiel": {"command": PY, "args": ["serveur_referentiel.py"]},
        "e10-etat": {"command": PY, "args": ["serveur_etat.py"]},
        "e10-redaction": {"command": PY, "args": ["serveur_redaction.py"]},
    },
    agents={
        "informatique": AgentDefinition(
            description="Déduit les comptes et accès à demander pour une arrivée",
            prompt="...",
            tools=[
                "mcp__e10-referentiel__lire_fiche",
                "mcp__e10-referentiel__acces_metier",
                "mcp__e10-referentiel__calculer_echeances",
                "mcp__e10-etat__enregistrer_demande",
                "mcp__e10-etat__journaliser",
            ],
        ),
        # rh, logistique : même principe, voir ROLES dans orchestration_squelette.py
    },
)
```

Lorsque plusieurs processus écrivent l'état en même temps (agents en parallèle, plusieurs clients MCP), le verrou de `commun.py` garde le fichier cohérent.
