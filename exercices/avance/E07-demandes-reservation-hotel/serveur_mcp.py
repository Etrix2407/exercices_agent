"""Serveur MCP du kit E07 : demandes de groupe, planning de l'hôtel, devis, brouillons.

Expose :
- outils de lecture : demandes reçues, disponibilités des chambres et des salles ;
- calcul du devis d'après la grille (code, pas de calcul par le modèle) ;
- outils d'écriture limités : fiche des besoins, brouillon de réponse avec devis joint,
  pré-réservation au statut « à valider » (le planning n'est pas modifié) ;
- ressource : grille tarifaire ;
- prompt : traitement d'une demande.
Aucun outil d'envoi.

Lancement (transport stdio) :
    ..\\.venv\\Scripts\\python serveur_mcp.py
Variables : KIT_BOITE, KIT_BASE.
"""

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

import planning
from boite_kit import BoiteKit

ICI = Path(__file__).resolve().parent
CHEMIN_BOITE = Path(os.environ.get("KIT_BOITE", ICI / "boite"))
ADRESSE = "Service commercial Le Grand Cèdre <reservations@grand-cedre.example>"

LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
ECRITURE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)

TypeChambre = Literal["simple", "double", "twin", "suite"]
NombreChambres = Annotated[int, Field(ge=0, description="Nombre de chambres de ce type")]


class LigneSalle(BaseModel):
    salle: str = Field(description="Cèdre, Érable ou Lys")
    jours: int = Field(1, ge=1, description="Nombre de jours d'occupation")


class LigneRepas(BaseModel):
    prestation: Literal["dejeuner_buffet", "diner", "pause_cafe"]
    couverts: int = Field(ge=1, description="Nombre de couverts ou de personnes")
    nombre: int = Field(1, ge=1, description="Nombre de repas ou de pauses")


class SalleDatee(BaseModel):
    salle: str
    date: str = Field(description="AAAA-MM-JJ")


serveur = MCPServer(
    name="hotel-reservations-groupe",
    instructions=(
        "Boîte de test du service commercial d'un hôtel fictif, planning des chambres et des salles, "
        "grille tarifaire. Le planning est en lecture seule ; une pré-réservation reste à valider par une "
        "personne. Les réponses sont des brouillons ; aucun envoi possible."
    ),
)


def boite() -> BoiteKit:
    return BoiteKit(CHEMIN_BOITE, ADRESSE)


def liste(cle: str, elements: list[dict]) -> dict:
    """Résultat de liste avec son nombre : une liste vide reste visible pour le modèle ({"nombre": 0, ...})."""
    return {"nombre": len(elements), cle: elements}


def erreur_outil(fonction, *args, **kwargs):
    """Convertit les erreurs de validation métier en erreurs d'outil lisibles par l'agent."""
    try:
        return fonction(*args, **kwargs)
    except (ValueError, KeyError, FileNotFoundError) as e:
        raise ToolError(str(e)) from e


# --- Demandes -----------------------------------------------------------------


@serveur.tool(annotations=LECTURE)
def lister_demandes(non_lues: bool = False) -> dict:
    """Liste les demandes reçues, de la plus ancienne à la plus récente."""
    return liste("demandes", boite().lister("inbox", non_lus=non_lues))


@serveur.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True))
def lire_demande(identifiant: str, marquer_lue: bool = False) -> dict:
    """Lit une demande complète (ex. demande_01_mariage)."""
    return erreur_outil(boite().lire, identifiant, marquer_lu=marquer_lue)


# --- Planning et devis ----------------------------------------------------------


@serveur.tool(annotations=LECTURE)
def disponibilites_chambres(arrivee: str, depart: str) -> dict:
    """Chambres libres par type, nuit par nuit, de arrivee (incluse) à depart (exclue). Dates AAAA-MM-JJ."""
    return erreur_outil(planning.disponibilites_chambres, arrivee, depart)


@serveur.tool(annotations=LECTURE)
def disponibilites_salles(date_debut: str, date_fin: str) -> list[dict]:
    """Salles libres et occupées pour chaque jour de date_debut à date_fin (incluses). Dates AAAA-MM-JJ."""
    return erreur_outil(planning.disponibilites_salles, date_debut, date_fin)


