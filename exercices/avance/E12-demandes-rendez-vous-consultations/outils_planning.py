r"""Fonctions d'accès à planning.db, partagées par le serveur MCP local et par le
relais d'outils personnalisés de lancer_session.py.

Lecture : demandes, référentiel, créneaux libres, propositions.
Écriture : uniquement des brouillons dans la table propositions.
Aucune fonction ne confirme un rendez-vous ni ne modifie le planning.

Chemin de la base : variable PLANNING_DB, sinon planning.db à côté de ce fichier.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

PRIORITES = ("urgent", "prioritaire", "standard", "incertaine")


class ErreurOutil(Exception):
    """Refus d'une opération, avec un message destiné à l'agent."""


def chemin_base() -> Path:
    return Path(os.environ.get("PLANNING_DB", Path(__file__).with_name("planning.db")))


def _connexion(ecriture: bool = False) -> sqlite3.Connection:
    base = chemin_base()
    if not base.exists():
        raise FileNotFoundError(f"Base absente : {base}. Lancer init_donnees.py.")
    mode = "rw" if ecriture else "ro"
    cx = sqlite3.connect(f"{base.resolve().as_uri()}?mode={mode}", uri=True)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    return cx


def _requete(sql: str, params: tuple = ()) -> list[dict]:
    with closing(_connexion()) as cx:
        return [dict(r) for r in cx.execute(sql, params)]


# --- Lecture -------------------------------------------------------------------

# Le NISS fictif n'est pas utile au tri : il n'est pas renvoyé à l'agent.
COLONNES_DEMANDE = (
    "id_demande, date_depot, canal, identifiant_patient, nom_fictif, specialite_demandee, motif, "
    "CASE courrier_adressage WHEN 1 THEN 'oui' ELSE 'non' END AS courrier_adressage"
)


def lister_demandes(specialite: str | None = None, sans_proposition: bool = False) -> list[dict]:
    """Demandes du lot, filtrables par spécialité saisie et par absence de proposition."""
    sql = f"SELECT {COLONNES_DEMANDE} FROM demandes d WHERE 1 = 1"
    params: list = []
    if specialite:
        sql += " AND d.specialite_demandee = ?"
        params.append(specialite)
    if sans_proposition:
        sql += " AND NOT EXISTS (SELECT 1 FROM propositions p WHERE p.id_demande = d.id_demande)"
    return _requete(sql + " ORDER BY id_demande", tuple(params))


def lire_demande(id_demande: str) -> dict:
    lignes = _requete(f"SELECT {COLONNES_DEMANDE} FROM demandes WHERE id_demande = ?", (id_demande,))
    if not lignes:
        raise ErreurOutil(f"Demande inconnue : {id_demande}")
    return lignes[0]


def referentiel(specialite: str | None = None) -> list[dict]:
    """Spécialités : courrier d'adressage requis et délais cibles (jours) par priorité."""
    sql = (
        "SELECT nom, CASE courrier_requis WHEN 1 THEN 'oui' ELSE 'non' END AS courrier_requis, "
        "delai_urgent_j, delai_prioritaire_j, delai_standard_j FROM specialites"
    )
    if specialite:
        return _requete(sql + " WHERE nom = ?", (specialite,))
    return _requete(sql + " ORDER BY nom")


def _verifier_date(valeur: str | None, nom: str) -> None:
    """Refuse une date hors format AAAA-MM-JJ : les dates sont comparées comme du texte."""
    if valeur in (None, ""):
        return
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
            raise ValueError
        date.fromisoformat(valeur)
    except ValueError:
        raise ErreurOutil(f"{nom} : date attendue au format AAAA-MM-JJ, reçu « {valeur} ».") from None


def lister_creneaux_libres(specialite: str, date_min: str | None = None, date_max: str | None = None) -> list[dict]:
    """Créneaux libres d'une spécialité, sans ceux déjà retenus dans une proposition.
    Refus : spécialité absente du référentiel (une liste vide signifie alors « aucun créneau »), date mal formée."""
    if not referentiel(specialite):
        noms = ", ".join(r["nom"] for r in referentiel())
        raise ErreurOutil(f"Spécialité inconnue : {specialite}. Noms exacts : {noms}.")
    _verifier_date(date_min, "date_min")
    _verifier_date(date_max, "date_max")
    sql = (
        "SELECT c.id_creneau, c.specialite, c.date, c.heure, c.duree_minutes FROM creneaux c "
        "WHERE c.specialite = ? AND c.statut = 'libre' "
        "AND NOT EXISTS (SELECT 1 FROM propositions p WHERE p.id_creneau = c.id_creneau)"
    )
    params: list = [specialite]
    if date_min:
        sql += " AND c.date >= ?"
        params.append(date_min)
    if date_max:
        sql += " AND c.date <= ?"
        params.append(date_max)
    return _requete(sql + " ORDER BY c.date, c.heure", tuple(params))


