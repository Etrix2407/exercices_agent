"""Serveur MCP « e10-referentiel » : fiches d'arrivée, référentiel métier vers accès, sites, bureaux.

Lecture seule. Utilisé par les agents RH, informatique et logistique, et par l'orchestrateur.
Lancement : ..\\.venv\\Scripts\\python serveur_referentiel.py (transport stdio).
"""

import json
from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import fiches, lire_csv, lire_json, retrancher_jours_ouvres

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

serveur = MCPServer(
    name="e10-referentiel",
    instructions=(
        "Référentiels fictifs d'un groupe d'ingénierie : fiches d'arrivée, accès par métier, sites, bureaux. "
        "Lecture seule. Les fichiers sont relus à chaque appel."
    ),
)


def _fiche(id_arrivee: str) -> dict[str, Any]:
    toutes = fiches()
    if id_arrivee not in toutes:
        raise ToolError(f"Arrivée inconnue : {id_arrivee}")
    return toutes[id_arrivee]


@serveur.tool(annotations=LECTURE)
def lister_arrivees() -> list[dict]:
    """Arrivées connues : identifiant, nom, poste, métier, site, date d'arrivée."""
    return [
        {k: f.get(k) for k in ("id", "prenom", "nom", "poste", "metier", "site", "date_arrivee")}
        for f in fiches().values()
    ]


@serveur.tool(annotations=LECTURE)
def lire_fiche(id_arrivee: str) -> dict[str, Any]:
    """Fiche d'arrivée complète (ARR-2026-xxx)."""
    return _fiche(id_arrivee)


@serveur.tool(annotations=LECTURE)
def lister_metiers() -> list[str]:
    """Codes métier présents dans le référentiel (TOUS désigne le socle commun)."""
    return sorted({l["metier"] for l in lire_csv("referentiel_metier_acces.csv")})


@serveur.tool(annotations=LECTURE)
def acces_metier(metier: str) -> dict[str, Any]:
    """Lignes du référentiel pour un métier : socle commun (TOUS) et accès propres au métier."""
    metier = metier.strip().upper()
    lignes = lire_csv("referentiel_metier_acces.csv")
    propres = [l for l in lignes if l["metier"] == metier]
    return {
        "metier": metier,
        "present_dans_referentiel": bool(propres),
        "socle": [l for l in lignes if l["metier"] == "TOUS"],
        "specifiques": propres,
    }


@serveur.tool(annotations=LECTURE)
def infos_site(code_site: str) -> dict[str, Any]:
    """Adresse, accueil, horaires, restauration et contact RH d'un site (BRU, OST, COR, LAN, PIE)."""
    for s in lire_csv("sites.csv"):
        if s["code"] == code_site:
            return s
    raise ToolError(f"Site inconnu : {code_site}")


@serveur.tool(annotations=LECTURE)
def bureaux_site(code_site: str, zone: str | None = None) -> dict[str, Any]:
    """Bureaux et postes d'un site avec leur statut initial (fichier bureaux_places.csv)."""
    bureaux = [
        b for b in lire_csv("bureaux_places.csv")
        if b["site"] == code_site and zone in (None, b["zone"])
    ]
    return {"code_site": code_site, "zone": zone, "nombre": len(bureaux), "bureaux": bureaux}


@serveur.tool(annotations=LECTURE)
def calculer_echeances(date_arrivee: str) -> dict[str, Any]:
    """Échéance de chaque service : date d'arrivée moins le délai en jours ouvrés de parametres.json."""
    try:
        arrivee = date.fromisoformat(date_arrivee)
    except ValueError as e:
        raise ToolError(f"Date illisible (AAAA-MM-JJ attendu) : {date_arrivee}") from e
    delais = lire_json("parametres.json")["delais_jours_ouvres_avant_arrivee"]
    return {
        "date_arrivee": date_arrivee,
        "echeances": {
            service: {"delai_jours_ouvres": n, "echeance": retrancher_jours_ouvres(arrivee, n).isoformat()}
            for service, n in delais.items()
        },
    }


@serveur.resource(
    "parametres://arrivees",
    name="parametres",
    mime_type="application/json",
    description="Date d'exécution, délais par service et programme type de la première semaine",
)
def parametres() -> str:
    return json.dumps(lire_json("parametres.json"), ensure_ascii=False, indent=2)


@serveur.prompt(description="Préparer les demandes d'un service pour une arrivée")
def preparer_demandes(id_arrivee: str, service: str) -> str:
    return (
        f"Pour l'arrivée {id_arrivee} et le service {service} : lire la fiche avec lire_fiche, "
        "puis les référentiels utiles (acces_metier, bureaux_site, infos_site) et calculer_echeances. "
        "Lister chaque demande avec sa source dans le référentiel et son échéance, "
        "puis l'enregistrer avec enregistrer_demande (serveur e10-etat). "
        "Signaler à part toute demande qui ne provient pas du référentiel."
    )


if __name__ == "__main__":
    serveur.run("stdio")
