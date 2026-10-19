"""Serveur MCP « e10-redaction » : brouillons de relance, livret d'accueil, tableau d'avancement.

Aucun envoi : les relances sont des fichiers .eml dans sorties/brouillons/, enregistrés
dans l'état partagé avec le statut « brouillon ».
Lancement : ..\\.venv\\Scripts\\python serveur_redaction.py (transport stdio).
"""

import re
from datetime import datetime
from email import policy
from email.message import EmailMessage
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import SORTIES, etat_verrouille

ECRITURE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
EXPEDITEUR = "Préparation des arrivées <arrivees@vandamme.example>"

serveur = MCPServer(
    name="e10-redaction",
    instructions="Écriture de brouillons uniquement (relances, livrets, tableau d'avancement). Aucun envoi.",
)


def _id(id_arrivee: str) -> str:
    if not re.fullmatch(r"ARR-\d{4}-\d{3}", id_arrivee):
        raise ToolError(f"Identifiant d'arrivée invalide : {id_arrivee}")
    return id_arrivee


def _ecrire(relatif: str, contenu: str | bytes) -> str:
    chemin = SORTIES / relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenu, bytes):
        chemin.write_bytes(contenu)
    else:
        chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


@serveur.tool(annotations=ECRITURE)
def ecrire_brouillon_relance(id_arrivee: str, id_tache: str, destinataire: str, sujet: str, corps: str, agent: str) -> dict[str, Any]:
    """Écrit un brouillon de relance (.eml non envoyé) et l'enregistre dans l'état partagé.

    Refuse une deuxième relance pour la même tâche tant que la précédente est au statut brouillon.
    """
    with etat_verrouille() as etat:
        if _id(id_arrivee) not in etat["arrivees"]:
            raise ToolError(f"Arrivée absente de l'état : {id_arrivee}")
        if id_tache not in {t["id"] for t in etat["arrivees"][id_arrivee]["taches"]}:
            raise ToolError(f"Tâche inconnue : {id_tache}")
        for r in etat["relances"]:
            if r["id_arrivee"] == id_arrivee and r["id_tache"] == id_tache and r["statut"] == "brouillon":
                raise ToolError(f"Relance {r['id']} déjà en brouillon pour {id_arrivee} {id_tache}, en attente de validation RH.")
        numero = len(etat["relances"]) + 1
        msg = EmailMessage(policy=policy.default)
        msg["From"] = EXPEDITEUR
        msg["To"] = destinataire
        msg["Subject"] = sujet
        msg["X-Statut"] = "brouillon"
        msg.set_content(corps)
        chemin = _ecrire(f"brouillons/REL-{numero:04d}.eml", bytes(msg))
        relance = {"id": f"REL-{numero:04d}", "id_arrivee": id_arrivee, "id_tache": id_tache,
                   "destinataire": destinataire, "statut": "brouillon", "fichier": chemin, "agent": agent,
                   "cree_le": datetime.now().isoformat(timespec="seconds")}
        etat["relances"].append(relance)
    return relance


@serveur.tool(annotations=ECRITURE)
def ecrire_livret(id_arrivee: str, contenu_markdown: str) -> dict[str, Any]:
    """Écrit (ou remplace) le livret d'accueil d'une arrivée, en Markdown."""
    return {"ecrit": _ecrire(f"livrets/{_id(id_arrivee)}.md", contenu_markdown)}


@serveur.tool(annotations=ECRITURE)
def ecrire_tableau_avancement(contenu_markdown: str) -> dict[str, Any]:
    """Écrit le tableau d'avancement de l'exécution (un fichier par date et heure)."""
    nom = datetime.now().strftime("avancement-%Y%m%d-%H%M%S.md")
    return {"ecrit": _ecrire(f"avancement/{nom}", contenu_markdown)}


@serveur.tool(annotations=LECTURE)
def lister_sorties() -> dict[str, Any]:
    """Fichiers déjà écrits dans le dossier de sorties."""
    fichiers = []
    if SORTIES.exists():
        fichiers = sorted(p.relative_to(SORTIES).as_posix() for p in SORTIES.rglob("*") if p.is_file())
    return {"nombre": len(fichiers), "fichiers": fichiers}


@serveur.resource(
    "modele://livret",
    name="modele_livret",
    mime_type="text/markdown",
    description="Plan du livret d'accueil",
)
def modele_livret() -> str:
    return (
        "# Livret d'accueil : prénom nom\n\n## Première journée\n\n## Programme de la première semaine\n\n"
        "## Contacts\n\n## Informations pratiques du site\n\n## Matériel et accès prévus\n"
    )


@serveur.prompt(description="Rédiger le livret d'accueil d'une arrivée")
def rediger_livret(id_arrivee: str) -> str:
    return (
        f"Rédiger le livret d'accueil de {id_arrivee} selon le plan de la ressource modele://livret, "
        "avec les seules informations de la fiche, du site, des paramètres et de l'état partagé. "
        "Omettre une rubrique plutôt que de la compléter par supposition. Écrire avec ecrire_livret."
    )


if __name__ == "__main__":
    serveur.run("stdio")
