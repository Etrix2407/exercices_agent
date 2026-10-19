"""Serveur MCP « e09-sorties » : fiches, brouillons de courrier et journal des échanges.

Aucun envoi : tout est écrit dans sorties/ (ou dans le dossier indiqué par E09_SORTIES).
Lancement : ..\\.venv\\Scripts\\python serveur_sorties.py (transport stdio).
"""

import json
import re
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import SORTIES

ECRITURE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
JOURNAL = SORTIES / "journal.jsonl"

serveur = MCPServer(
    name="e09-sorties",
    instructions=(
        "Écriture de brouillons uniquement (fiches, courriers) et journal des échanges entre agents. "
        "Aucun envoi."
    ),
)


def _dossier(numero_dossier: str) -> str:
    if not re.fullmatch(r"SIN-\d{4}-\d{4}", numero_dossier):
        raise ToolError(f"Numéro de dossier invalide : {numero_dossier}")
    return numero_dossier


def _ecrire(relatif: str, contenu: str) -> str:
    chemin = SORTIES / relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


@serveur.tool(annotations=ECRITURE)
def ecrire_fiche(numero_dossier: str, contenu_markdown: str) -> dict[str, Any]:
    """Écrit (ou remplace) la fiche de pré-instruction d'un dossier, en Markdown."""
    return {"ecrit": _ecrire(f"fiches/{_dossier(numero_dossier)}.md", contenu_markdown)}


@serveur.tool(annotations=ECRITURE)
def ecrire_brouillon_courrier(numero_dossier: str, destinataire: str, objet: str, corps: str) -> dict[str, Any]:
    """Écrit le brouillon de courrier à l'assuré. Le courrier n'est pas envoyé."""
    contenu = (
        f"BROUILLON, NON ENVOYÉ\nDossier : {_dossier(numero_dossier)}\n"
        f"À : {destinataire}\nObjet : {objet}\n\n{corps}\n"
    )
    return {"ecrit": _ecrire(f"courriers/{numero_dossier}.txt", contenu)}


@serveur.tool(annotations=ECRITURE)
def journaliser(agent: str, numero_dossier: str, evenement: str, detail: str = "") -> dict[str, Any]:
    """Ajoute une ligne au journal des échanges : agent émetteur, dossier, événement, détail."""
    SORTIES.mkdir(parents=True, exist_ok=True)
    ligne = {
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "dossier": _dossier(numero_dossier),
        "evenement": evenement,
        "detail": detail,
    }
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


@serveur.tool(annotations=LECTURE)
def lire_journal(numero_dossier: str | None = None) -> dict[str, Any]:
    """Lignes du journal, éventuellement filtrées par dossier."""
    lignes = []
    if JOURNAL.exists():
        lignes = [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    lignes = [l for l in lignes if numero_dossier in (None, l["dossier"])]
    return {"nombre": len(lignes), "lignes": lignes}


@serveur.tool(annotations=LECTURE)
def lister_sorties() -> dict[str, Any]:
    """Fichiers déjà écrits dans le dossier de sorties."""
    fichiers = []
    if SORTIES.exists():
        fichiers = sorted(p.relative_to(SORTIES).as_posix() for p in SORTIES.rglob("*") if p.is_file())
    return {"nombre": len(fichiers), "fichiers": fichiers}


@serveur.resource(
    "modele://fiche",
    name="modele_fiche",
    mime_type="text/markdown",
    description="Plan de la fiche de pré-instruction",
)
def modele_fiche() -> str:
    return (
        "# Fiche de pré-instruction : SIN-2026-xxxx\n\n"
        "## Informations extraites\n\n## Garanties applicables (avec article)\n\n"
        "## Franchise et plafond\n\n## Pièces manquantes\n\n## Orientation proposée et justification\n\n"
        "## Origine des éléments (agent, étape)\n"
    )


@serveur.prompt(description="Rédiger le courrier à l'assuré à partir de la synthèse de couverture")
def rediger_courrier(numero_dossier: str, synthese: str) -> str:
    return (
        f"À partir de la seule synthèse suivante pour le dossier {numero_dossier}, rédiger un courrier sobre "
        "à l'assuré (pièces à fournir, suite proposée, prochaines étapes) et l'écrire avec "
        "ecrire_brouillon_courrier. Ne mentionner aucune décision de refus ou de paiement.\n\n"
        "Synthèse :\n" + synthese
    )


if __name__ == "__main__":
    serveur.run("stdio")
