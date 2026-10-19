"""Serveur MCP « e11-contrats » : lecture des contrats, recherche de passages, vérification de citation.

Lecture seule. Utilisé par l'agent d'extraction et par l'agent contradicteur.
Lancement : ..\\.venv\\Scripts\\python serveur_contrats.py (transport stdio).
"""

from collections import defaultdict
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import extraire_citations, mots, phrases, racine, requete, verifier

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

serveur = MCPServer(
    name="e11-contrats",
    instructions=(
        "Contrats fournisseurs fictifs, découpés en sections (une par article). Lecture seule. "
        "Un contrat se désigne par son identifiant (contrat-01) ou son numéro (CTR-2026-0412). "
        "Toute citation reprise dans une note doit passer verifier_citation."
    ),
)


def _contrat(reference: str) -> dict[str, Any]:
    lignes = requete("SELECT id, numero, fichier, fournisseur FROM contrats WHERE id = ? OR numero = ?",
                     (reference, reference))
    if not lignes:
        raise ToolError(f"Contrat inconnu : {reference}")
    return lignes[0]


def _sections(contrat_id: str) -> list[dict]:
    return requete("SELECT ordre, article, titre, texte FROM sections WHERE contrat_id = ? ORDER BY ordre", (contrat_id,))


@serveur.tool(annotations=LECTURE)
def lister_contrats() -> list[dict]:
    """Contrats disponibles : identifiant, numéro, fichier, fournisseur."""
    return requete("SELECT id, numero, fichier, fournisseur FROM contrats ORDER BY id")


@serveur.tool(annotations=LECTURE)
def lire_contrat(contrat: str) -> dict[str, Any]:
    """Texte complet d'un contrat, en Markdown."""
    c = _contrat(contrat)
    return {**c, "texte": requete("SELECT texte FROM contrats WHERE id = ?", (c["id"],))[0]["texte"]}


@serveur.tool(annotations=LECTURE)
def sommaire_contrat(contrat: str) -> list[dict]:
    """Liste des sections d'un contrat : ordre, numéro d'article (null pour Parties, Préambule...), titre."""
    return [{k: s[k] for k in ("ordre", "article", "titre")} for s in _sections(_contrat(contrat)["id"])]


@serveur.tool(annotations=LECTURE)
def lire_article(contrat: str, numero_article: int) -> dict[str, Any]:
    """Texte d'un article d'un contrat."""
    c = _contrat(contrat)
    lignes = requete("SELECT article, titre, texte FROM sections WHERE contrat_id = ? AND article = ?",
                     (c["id"], numero_article))
    if not lignes:
        raise ToolError(f"Article {numero_article} absent du contrat {c['id']}")
    return {"contrat": c["id"], **lignes[0]}


@serveur.tool(annotations=LECTURE)
def rechercher_passages(contrat: str, mots_cles: str, maximum: int = 5) -> dict[str, Any]:
    """Sections d'un contrat classées par pertinence (index par mots), avec la phrase la plus proche de la requête."""
    c = _contrat(contrat)
    termes = {racine(m) for m in mots(mots_cles)}
    if not termes:
        raise ToolError("Aucun mot-clé exploitable.")
    scores: dict[int, dict] = defaultdict(lambda: {"termes": set(), "occurrences": 0})
    for t in termes:
        for ligne in requete("SELECT ordre, occurrences FROM index_mots WHERE contrat_id = ? AND mot LIKE ?",
                             (c["id"], t + "%")):
            scores[ligne["ordre"]]["termes"].add(t)
            scores[ligne["ordre"]]["occurrences"] += ligne["occurrences"]
    classement = sorted(scores.items(), key=lambda x: (-len(x[1]["termes"]), -x[1]["occurrences"]))[:maximum]
    sections = {s["ordre"]: s for s in _sections(c["id"])}
    resultats = []
    for ordre, score in classement:
        s = sections[ordre]
        meilleure = max(phrases(s["texte"]), key=lambda p: sum(racine(m) in termes for m in mots(p)))
        resultats.append({"article": s["article"], "titre": s["titre"], "termes_trouves": len(score["termes"]),
                          "occurrences": score["occurrences"], "phrase": meilleure})
    return {"contrat": c["id"], "nombre": len(resultats), "passages": resultats}


@serveur.tool(annotations=LECTURE)
def verifier_citation(contrat: str, citation: str) -> dict[str, Any]:
    """Vérifie qu'une citation figure mot pour mot dans le contrat (seuls les écarts d'espaces sont tolérés).

    Renvoie exacte, l'article trouvé, sinon exacte_hors_typographie (apostrophes, guillemets)
    et le passage le plus proche.
    """
    return verifier(citation, _sections(_contrat(contrat)["id"]))


@serveur.tool(annotations=LECTURE)
def verifier_citations_note(contrat: str, texte_note: str) -> dict[str, Any]:
    """Extrait toutes les citations entre guillemets d'une note et vérifie chacune contre le contrat."""
    sections = _sections(_contrat(contrat)["id"])
    resultats = [verifier(c, sections) for c in extraire_citations(texte_note)]
    return {
        "contrat": contrat,
        "citations": len(resultats),
        "exactes": sum(r["exacte"] for r in resultats),
        "introuvables": [r for r in resultats if not r["exacte"]],
    }


@serveur.resource(
    "contrats://liste",
    name="liste_contrats",
    mime_type="text/plain",
    description="Contrats disponibles (identifiant, numéro, fournisseur, nombre d'articles)",
)
def liste_contrats() -> str:
    lignes = requete(
        "SELECT c.id, c.numero, c.fournisseur, COUNT(s.article) AS articles FROM contrats c "
        "JOIN sections s ON s.contrat_id = c.id GROUP BY c.id ORDER BY c.id"
    )
    return "\n".join(f"{l['id']} | {l['numero']} | {l['fournisseur']} | {l['articles']} articles" for l in lignes)


@serveur.prompt(description="Repérer dans un contrat les passages correspondant aux clauses de la grille")
def extraire_clauses(contrat: str) -> str:
    return (
        f"Pour le contrat {contrat} : lire sommaire_contrat, puis, pour chaque clause G1 à G10 de la grille, "
        "trouver le passage correspondant (lire_article, rechercher_passages). Rendre pour chaque clause : "
        "code, article, citation exacte ou « absente ». Passer chaque citation à verifier_citation avant de la rendre."
    )


if __name__ == "__main__":
    serveur.run("stdio")
