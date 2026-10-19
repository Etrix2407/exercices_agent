r"""Fonctions d'accès à parc.db et à la boîte mail, utilisées par serveur_mcp.py
et réutilisables dans une boucle d'agent écrite à la main.

Lecture : parc, contrats, contrôles, habilitations, factures, documents, mails.
Écriture : brouillons uniquement (table brouillons, dossier boite/outbox/).

Chemins : variables PARC_DB et PARC_BOITE, sinon parc.db et boite/ à côté de ce fichier.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import boite_kit

LIMITE_LIGNES = 200
TYPES_BROUILLON = ("statut_machine", "blocage_machine", "correction_facture", "relance",
                   "dossier_litige", "planning", "alerte", "autre")


class ErreurOutil(Exception):
    """Refus d'une opération, avec un message destiné à l'agent."""


def chemin_base() -> Path:
    return Path(os.environ.get("PARC_DB", Path(__file__).with_name("parc.db")))


def boite() -> boite_kit.BoiteDemandes:
    return boite_kit.BoiteDemandes(os.environ.get("PARC_BOITE", boite_kit.RACINE))


def _connexion(ecriture: bool = False) -> sqlite3.Connection:
    base = chemin_base()
    if not base.exists():
        raise FileNotFoundError(f"Base absente : {base}. Lancer init_donnees.py.")
    cx = sqlite3.connect(f"{base.resolve().as_uri()}?mode={'rw' if ecriture else 'ro'}", uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def _requete(sql: str, params: tuple = ()) -> list[dict]:
    with closing(_connexion()) as cx:
        return [dict(r) for r in cx.execute(sql, params).fetchmany(LIMITE_LIGNES)]


def _motif(valeur: str) -> str:
    """Fragment pour LIKE ... ESCAPE '!' : les jokers saisis (% et _) sont pris littéralement."""
    return "%" + valeur.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _filtres(sql: str, conditions: dict, ordre: str) -> list[dict]:
    """Ajoute les conditions non vides (colonne -> (opérateur, valeur)) à une requête."""
    params = []
    for colonne, (operateur, valeur) in conditions.items():
        if valeur not in (None, ""):
            if operateur == "LIKE":
                sql += f" AND {colonne} LIKE ? ESCAPE '!'"
                params.append(_motif(valeur))
            else:
                sql += f" AND {colonne} {operateur} ?"
                params.append(valeur)
    return _requete(f"{sql} ORDER BY {ordre}", tuple(params))


def _date(valeur: str | None, nom: str) -> None:
    """Refuse une date qui n'est pas au format AAAA-MM-JJ (les dates sont comparées comme du texte)."""
    if valeur in (None, ""):
        return
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
            raise ValueError
        date.fromisoformat(valeur)
    except ValueError:
        raise ErreurOutil(f"{nom} : date attendue au format AAAA-MM-JJ, reçu « {valeur} ».") from None


def _famille(famille: str | None) -> None:
    """Refuse un fragment de famille qui ne correspond à aucune machine (évite une liste vide trompeuse)."""
    if famille in (None, ""):
        return
    if not _requete("SELECT 1 FROM machines WHERE famille LIKE ? ESCAPE '!' LIMIT 1", (_motif(famille),)):
        familles = [r["famille"] for r in _requete("SELECT DISTINCT famille FROM machines ORDER BY famille")]
        raise ErreurOutil(f"Aucune famille ne contient « {famille} ». Familles : {', '.join(familles)}.")


# --- Schéma et requête libre ----------------------------------------------------


def schema() -> str:
    with closing(_connexion()) as cx:
        lignes = cx.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL "
                            "AND name != 'sqlite_sequence' ORDER BY name")
        return "\n\n".join(r[0] + ";" for r in lignes)


def requete_sql(sql: str) -> list[dict]:
    instruction = sql.strip().rstrip(";")
    if ";" in instruction or not re.match(r"(?is)^\s*(select|with)\b", instruction):
        raise ErreurOutil("Seule une instruction SELECT unique est acceptée.")
    try:
        return _requete(instruction)
    except sqlite3.Error as e:
        raise ErreurOutil(f"Erreur SQL : {e}") from e


# --- Parc et contrats --------------------------------------------------------------


