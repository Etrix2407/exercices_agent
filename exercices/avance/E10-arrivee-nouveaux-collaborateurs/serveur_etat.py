"""Serveur MCP « e10-etat » : état partagé de coordination entre agents.

Fichier etat/etat_partage.json (ou variable E10_ETAT) : tâches par service, demandes générées,
propositions de bureau, relances en brouillon, journal. Écritures sous verrou.
Lancement : ..\\.venv\\Scripts\\python serveur_etat.py (transport stdio).
"""

import json
from datetime import date, datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import etat_verrouille, fiches, lire_csv, lire_etat

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
ECRITURE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
SERVICES = ("rh", "informatique", "services_generaux", "manager")
STATUTS = ("a_faire", "en_cours", "fait")

serveur = MCPServer(
    name="e10-etat",
    instructions=(
        "État partagé de la préparation des arrivées. Lire avant d'écrire. "
        "Chaque écriture indique l'agent qui en est l'auteur."
    ),
)


def _date_reference(date_reference: str | None, etat: dict) -> date:
    try:
        return date.fromisoformat(date_reference or etat["date_execution"])
    except ValueError as e:
        raise ToolError(f"Date illisible (AAAA-MM-JJ attendu) : {date_reference}") from e


def _arrivee(etat: dict, id_arrivee: str) -> dict[str, Any]:
    if id_arrivee not in etat["arrivees"]:
        raise ToolError(f"Arrivée absente de l'état : {id_arrivee}")
    return etat["arrivees"][id_arrivee]


def _horodatage() -> str:
    return datetime.now().isoformat(timespec="seconds")


@serveur.tool(annotations=LECTURE)
def lire_etat_arrivee(id_arrivee: str) -> dict[str, Any]:
    """Tâches, demandes, proposition de bureau et relances d'une arrivée."""
    etat = lire_etat()
    return {
        "id_arrivee": id_arrivee,
        "date_execution": etat["date_execution"],
        "taches": _arrivee(etat, id_arrivee)["taches"],
        "demandes": [d for d in etat["demandes"] if d["id_arrivee"] == id_arrivee],
        "propositions_bureau": [p for p in etat["propositions_bureau"] if p["id_arrivee"] == id_arrivee],
        "relances": [r for r in etat["relances"] if r["id_arrivee"] == id_arrivee],
    }


@serveur.tool(annotations=LECTURE)
def taches_en_retard(date_reference: str | None = None) -> dict[str, Any]:
    """Tâches non faites dont l'échéance est strictement antérieure à la date de référence.

    Date de référence par défaut : date_execution de l'état.
    """
    etat = lire_etat()
    ref = _date_reference(date_reference, etat)
    taches = [
        {"id_arrivee": ida, **t, "jours_de_retard": (ref - date.fromisoformat(t["echeance"])).days}
        for ida, a in etat["arrivees"].items()
        for t in a["taches"]
        if t["statut"] != "fait" and date.fromisoformat(t["echeance"]) < ref
    ]
    return {"date_reference": ref.isoformat(), "nombre": len(taches), "taches": taches}


@serveur.tool(annotations=LECTURE)
def tableau_avancement(date_reference: str | None = None) -> list[dict]:
    """Par arrivée : nombre de tâches par statut, tâches en retard, demandes et relances enregistrées."""
    etat = lire_etat()
    ref = _date_reference(date_reference, etat)
    lignes = []
    for ida, a in etat["arrivees"].items():
        compte = {s: sum(t["statut"] == s for t in a["taches"]) for s in STATUTS}
        retard = [t["id"] for t in a["taches"] if t["statut"] != "fait" and date.fromisoformat(t["echeance"]) < ref]
        lignes.append({
            "id_arrivee": ida, **compte, "en_retard": retard,
            "demandes": sum(d["id_arrivee"] == ida for d in etat["demandes"]),
            "relances": sum(r["id_arrivee"] == ida for r in etat["relances"]),
        })
    return lignes