@serveur.tool(annotations=LECTURE)
def calculer_devis(
    arrivee: str,
    depart: str,
    chambres: dict[TypeChambre, NombreChambres],
    salles: list[LigneSalle] | None = None,
    repas: list[LigneRepas] | None = None,
) -> dict:
    """Calcule un devis indicatif d'après la grille : chambres par saison, petit-déjeuner par personne logée
    et par nuit (ajouté d'office), salles à la journée, repas. Renvoie les lignes, le total et un tableau Markdown."""
    return erreur_outil(
        planning.calculer_devis, arrivee, depart, dict(chambres),
        [s.model_dump() for s in salles or []], [r.model_dump() for r in repas or []],
    )


# --- Écritures limitées -------------------------------------------------------


@serveur.tool(annotations=ECRITURE)
def enregistrer_fiche_besoins(identifiant_demande: str, fiche: dict) -> dict:
    """Enregistre la fiche structurée (JSON) des besoins extraits d'une demande dans boite/fiches/."""
    erreur_outil(boite().lire, identifiant_demande)  # vérifie que la demande existe
    dossier = CHEMIN_BOITE / "fiches"
    dossier.mkdir(exist_ok=True)
    chemin = dossier / f"{identifiant_demande}.json"
    chemin.write_text(json.dumps(fiche, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"fiche": chemin.name}


@serveur.tool(annotations=ECRITURE)
def enregistrer_brouillon(
    identifiant_demande: str, corps: str, sujet: str | None = None, devis_markdown: str | None = None
) -> dict:
    """Dépose un brouillon de réponse à la demande (destinataire : son expéditeur), avec le devis joint
    en devis.md si fourni. Rien n'est envoyé."""
    pieces = {"devis.md": devis_markdown} if devis_markdown else None
    return erreur_outil(boite().enregistrer_brouillon, identifiant_demande, corps, sujet, pieces)


@serveur.tool(annotations=LECTURE)
def lister_brouillons() -> dict:
    """Liste les brouillons déposés (id, demande d'origine, destinataire, sujet, pièces jointes)."""
    return liste("brouillons", boite().lister_brouillons())


@serveur.tool(annotations=ECRITURE)
def pre_reserver(
    identifiant_demande: str,
    arrivee: str,
    depart: str,
    chambres: dict[TypeChambre, NombreChambres],
    salles: list[SalleDatee] | None = None,
) -> dict:
    """Enregistre une pré-réservation au statut a_valider, refusée si les chambres ou salles demandées ne sont
    pas libres dans le planning. Le planning n'est pas modifié : seule une personne peut l'y inscrire
    (planning.py valider)."""
    erreur_outil(boite().lire, identifiant_demande)  # vérifie que la demande existe
    return erreur_outil(
        planning.pre_reserver, identifiant_demande, arrivee, depart, dict(chambres),
        [s.model_dump() for s in salles or []],
    )


@serveur.tool(annotations=LECTURE)
def lister_pre_reservations(statut: Literal["a_valider", "validee"] | None = None) -> dict:
    """Pré-réservations enregistrées, filtrables par statut."""
    return liste("pre_reservations", erreur_outil(planning.pre_reservations, statut))


# --- Ressource ----------------------------------------------------------------


@serveur.resource("hotel://grille-tarifaire", name="grille_tarifaire", mime_type="text/markdown",
                  description="Grille tarifaire : saisons, chambres, salles, repas, règles de calcul")
def grille_tarifaire() -> str:
    return (ICI / "donnees" / "grille_tarifaire.md").read_text(encoding="utf-8")


# --- Prompt -------------------------------------------------------------------


@serveur.prompt(description="Traiter une demande de réservation de groupe")
def traiter_demande(identifiant: str) -> str:
    return (
        f"Lire la demande {identifiant} avec lire_demande. Extraire les besoins (dates, effectifs, chambres par "
        "type, salle, repas) et les enregistrer avec enregistrer_fiche_besoins. Si une information nécessaire "
        "manque, préparer un brouillon de demande de précisions sans devis. Sinon, vérifier "
        "disponibilites_chambres et disponibilites_salles, calculer le devis avec calculer_devis et déposer un "
        "brouillon avec le devis joint. Si les disponibilités ne suffisent pas, proposer d'autres dates "
        "vérifiées dans le planning. Aucune remise ; les prix viennent uniquement de la grille."
    )


if __name__ == "__main__":
    serveur.run("stdio")