def lister_propositions() -> list[dict]:
    return _requete(
        "SELECT p.*, c.date AS date_creneau, c.heure AS heure_creneau FROM propositions p "
        "LEFT JOIN creneaux c ON c.id_creneau = p.id_creneau ORDER BY p.id_demande"
    )


def bilan() -> dict:
    """Compteurs du lot : demandes, propositions avec ou sans créneau, à revoir, non traitées."""
    with closing(_connexion()) as cx:
        total = cx.execute("SELECT COUNT(*) FROM demandes").fetchone()[0]
        traitees = cx.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        avec = cx.execute("SELECT COUNT(*) FROM propositions WHERE id_creneau IS NOT NULL").fetchone()[0]
        a_revoir = cx.execute("SELECT COUNT(*) FROM propositions WHERE a_revoir = 1").fetchone()[0]
    return {
        "demandes": total,
        "traitees": traitees,
        "avec_creneau": avec,
        "sans_creneau": traitees - avec,
        "a_revoir": a_revoir,
        "non_traitees": total - traitees,
    }


# --- Écriture de brouillons ----------------------------------------------------


def proposer_creneau(
    id_demande: str,
    specialite: str,
    priorite: str,
    justification: str,
    id_creneau: str | None = None,
    pieces_manquantes: str = "",
    motif_sans_creneau: str = "",
    a_revoir: bool = False,
) -> dict:
    """Enregistre ou remplace la proposition (brouillon) d'une demande.

    Refus : demande ou spécialité inconnue, priorité hors liste, créneau d'une autre
    spécialité, déjà retenu ou antérieur au dépôt, créneau pour une priorité urgente,
    créneau alors que le courrier d'adressage requis est absent, absence de motif
    quand aucun créneau n'est proposé. Une priorité « incertaine » force « à revoir ».
    """
    if priorite not in PRIORITES:
        raise ErreurOutil(f"Priorité invalide : {priorite}. Valeurs : {', '.join(PRIORITES)}.")
    if not justification.strip():
        raise ErreurOutil("Justification obligatoire.")
    demande = lire_demande(id_demande)
    ref = referentiel(specialite)
    if not ref:
        raise ErreurOutil(f"Spécialité inconnue : {specialite}")
    ref = ref[0]
    a_revoir = bool(a_revoir) or priorite == "incertaine"
    avertissements: list[str] = []

    if id_creneau:
        lignes = _requete("SELECT * FROM creneaux WHERE id_creneau = ?", (id_creneau,))
        if not lignes:
            raise ErreurOutil(f"Créneau inconnu : {id_creneau}")
        creneau = lignes[0]
        if creneau["specialite"] != specialite:
            raise ErreurOutil(f"Le créneau {id_creneau} relève de {creneau['specialite']}, pas de {specialite}.")
        if creneau["statut"] != "libre":
            raise ErreurOutil(f"Le créneau {id_creneau} n'est pas libre.")
        if creneau["date"] < demande["date_depot"]:
            raise ErreurOutil(f"Le créneau {id_creneau} est antérieur à la date de dépôt.")
        if priorite == "urgent":
            raise ErreurOutil("Priorité urgente : orientation vers les urgences, aucun créneau programmé.")
        if ref["courrier_requis"] == "oui" and demande["courrier_adressage"] == "non":
            raise ErreurOutil(
                f"{specialite} exige un courrier d'adressage, absent pour {id_demande} : "
                "aucun créneau réservable tant que le courrier n'est pas reçu."
            )
        deja = _requete(
            "SELECT id_demande FROM propositions WHERE id_creneau = ? AND id_demande != ?", (id_creneau, id_demande)
        )
        if deja:
            raise ErreurOutil(f"Le créneau {id_creneau} est déjà proposé pour {deja[0]['id_demande']}.")
        if priorite in ("prioritaire", "standard"):
            delai = ref[f"delai_{priorite}_j"]
            limite = date.fromisoformat(demande["date_depot"]) + timedelta(days=delai)
            if date.fromisoformat(creneau["date"]) > limite:
                avertissements.append(f"Créneau au-delà du délai cible ({delai} jours, limite {limite.isoformat()}).")
    elif not motif_sans_creneau.strip():
        raise ErreurOutil("Sans créneau, indiquer motif_sans_creneau.")

    with closing(_connexion(ecriture=True)) as cx:
        cx.execute(
            "INSERT OR REPLACE INTO propositions (id_demande, specialite_retenue, priorite, justification, "
            "pieces_manquantes, id_creneau, motif_sans_creneau, a_revoir) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id_demande, specialite, priorite, justification.strip(), pieces_manquantes.strip(), id_creneau or None,
             motif_sans_creneau.strip(), int(a_revoir)),
        )
        cx.commit()
    return {"id_demande": id_demande, "statut": "brouillon", "id_creneau": id_creneau, "a_revoir": a_revoir,
            "avertissements": avertissements}


