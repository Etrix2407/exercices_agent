"""Serveur MCP « e09-contrat » : rôle de couverture.

Conditions particulières, garanties et plafonds par contrat, conditions générales
(lecture d'un article, recherche par mots-clés).
Lancement : ..\\.venv\\Scripts\\python serveur_contrat.py (transport stdio).
"""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import mots, rechercher, requete

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
CIVILITES = {"m", "mme", "mlle", "monsieur", "madame", "mr"}

serveur = MCPServer(
    name="e09-contrat",
    instructions=(
        "Contrats fictifs d'assurance habitation. Lecture seule. Citer l'article des conditions générales "
        "ou la ligne des conditions particulières à l'appui de chaque affirmation."
    ),
)


@serveur.tool(annotations=LECTURE)
def rechercher_contrat(texte: str) -> dict[str, Any]:
    """Recherche un contrat par numéro, nom du titulaire ou fragment d'adresse du logement.

    Un contrat est retenu si tous les mots de la recherche (hors civilités et mots vides) y figurent.
    """
    cibles = [m for m in mots(texte) if m not in CIVILITES]
    if not cibles:
        raise ToolError("Recherche vide : indiquer un numéro, un nom ou un fragment d'adresse.")
    contrats = [
        {k: c[k] for k in ("numero_contrat", "titulaire", "logement", "date_effet", "formule", "options")}
        for c in requete("SELECT * FROM contrats ORDER BY numero_contrat")
        if set(cibles) <= set(mots(" ".join([c["numero_contrat"], c["titulaire"], c["logement"]])))
    ]
    return {"nombre": len(contrats), "contrats": contrats}


@serveur.tool(annotations=LECTURE)
def lire_conditions_particulieres(numero_contrat: str) -> dict[str, Any]:
    """Texte complet des conditions particulières d'un contrat (PH-HAB-xxxx)."""
    lignes = requete("SELECT numero_contrat, fichier, texte FROM contrats WHERE numero_contrat = ?", (numero_contrat,))
    if not lignes:
        raise ToolError(f"Contrat inconnu : {numero_contrat}")
    return lignes[0]


@serveur.tool(annotations=LECTURE)
def garanties_contrat(numero_contrat: str) -> dict[str, Any]:
    """Formule, options, date d'effet et tableau des garanties (statut, article, plafond en euros)."""
    contrat = requete(
        "SELECT numero_contrat, titulaire, logement, date_effet, formule, options FROM contrats WHERE numero_contrat = ?",
        (numero_contrat,),
    )
    if not contrat:
        raise ToolError(f"Contrat inconnu : {numero_contrat}")
    garanties = requete(
        "SELECT garantie, article_cg, statut, plafond FROM garanties WHERE numero_contrat = ?", (numero_contrat,)
    )
    return {**contrat[0], "garanties": garanties}


@serveur.tool(annotations=LECTURE)
def lire_article_cg(numero: int) -> dict[str, Any]:
    """Texte d'un article des conditions générales (1 à 25)."""
    lignes = requete("SELECT * FROM articles_cg WHERE numero = ?", (numero,))
    if not lignes:
        raise ToolError(f"Article inconnu : {numero}")
    return lignes[0]


@serveur.tool(annotations=LECTURE)
def rechercher_conditions_generales(mots_cles: str, maximum: int = 5) -> dict[str, Any]:
    """Articles des conditions générales classés par pertinence pour les mots-clés donnés."""
    articles = requete("SELECT numero, titre, texte FROM articles_cg")
    for a in articles:
        a["recherche"] = a["titre"] + " " + a["texte"]
    articles_trouves = [
        {
            "numero": r["numero"],
            "titre": r["titre"],
            "termes_trouves": r["termes_trouves"],
            "occurrences": r["occurrences"],
            "extrait": r["texte"][:300],
        }
        for r in rechercher(articles, mots_cles, champ="recherche", maximum=maximum)
    ]
    return {"nombre": len(articles_trouves), "articles": articles_trouves}


@serveur.resource(
    "cg://sommaire",
    name="sommaire_cg",
    mime_type="text/plain",
    description="Sommaire des conditions générales (numéro, titre, partie)",
)
def sommaire_cg() -> str:
    lignes = requete("SELECT numero, titre, titre_partie FROM articles_cg ORDER BY numero")
    return "\n".join(f"Article {l['numero']}. {l['titre']} ({l['titre_partie']})" for l in lignes)


@serveur.prompt(description="Confronter une déclaration structurée au contrat")
def verifier_couverture(numero_dossier: str, numero_contrat: str) -> str:
    return (
        f"Pour le dossier {numero_dossier} et le contrat {numero_contrat} : lire garanties_contrat, "
        "puis les articles des conditions générales utiles (ressource cg://sommaire, lire_article_cg, "
        "rechercher_conditions_generales). Produire la liste des garanties applicables, des exclusions examinées, "
        "du plafond, des pièces exigées et des points à vérifier, chacun avec la référence d'article. "
        "Ne pas conclure à un refus ni à un paiement : formuler une orientation proposée au gestionnaire."
    )


if __name__ == "__main__":
    serveur.run("stdio")
