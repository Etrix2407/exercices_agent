"""Serveur MCP « e11-grille » : grille de référence et calcul des échéances contractuelles.

Lecture seule. Utilisé par l'agent d'analyse et par l'agent de rédaction.
Lancement : ..\\.venv\\Scripts\\python serveur_grille.py (transport stdio).
"""

import calendar
from datetime import date, timedelta
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import requete

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

serveur = MCPServer(
    name="e11-grille",
    instructions=(
        "Grille fictive de revue des contrats fournisseurs : 10 clauses (G1 à G10), "
        "trois positions chacune (acceptable, repli, refusée). Lecture seule."
    ),
)


def ajouter_mois(depart: date, mois: int) -> date:
    """Même quantième, mois décalé ; ramené au dernier jour du mois si besoin (31/01 + 1 mois = 28/02)."""
    total = depart.month - 1 + mois
    annee, mois_cible = depart.year + total // 12, total % 12 + 1
    return date(annee, mois_cible, min(depart.day, calendar.monthrange(annee, mois_cible)[1]))


@serveur.tool(annotations=LECTURE)
def lire_grille() -> list[dict]:
    """Les 10 clauses de la grille avec critère et trois positions."""
    return requete("SELECT * FROM grille ORDER BY CAST(SUBSTR(code, 2) AS INTEGER)")


@serveur.tool(annotations=LECTURE)
def lire_clause_grille(code: str) -> dict[str, Any]:
    """Une clause de la grille (G1 à G10)."""
    lignes = requete("SELECT * FROM grille WHERE code = ?", (code.upper(),))
    if not lignes:
        raise ToolError(f"Clause inconnue : {code}. Codes : G1 à G10.")
    return lignes[0]


@serveur.tool(annotations=LECTURE)
def calculer_echeances_contrat(date_debut: str, duree_mois: int, preavis_mois: int = 0, reconduction_mois: int = 0) -> dict[str, Any]:
    """Terme de la période initiale, date limite de dénonciation et terme après une reconduction.

    Conventions : terme = date de début + durée (en mois) ; dernier jour couvert = terme - 1 jour ;
    date limite de dénonciation = terme - préavis (en mois).
    """
    try:
        debut = date.fromisoformat(date_debut)
    except ValueError as e:
        raise ToolError(f"Date illisible (AAAA-MM-JJ attendu) : {date_debut}") from e
    if duree_mois <= 0 or preavis_mois < 0 or reconduction_mois < 0:
        raise ToolError("Durée strictement positive, préavis et reconduction positifs ou nuls attendus.")
    terme = ajouter_mois(debut, duree_mois)
    resultat = {
        "date_debut": debut.isoformat(),
        "terme_periode_initiale": terme.isoformat(),
        "dernier_jour_couvert": (terme - timedelta(days=1)).isoformat(),
    }
    if preavis_mois:
        resultat["date_limite_denonciation"] = ajouter_mois(terme, -preavis_mois).isoformat()
    if reconduction_mois:
        resultat["terme_apres_reconduction"] = ajouter_mois(terme, reconduction_mois).isoformat()
    return resultat


@serveur.resource(
    "grille://reference",
    name="grille_reference",
    mime_type="text/markdown",
    description="Grille de référence complète en Markdown",
)
def grille_reference() -> str:
    blocs = [
        f"## {c['code']}. {c['intitule']}\n\n- Critère : {c['critere']}\n- Acceptable : {c['acceptable']}\n"
        f"- Repli : {c['repli']}\n- Refusée : {c['refusee']}"
        for c in lire_grille()
    ]
    return "# Grille de référence\n\n" + "\n\n".join(blocs)


@serveur.prompt(description="Classer une clause extraite au regard de la grille")
def classer_clause(code: str, citation: str) -> str:
    return (
        f"Comparer la citation suivante à la clause {code} de la grille (lire_clause_grille). "
        "Classer en conforme, repli, refusée ou absente. Justifier en reprenant les termes de la position retenue "
        "et en s'appuyant uniquement sur la citation.\n\nCitation : « " + citation + " »"
    )


if __name__ == "__main__":
    serveur.run("stdio")