def rechercher_machines(famille: str | None = None, agence: str | None = None, statut: str | None = None) -> list[dict]:
    _famille(famille)
    return _filtres("SELECT * FROM machines WHERE 1 = 1",
                    {"famille": ("LIKE", famille), "agence_code": ("=", agence), "statut_declare": ("=", statut)},
                    "reference_machine")


def fiche_machine(reference: str) -> dict:
    machine = _requete("SELECT * FROM machines WHERE reference_machine = ?", (reference,))
    if not machine:
        raise ErreurOutil(f"Machine inconnue : {reference}")
    m = machine[0]
    return {
        **m,
        "catalogue": (_requete("SELECT * FROM catalogue WHERE libelle = ?", (m["famille"],)) or [None])[0],
        "controle": (_requete("SELECT * FROM controles WHERE reference_machine = ?", (reference,)) or [None])[0],
        "contrats": _requete("SELECT * FROM contrats WHERE reference_machine = ? ORDER BY date_debut", (reference,)),
        "documents": _requete("SELECT reference, type, date_document, contrat_id FROM documents "
                              "WHERE reference_machine = ? ORDER BY date_document", (reference,)),
    }


def machines_libres(famille: str, date_debut: str, date_fin: str, agence: str | None = None) -> list[dict]:
    """Machines d'une famille sans contrat qui chevauche la période (dates AAAA-MM-JJ).
    Renvoie aussi le statut déclaré, le contrôle de retour et l'échéance réglementaire,
    sans les interpréter."""
    _famille(famille)
    _date(date_debut, "date_debut")
    _date(date_fin, "date_fin")
    sql = (
        "SELECT m.reference_machine, m.agence_code, m.statut_declare, m.date_dernier_retour, "
        "m.controle_retour_fait, m.prochaine_echeance_controle FROM machines m "
        "WHERE m.famille LIKE ? ESCAPE '!' AND NOT EXISTS (SELECT 1 FROM contrats c WHERE c.reference_machine = m.reference_machine "
        "AND c.date_debut <= ? AND COALESCE(c.date_retour_reel, c.date_fin_prevue) >= ?)"
    )
    params: list = [_motif(famille), date_fin, date_debut]
    if agence:
        sql += " AND m.agence_code = ?"
        params.append(agence)
    return _requete(sql + " ORDER BY m.agence_code, m.reference_machine", tuple(params))


def rechercher_contrats(client: str | None = None, statut: str | None = None,
                        reference_machine: str | None = None) -> list[dict]:
    return _filtres("SELECT * FROM contrats WHERE 1 = 1",
                    {"client": ("LIKE", client), "statut_contrat": ("=", statut),
                     "reference_machine": ("=", reference_machine)}, "contrat_id")


def contrat(contrat_id: str) -> dict:
    c = _requete("SELECT * FROM contrats WHERE contrat_id = ?", (contrat_id,))
    if not c:
        raise ErreurOutil(f"Contrat inconnu : {contrat_id}")
    return {
        **c[0],
        "machine": _requete("SELECT reference_machine, famille, agence_code, statut_declare FROM machines "
                            "WHERE reference_machine = ?", (c[0]["reference_machine"],))[0],
        "factures": _requete("SELECT * FROM factures WHERE contrat_id = ?", (contrat_id,)),
        "documents": _requete("SELECT reference, type, date_document FROM documents WHERE contrat_id = ? "
                              "ORDER BY date_document", (contrat_id,)),
    }


def demandes_non_servies(famille: str | None = None) -> list[dict]:
    return _filtres("SELECT * FROM demandes_non_servies WHERE 1 = 1", {"famille_demandee": ("LIKE", famille)},
                    "date_demande")


def echeances_controles(avant_le: str | None = None) -> list[dict]:
    _date(avant_le, "avant_le")
    return _filtres("SELECT * FROM controles WHERE 1 = 1", {"date_echeance": ("<=", avant_le)}, "date_echeance")


def habilitations(agence: str | None = None, expire_avant: str | None = None) -> list[dict]:
    _date(expire_avant, "expire_avant")
    return _filtres("SELECT * FROM habilitations WHERE 1 = 1",
                    {"agence_code": ("=", agence), "date_expiration": ("<=", expire_avant)}, "date_expiration")