def retirer_proposition(id_demande: str) -> dict:
    """Supprime le brouillon d'une demande (libère le créneau retenu)."""
    with closing(_connexion(ecriture=True)) as cx:
        n = cx.execute("DELETE FROM propositions WHERE id_demande = ?", (id_demande,)).rowcount
        cx.commit()
    if not n:
        raise ErreurOutil(f"Aucune proposition pour {id_demande}.")
    return {"id_demande": id_demande, "retire": True}


def exporter_propositions(chemin: Path | str) -> Path:
    """Écrit un CSV avec une ligne par demande du lot, traitée ou non."""
    chemin = Path(chemin)
    lignes = _requete(
        "SELECT d.id_demande, COALESCE(p.specialite_retenue, d.specialite_demandee, '') AS specialite, "
        "COALESCE(p.priorite, '') AS priorite, COALESCE(p.justification, '') AS justification, "
        "COALESCE(p.pieces_manquantes, '') AS pieces_manquantes, COALESCE(p.id_creneau, '') AS id_creneau, "
        "COALESCE(c.date || ' ' || c.heure, '') AS date_creneau, "
        "CASE WHEN p.id_demande IS NULL THEN 'non traitée' ELSE p.motif_sans_creneau END AS motif_sans_creneau, "
        "CASE WHEN p.a_revoir = 1 THEN 'à revoir par le secrétariat' ELSE '' END AS a_revoir, "
        "COALESCE(p.statut, '') AS statut FROM demandes d "
        "LEFT JOIN propositions p ON p.id_demande = d.id_demande "
        "LEFT JOIN creneaux c ON c.id_creneau = p.id_creneau ORDER BY d.id_demande"
    )
    with chemin.open("w", encoding="utf-8", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=list(lignes[0].keys()))
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
    return chemin


# --- Définitions d'outils pour un agent (format Managed Agents, type custom) ----

_PROPOSER_SCHEMA = {
    "type": "object",
    "properties": {
        "id_demande": {"type": "string"},
        "specialite": {"type": "string", "description": "Spécialité retenue, nom exact du référentiel"},
        "priorite": {"type": "string", "enum": list(PRIORITES)},
        "justification": {"type": "string", "description": "Raison de la priorité, en une ou deux phrases"},
        "id_creneau": {"type": "string", "description": "Créneau proposé ; omis si aucun créneau"},
        "pieces_manquantes": {"type": "string"},
        "motif_sans_creneau": {"type": "string", "description": "Obligatoire si id_creneau est omis"},
        "a_revoir": {"type": "boolean", "description": "Demande à revoir par le secrétariat"},
    },
    "required": ["id_demande", "specialite", "priorite", "justification"],
}

OUTILS_SESSION = [
    {
        "type": "custom",
        "name": "lister_creneaux_libres",
        "description": "Liste les créneaux libres d'une spécialité dans la base locale du centre, "
        "sans ceux déjà retenus. Dates au format AAAA-MM-JJ.",
        "input_schema": {
            "type": "object",
            "properties": {
                "specialite": {"type": "string", "description": "Nom exact du référentiel"},
                "date_min": {"type": "string", "description": "AAAA-MM-JJ"},
                "date_max": {"type": "string", "description": "AAAA-MM-JJ"},
            },
            "required": ["specialite"],
        },
    },
    {
        "type": "custom",
        "name": "proposer_creneau",
        "description": "Enregistre la proposition d'une demande en brouillon dans la base locale. "
        "Ne confirme aucun rendez-vous. Renvoie une erreur explicite si une règle du référentiel est violée.",
        "input_schema": _PROPOSER_SCHEMA,
    },
    {
        "type": "custom",
        "name": "retirer_proposition",
        "description": "Supprime le brouillon d'une demande pour le refaire.",
        "input_schema": {"type": "object", "properties": {"id_demande": {"type": "string"}}, "required": ["id_demande"]},
    },
    {
        "type": "custom",
        "name": "bilan_propositions",
        "description": "Compteurs du lot : demandes, traitées, avec ou sans créneau, à revoir, non traitées.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_TABLE = {
    "lister_creneaux_libres": lister_creneaux_libres,
    "proposer_creneau": proposer_creneau,
    "retirer_proposition": retirer_proposition,
    "bilan_propositions": bilan,
}


def executer_outil(nom: str, arguments: dict) -> tuple[str, bool]:
    """Exécute un outil du relais. Renvoie (texte JSON, est_erreur)."""
    if nom not in _TABLE:
        return f"Outil inconnu : {nom}", True
    try:
        resultat = _TABLE[nom](**(arguments or {}))
    except (ErreurOutil, TypeError, ValueError) as e:
        return str(e), True
    return json.dumps(resultat, ensure_ascii=False), False
