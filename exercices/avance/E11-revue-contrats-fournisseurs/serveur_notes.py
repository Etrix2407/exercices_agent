"""Serveur MCP « e11-notes » : notes de revue, synthèses et remarques du contradicteur (brouillons).

Les notes écrites portent la mention « brouillon, non validé par un juriste ». Rien n'est transmis.
Sorties dans sorties/ (ou dans le dossier indiqué par E11_SORTIES).
Lancement : ..\\.venv\\Scripts\\python serveur_notes.py (transport stdio).
"""

import json
import re
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from commun import SORTIES, requete

ECRITURE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
MENTION = "**Statut : brouillon, non validé par un juriste.**\n\n"
REMARQUES = SORTIES / "remarques.jsonl"

serveur = MCPServer(
    name="e11-notes",
    instructions="Écriture de brouillons de notes et de synthèses, registre des remarques du contradicteur. Aucune transmission.",
)


def _contrat(reference: str) -> str:
    lignes = requete("SELECT id FROM contrats WHERE id = ? OR numero = ?", (reference, reference))
    if not lignes:
        raise ToolError(f"Contrat inconnu : {reference}")
    return lignes[0]["id"]


def _ecrire(relatif: str, contenu: str) -> str:
    chemin = SORTIES / relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


@serveur.tool(annotations=ECRITURE)
def ecrire_note_revue(contrat: str, contenu_markdown: str) -> dict[str, Any]:
    """Écrit (ou remplace) la note de revue d'un contrat, précédée de la mention de brouillon."""
    return {"ecrit": _ecrire(f"notes/note-{_contrat(contrat)}.md", MENTION + contenu_markdown)}


@serveur.tool(annotations=ECRITURE)
def ecrire_synthese_acheteur(contrat: str, contenu_markdown: str) -> dict[str, Any]:
    """Écrit (ou remplace) la synthèse d'une page destinée à l'acheteur, précédée de la mention de brouillon."""
    return {"ecrit": _ecrire(f"syntheses/synthese-{_contrat(contrat)}.md", MENTION + contenu_markdown)}


@serveur.tool(annotations=ECRITURE)
def enregistrer_remarque(contrat: str, agent: str, remarque: str, clause: str = "", traitement: str = "") -> dict[str, Any]:
    """Ajoute une remarque (par exemple du contradicteur) et son traitement éventuel au registre."""
    SORTIES.mkdir(parents=True, exist_ok=True)
    existantes = _remarques()
    ligne = {"id": f"R{len(existantes) + 1:03d}", "horodatage": datetime.now().isoformat(timespec="seconds"),
             "contrat": _contrat(contrat), "agent": agent, "clause": clause, "remarque": remarque,
             "traitement": traitement}
    with REMARQUES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def _remarques() -> list[dict]:
    if not REMARQUES.exists():
        return []
    return [json.loads(l) for l in REMARQUES.read_text(encoding="utf-8").splitlines() if l.strip()]


@serveur.tool(annotations=LECTURE)
def lister_remarques(contrat: str | None = None) -> dict[str, Any]:
    """Remarques enregistrées, éventuellement filtrées par contrat."""
    cible = _contrat(contrat) if contrat else None
    lignes = [l for l in _remarques() if cible in (None, l["contrat"])]
    return {"nombre": len(lignes), "remarques": lignes}


@serveur.tool(annotations=ECRITURE)
def traiter_remarque(id_remarque: str, traitement: str, agent: str) -> dict[str, Any]:
    """Renseigne le traitement d'une remarque existante (correction apportée ou maintien motivé)."""
    lignes = _remarques()
    for l in lignes:
        if l["id"] == id_remarque:
            l["traitement"] = traitement
            l["traite_par"] = agent
            l["traite_le"] = datetime.now().isoformat(timespec="seconds")
            temporaire = REMARQUES.with_suffix(".tmp")
            temporaire.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lignes), encoding="utf-8")
            temporaire.replace(REMARQUES)
            return l
    raise ToolError(f"Remarque inconnue : {id_remarque}")


@serveur.tool(annotations=LECTURE)
def lister_notes() -> dict[str, Any]:
    """Notes disponibles : notes de test fournies et brouillons déjà écrits."""
    brouillons = sorted(p.relative_to(SORTIES).as_posix() for p in SORTIES.rglob("*.md")) if SORTIES.exists() else []
    return {"notes_test": [l["fichier"] for l in requete("SELECT fichier FROM notes_test ORDER BY fichier")],
            "brouillons": brouillons}


@serveur.tool(annotations=LECTURE)
def lire_note(nom: str) -> dict[str, Any]:
    """Texte d'une note : nom d'une note de test ou chemin relatif d'un brouillon (notes/note-contrat-01.md)."""
    test = requete("SELECT fichier, texte FROM notes_test WHERE fichier = ?", (nom,))
    if test:
        return {"nom": nom, "origine": "note_test", "texte": test[0]["texte"]}
    if not re.fullmatch(r"(notes|syntheses)/[\w.-]+\.md", nom):
        raise ToolError(f"Note inconnue : {nom}")
    chemin = SORTIES / nom
    if not chemin.exists():
        raise ToolError(f"Note inconnue : {nom}")
    return {"nom": nom, "origine": "brouillon", "texte": chemin.read_text(encoding="utf-8")}


@serveur.resource(
    "modele://note-revue",
    name="modele_note_revue",
    mime_type="text/markdown",
    description="Plan de la note de revue",
)
def modele_note() -> str:
    return (
        "# Note de revue : CTR-2026-xxxx (fournisseur)\n\n"
        "## Tableau des clauses\n\n"
        "| Clause | Art. | Classement | Citation exacte | Référence grille | Reformulation proposée |\n"
        "|---|---|---|---|---|---|\n\n"
        "## Remarques du contradicteur et traitement\n"
    )


@serveur.prompt(description="Relire une note de revue en contradicteur")
def contredire_note(contrat: str, nom_note: str) -> str:
    return (
        f"Lire la note {nom_note} (lire_note) portant sur le contrat {contrat}. "
        "Vérifier toutes ses citations avec verifier_citations_note (serveur e11-contrats), "
        "puis chaque classement au regard du passage cité et de la grille. "
        "Enregistrer chaque affirmation non étayée par le texte du contrat avec enregistrer_remarque."
    )


if __name__ == "__main__":
    serveur.run("stdio")