@serveur.tool(annotations=ECRITURE)
def enregistrer_demande(
    id_arrivee: str, service: str, objet: str, echeance: str, agent: str, code_acces: str | None = None
) -> dict[str, Any]:
    """Enregistre une demande adressée à un service. Refuse un doublon (même arrivée, service, objet ou code).

    echeance au format AAAA-MM-JJ. Le champ dans_referentiel indique si code_acces figure au référentiel
    pour le métier de l'arrivée ; un code hors référentiel n'est accepté que pour le service manager.
    """
    if service not in SERVICES:
        raise ToolError(f"Service inconnu : {service}. Services : {', '.join(SERVICES)}")
    try:
        date.fromisoformat(echeance)
    except ValueError as e:
        raise ToolError(f"Échéance illisible (AAAA-MM-JJ attendu) : {echeance}") from e
    fiche = fiches().get(id_arrivee)
    if fiche is None:
        raise ToolError(f"Arrivée inconnue : {id_arrivee}")
    codes = {l["code_acces"] for l in lire_csv("referentiel_metier_acces.csv") if l["metier"] in ("TOUS", fiche["metier"])}
    if code_acces and code_acces not in codes and service != "manager":
        raise ToolError(
            f"Code {code_acces} absent du référentiel pour le métier {fiche['metier']} : "
            "demande à adresser au service manager pour décision."
        )
    with etat_verrouille() as etat:
        for d in etat["demandes"]:
            if d["id_arrivee"] == id_arrivee and d["service"] == service and (
                d["objet"] == objet or (code_acces and d["code_acces"] == code_acces)
            ):
                raise ToolError(f"Demande déjà enregistrée : {d['id']}")
        demande = {
            "id": f"DEM-{len(etat['demandes']) + 1:04d}",
            "id_arrivee": id_arrivee,
            "service": service,
            "objet": objet,
            "code_acces": code_acces,
            "dans_referentiel": code_acces in codes if code_acces else None,
            "echeance": echeance,
            "agent": agent,
            "cree_le": _horodatage(),
        }
        etat["demandes"].append(demande)
    return demande


@serveur.tool(annotations=ECRITURE)
def mettre_a_jour_tache(id_arrivee: str, id_tache: str, statut: str, agent: str, date_reponse: str | None = None) -> dict[str, Any]:
    """Change le statut d'une tâche (a_faire, en_cours, fait) et sa date de réponse éventuelle."""
    if statut not in STATUTS:
        raise ToolError(f"Statut inconnu : {statut}. Statuts : {', '.join(STATUTS)}")
    with etat_verrouille() as etat:
        for t in _arrivee(etat, id_arrivee)["taches"]:
            if t["id"] == id_tache:
                t["statut"], t["date_reponse"] = statut, date_reponse
                etat["journal"].append({"horodatage": _horodatage(), "agent": agent, "id_arrivee": id_arrivee,
                                        "evenement": f"tâche {id_tache} : {statut}", "detail": ""})
                return {"id_arrivee": id_arrivee, **t}
    raise ToolError(f"Tâche inconnue : {id_tache}")


@serveur.tool(annotations=ECRITURE)
def proposer_bureau(id_arrivee: str, identifiant_bureau: str, agent: str) -> dict[str, Any]:
    """Réserve un bureau à titre de proposition. Refuse un bureau occupé ou déjà proposé à une autre arrivée."""
    fiche = fiches().get(id_arrivee)
    if fiche is None:
        raise ToolError(f"Arrivée inconnue : {id_arrivee}")
    bureau = next((b for b in lire_csv("bureaux_places.csv") if b["identifiant"] == identifiant_bureau), None)
    if bureau is None:
        raise ToolError(f"Bureau inconnu : {identifiant_bureau}")
    if bureau["site"] != fiche["site"]:
        raise ToolError(f"Le bureau {identifiant_bureau} est sur le site {bureau['site']}, l'arrivée sur {fiche['site']}.")
    if bureau["statut"] != "libre":
        raise ToolError(f"Bureau {identifiant_bureau} : statut {bureau['statut']}.")
    with etat_verrouille() as etat:
        for p in etat["propositions_bureau"]:
            if p["identifiant_bureau"] == identifiant_bureau and p["id_arrivee"] != id_arrivee:
                raise ToolError(f"Bureau déjà proposé pour {p['id_arrivee']}.")
        etat["propositions_bureau"] = [p for p in etat["propositions_bureau"] if p["id_arrivee"] != id_arrivee]
        proposition = {"id_arrivee": id_arrivee, "identifiant_bureau": identifiant_bureau,
                       "zone": bureau["zone"], "agent": agent, "cree_le": _horodatage()}
        etat["propositions_bureau"].append(proposition)
    return proposition


@serveur.tool(annotations=ECRITURE)
def journaliser(agent: str, id_arrivee: str, evenement: str, detail: str = "") -> dict[str, Any]:
    """Ajoute une ligne au journal partagé."""
    ligne = {"horodatage": _horodatage(), "agent": agent, "id_arrivee": id_arrivee, "evenement": evenement, "detail": detail}
    with etat_verrouille() as etat:
        etat["journal"].append(ligne)
    return ligne


@serveur.resource(
    "etat://partage",
    name="etat_partage",
    mime_type="application/json",
    description="Contenu complet du fichier d'état partagé",
)
def etat_partage() -> str:
    return json.dumps(lire_etat(), ensure_ascii=False, indent=2)


@serveur.prompt(description="Faire le point d'avancement et proposer les relances")
def point_avancement(date_reference: str = "") -> str:
    quand = f"à la date {date_reference}" if date_reference else "à la date d'exécution de l'état"
    return (
        f"Faire le point {quand} : appeler tableau_avancement et taches_en_retard. "
        "Pour chaque tâche en retard sans relance déjà enregistrée, préparer un brouillon de relance "
        "avec ecrire_brouillon_relance (serveur e10-redaction). Ne rien envoyer."
    )


if __name__ == "__main__":
    serveur.run("stdio")