def factures(client: str | None = None, statut: str | None = None) -> list[dict]:
    return _filtres("SELECT * FROM factures WHERE 1 = 1", {"client": ("LIKE", client), "statut": ("LIKE", statut)},
                    "date_echeance")


# --- Documents ----------------------------------------------------------------------


def rechercher_documents(type_document: str | None = None, texte: str | None = None,
                         contrat_id: str | None = None) -> list[dict]:
    """Bons de livraison et de reprise, comptes rendus de retour, fiches de sécurité (extrait de 160 caractères)."""
    return _filtres(
        "SELECT reference, type, date_document, contrat_id, reference_machine, substr(texte, 1, 160) AS extrait "
        "FROM documents WHERE 1 = 1",
        {"type": ("=", type_document), "texte": ("LIKE", texte), "contrat_id": ("=", contrat_id)},
        "date_document",
    )


def lire_document(reference: str) -> dict:
    d = _requete("SELECT * FROM documents WHERE reference = ?", (reference,))
    if not d:
        raise ErreurOutil(f"Document inconnu : {reference}")
    return d[0]


# --- Mails ----------------------------------------------------------------------------


def lister_mails(chercher: str | None = None, dossier: str = "inbox") -> list[dict]:
    try:
        return boite().lister(dossier, chercher=chercher)
    except ValueError as e:
        raise ErreurOutil(f"{e}. Valeurs : inbox, outbox, archive.") from e


def lire_mail(identifiant: str) -> dict:
    try:
        return boite().lire(identifiant)
    except KeyError as e:
        raise ErreurOutil(str(e)) from e


# --- Brouillons -------------------------------------------------------------------------


def _source_connue(source: str) -> bool:
    """Une source citée doit exister : document, mail, contrat, facture ou machine."""
    tables = [("documents", "reference"), ("contrats", "contrat_id"), ("factures", "facture_id"),
              ("machines", "reference_machine")]
    for table, colonne in tables:
        if _requete(f"SELECT 1 FROM {table} WHERE {colonne} = ?", (source,)):
            return True
    try:
        boite()._chemin(source)
        return True
    except KeyError:
        return False


def creer_brouillon(type_brouillon: str, cible: str, contenu: str, justification: str,
                    sources: list[str] | None = None) -> dict:
    """Enregistre une proposition de modification, soumise à validation humaine.
    Aucune donnée de référence n'est modifiée."""
    if type_brouillon not in TYPES_BROUILLON:
        raise ErreurOutil(f"Type invalide : {type_brouillon}. Valeurs : {', '.join(TYPES_BROUILLON)}.")
    if not (cible.strip() and contenu.strip() and justification.strip()):
        raise ErreurOutil("cible, contenu et justification sont obligatoires.")
    sources = sources or []
    inconnues = [s for s in sources if not _source_connue(s)]
    if inconnues:
        raise ErreurOutil(f"Sources introuvables : {', '.join(inconnues)}")
    with closing(_connexion(ecriture=True)) as cx:
        identifiant = cx.execute(
            "INSERT INTO brouillons (type, cible, contenu, justification, sources) VALUES (?, ?, ?, ?, ?)",
            (type_brouillon, cible.strip(), contenu.strip(), justification.strip(), json.dumps(sources)),
        ).lastrowid
        cx.commit()
    return {"id": identifiant, "statut": "brouillon", "type": type_brouillon, "cible": cible}


def lister_brouillons(type_brouillon: str | None = None) -> list[dict]:
    lignes = _filtres("SELECT * FROM brouillons WHERE 1 = 1", {"type": ("=", type_brouillon)}, "id")
    for l in lignes:
        l["sources"] = json.loads(l["sources"])
    return lignes


def brouillon_mail(a: str, sujet: str, corps: str, service: str = "planification",
                   en_reponse_a: str | None = None) -> dict:
    try:
        identifiant = boite().preparer_brouillon(a, sujet, corps, service, en_reponse_a)
    except (ValueError, KeyError) as e:
        raise ErreurOutil(str(e)) from e
    return {"id": identifiant, "statut": "brouillon", "dossier": "outbox"}
