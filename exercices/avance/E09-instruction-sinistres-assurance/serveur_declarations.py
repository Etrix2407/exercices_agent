"""Serveur MCP « e09-declarations » : rôle d'extraction.

Lecture des déclarations de sinistre et calcul de délais en jours ouvrés.
Lancement : ..\\.venv\\Scripts\\python serveur_declarations.py (transport stdio).
"""

import json
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import jours_ouvres_entre, lire_date, requete

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

serveur = MCPServer(
    name="e09-declarations",
    instructions=(
        "Déclarations de sinistre habitation fictives. Lecture seule. "
        "Les champs d'en-tête sont repris tels quels ; le texte complet fait foi."
    ),
)


@serveur.tool(annotations=LECTURE)
def lister_declarations() -> list[dict]:
    """Liste les déclarations : numéro de dossier, date de réception, contrat indiqué, nature déclarée."""
    return requete(
        "SELECT numero_dossier, date_reception, numero_contrat, declarant, nature_declaree "
        "FROM declarations ORDER BY numero_dossier"
    )


@serveur.tool(annotations=LECTURE)
def lire_declaration(numero_dossier: str) -> dict[str, Any]:
    """Renvoie les champs d'en-tête et le texte complet d'une déclaration (SIN-2026-xxxx)."""
    lignes = requete("SELECT * FROM declarations WHERE numero_dossier = ?", (numero_dossier,))
    if not lignes:
        raise ToolError(f"Dossier inconnu : {numero_dossier}")
    return lignes[0]


@serveur.tool(annotations=LECTURE)
def compter_jours_ouvres(date_debut: str, date_fin: str) -> dict[str, Any]:
    """Nombre de jours ouvrés entre deux dates (date_debut exclue, date_fin incluse).

    Jours ouvrés : hors samedi, dimanche et jours fériés de donnees/jours_feries.json.
    Dates au format AAAA-MM-JJ ou JJ/MM/AAAA.
    """
    try:
        debut, fin = lire_date(date_debut), lire_date(date_fin)
    except ValueError as e:
        raise ToolError(f"Date illisible : {e}") from e
    return {"date_debut": debut.isoformat(), "date_fin": fin.isoformat(), "jours_ouvres": jours_ouvres_entre(debut, fin)}


MODELE_EXTRACTION = {
    "numero_dossier": "SIN-2026-xxxx",
    "numero_contrat": "PH-HAB-xxxx ou null",
    "declarant": "texte",
    "date_sinistre": "AAAA-MM-JJ",
    "date_connaissance": "AAAA-MM-JJ",
    "date_reception": "AAAA-MM-JJ",
    "nature": "degat_des_eaux | bris_de_glace | vol_domicile | vol_hors_domicile | incendie",
    "montant_estime": 0,
    "pieces_fournies": ["texte"],
    "faits_utiles": ["phrase citée de la déclaration"],
}


@serveur.resource(
    "modele://extraction",
    name="modele_extraction",
    mime_type="application/json",
    description="Structure de sortie proposée pour l'agent d'extraction",
)
def modele_extraction() -> str:
    return json.dumps(MODELE_EXTRACTION, ensure_ascii=False, indent=2)


@serveur.prompt(description="Structurer une déclaration de sinistre")
def extraire_declaration(numero_dossier: str) -> str:
    return (
        f"Lire la déclaration {numero_dossier} avec lire_declaration. "
        "Remplir la structure de la ressource modele://extraction à partir du seul texte de la déclaration. "
        "Indiquer null pour toute information absente, sans la déduire. "
        "Citer entre guillemets chaque phrase de la déclaration retenue dans faits_utiles."
    )


if __name__ == "__main__":
    serveur.run("stdio")
