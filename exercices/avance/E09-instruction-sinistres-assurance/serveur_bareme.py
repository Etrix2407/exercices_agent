"""Serveur MCP « e09-bareme » : calculs de franchise et de montant indicatif (art. 13 et 14).

Les montants sont calculés en code, jamais par le modèle.
Lancement : ..\\.venv\\Scripts\\python serveur_bareme.py (transport stdio).
"""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import requete

CALCUL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
COLONNES = ("nature", "option", "type_franchise", "valeur", "minimum", "maximum", "article", "regle")

serveur = MCPServer(
    name="e09-bareme",
    instructions=(
        "Barème de franchise fictif. Natures : degat_des_eaux, bris_de_glace, vol_domicile, vol_hors_domicile, "
        "incendie. Options : bris_de_glace_renforce, vol_hors_domicile. Ne passer que les options qui figurent "
        "aux conditions particulières du contrat."
    ),
)


def _franchise(nature: str, montant_estime: float, options: list[str]) -> dict[str, Any]:
    lignes = requete("SELECT * FROM bareme WHERE nature = ?", (nature,))
    if not lignes:
        natures = sorted({l["nature"] for l in requete("SELECT nature FROM bareme")})
        raise ToolError(f"Nature inconnue : {nature}. Natures du barème : {', '.join(natures)}")
    if montant_estime < 0:
        raise ToolError("Le montant estimé ne peut pas être négatif.")
    codes = sorted({l["option"] for l in requete("SELECT option FROM bareme WHERE option IS NOT NULL")})
    inconnues = [o for o in options if o not in codes]
    if inconnues:
        raise ToolError(
            f"Option(s) inconnue(s) : {', '.join(inconnues)}. Codes d'option du barème : {', '.join(codes)}."
        )
    # Une ligne propre à une option souscrite prime sur la ligne sans option.
    retenue = next((l for l in lignes if l["option"] and l["option"] in options), None)
    retenue = retenue or next((l for l in lignes if not l["option"]), None)
    if retenue is None:
        return {
            "applicable": False,
            "nature": nature,
            "motif": "aucune ligne du barème pour cette nature avec les options indiquées",
            "lignes_existantes": [{"option": l["option"], "regle": l["regle"]} for l in lignes],
        }
    if retenue["type_franchise"] == "pourcentage":
        brut = montant_estime * retenue["valeur"] / 100
        franchise = brut
        if retenue["minimum"] is not None:
            franchise = max(franchise, retenue["minimum"])
        if retenue["maximum"] is not None:
            franchise = min(franchise, retenue["maximum"])
        detail = (
            f"{retenue['valeur']:g} % de {montant_estime:g} = {brut:g}, "
            f"borné entre {retenue['minimum']:g} et {retenue['maximum']:g}"
        )
    else:
        franchise = retenue["valeur"]
        detail = "montant fixe"
    return {
        "applicable": True,
        "nature": nature,
        "option_appliquee": retenue["option"],
        "franchise": round(franchise, 2),
        "detail": detail,
        "regle": retenue["regle"],
        "article": retenue["article"],
    }


@serveur.tool(annotations=CALCUL)
def lire_bareme() -> list[dict]:
    """Toutes les lignes du barème de franchise."""
    return requete("SELECT * FROM bareme")


@serveur.tool(annotations=CALCUL)
def calculer_franchise(nature: str, montant_estime: float, options: list[str] | None = None) -> dict[str, Any]:
    """Franchise selon le barème (art. 14 §1) pour une nature, un montant estimé et les options souscrites.

    options : codes d'option du barème (bris_de_glace_renforce, vol_hors_domicile) ; un code inconnu est refusé.
    """
    return _franchise(nature, montant_estime, options or [])


@serveur.tool(annotations=CALCUL)
def calculer_montant_indicatif(
    nature: str, montant_estime: float, plafond: float | None, options: list[str] | None = None
) -> dict[str, Any]:
    """Montant indicatif net (art. 14 §2) : montant limité au plafond, moins la franchise, sans valeur négative."""
    if plafond is None or plafond <= 0:
        raise ToolError("Plafond absent ou nul : garantie à vérifier aux conditions particulières.")
    f = _franchise(nature, montant_estime, options or [])
    if not f["applicable"]:
        return f
    retenu = min(montant_estime, plafond)
    return {
        **f,
        "montant_estime": montant_estime,
        "plafond": plafond,
        "montant_retenu": round(retenu, 2),
        "plafond_atteint": montant_estime > plafond,
        "montant_indicatif_net": round(max(retenu - f["franchise"], 0), 2),
        "articles": ["art. 13", "art. 14 §2"],
    }


def _csv(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, float):
        return f"{valeur:g}"
    return f'"{valeur}"' if "," in valeur else valeur


@serveur.resource("bareme://franchises", name="bareme", mime_type="text/csv", description="Barème de franchise (CSV)")
def bareme_csv() -> str:
    lignes = requete("SELECT * FROM bareme")
    return "\n".join([",".join(COLONNES)] + [",".join(_csv(l[k]) for k in COLONNES) for l in lignes])


@serveur.prompt(description="Calculer franchise et montant indicatif d'un dossier")
def calculer_montants(nature: str, montant_estime: str, plafond: str, options: str = "") -> str:
    return (
        f"Appeler calculer_montant_indicatif avec nature={nature}, montant_estime={montant_estime}, "
        f"plafond={plafond}, options=[{options}]. Reporter les montants renvoyés sans les recalculer "
        "et citer les articles indiqués dans la réponse."
    )


if __name__ == "__main__":
    serveur.run("stdio")
