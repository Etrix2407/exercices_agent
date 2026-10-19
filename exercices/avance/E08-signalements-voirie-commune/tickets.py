"""Outil de tickets local des services techniques et référentiel des voies (base voirie.db).

Fonctions utilisées par serveur_mcp.py :
    rechercher_voie, chercher_tickets_ouverts, lire_ticket, creer_ticket, ajouter_commentaire, alerter_accueil
Aucune fonction de clôture ni de suppression.

Ligne de commande (consultation par une personne) :
    ..\\.venv\\Scripts\\python tickets.py lister [--tous]
    ..\\.venv\\Scripts\\python tickets.py voir TK-2026-0411
    ..\\.venv\\Scripts\\python tickets.py alertes
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

CHEMIN_BASE = Path(os.environ.get("KIT_BASE", Path(__file__).resolve().parent / "voirie.db"))
SERVICES = ("voirie", "eclairage", "proprete", "espaces_verts")
STATUTS_OUVERTS = ("ouvert", "en_cours")


def connexion(ecriture: bool = False) -> sqlite3.Connection:
    if not CHEMIN_BASE.exists():
        raise FileNotFoundError(f"Base absente : {CHEMIN_BASE}. Lancer init_donnees.py.")
    mode = "rw" if ecriture else "ro"
    cx = sqlite3.connect(f"{CHEMIN_BASE.resolve().as_uri()}?mode={mode}", uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, apostrophes et tirets remplacés par des espaces."""
    texte = "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn").lower()
    texte = re.sub(r"[’'\-.,]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


# --- Référentiel --------------------------------------------------------------


def rechercher_voie(texte: str) -> list[dict]:
    """Entrées du référentiel dont le nom ou une variante figure dans le texte, ou le contient.

    Un point de repère renvoie aussi sa voie de rattachement.
    """
    cible = normaliser(texte)
    if not cible:
        return []
    resultats = []
    with closing(connexion()) as cx:
        for v in cx.execute("SELECT * FROM voies"):
            formes = [v["nom_normalise"], *v["alias"].split("|")]
            formes_norm = [normaliser(f) for f in formes if f]
            if any(f in cible for f in formes_norm):
                score = 2  # le texte cite la voie ou le repère
            elif any(cible in f for f in formes_norm):
                score = 1  # le texte est un fragment du nom
            else:
                continue
            entree = {"nom_normalise": v["nom_normalise"], "type": v["type"], "correspondance": score}
            if v["repere"]:
                entree["voie_rattachee"] = v["repere"]
            resultats.append(entree)
    return sorted(resultats, key=lambda e: (-e["correspondance"], e["nom_normalise"]))


def lister_voies() -> list[dict]:
    with closing(connexion()) as cx:
        return [dict(r) for r in cx.execute("SELECT * FROM voies ORDER BY type = 'repere', nom_normalise")]


# --- Tickets ------------------------------------------------------------------


def _ticket(cx: sqlite3.Connection, ticket_id: str) -> dict:
    ligne = cx.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id.strip().upper(),)).fetchone()
    if not ligne:
        raise KeyError(f"Ticket inconnu : {ticket_id}")
    t = dict(ligne)
    t["adresse_a_preciser"], t["urgent"] = bool(t["adresse_a_preciser"]), bool(t["urgent"])
    return t


def chercher_tickets_ouverts(service: str | None = None, adresse: str | None = None, texte: str | None = None) -> list[dict]:
    """Tickets aux statuts ouvert ou en_cours, filtrés par service, fragment d'adresse ou de description."""
    with closing(connexion()) as cx:
        sql = "SELECT t.*, (SELECT COUNT(*) FROM commentaires c WHERE c.ticket_id = t.id) AS commentaires FROM tickets t WHERE statut IN (?, ?)"
        params: list = list(STATUTS_OUVERTS)
        if service:
            sql += " AND service = ?"
            params.append(service)
        lignes = [dict(r) for r in cx.execute(sql + " ORDER BY date_ouverture", params)]
    if adresse:
        lignes = [l for l in lignes if normaliser(adresse) in normaliser(l["adresse"])]
    if texte:
        lignes = [l for l in lignes if normaliser(texte) in normaliser(l["description"])]
    for l in lignes:
        l["adresse_a_preciser"], l["urgent"] = bool(l["adresse_a_preciser"]), bool(l["urgent"])
    return lignes


def lire_ticket(ticket_id: str) -> dict:
    with closing(connexion()) as cx:
        t = _ticket(cx, ticket_id)
        t["commentaires"] = [dict(r) for r in cx.execute(
            "SELECT date, texte, message_origine FROM commentaires WHERE ticket_id = ? ORDER BY id", (t["id"],))]
        return t


def creer_ticket(
    service: str,
    categorie: str,
    adresse: str,
    description: str,
    message_origine: str,
    adresse_a_preciser: bool = False,
    urgent: bool = False,
) -> dict:
    """Crée un ticket au statut ouvert et renvoie son numéro."""
    if service not in SERVICES:
        raise ValueError(f"Service inconnu : {service} (attendu : {', '.join(SERVICES)})")
    with closing(connexion(ecriture=True)) as cx, cx:
        existant = cx.execute("SELECT id FROM tickets WHERE message_origine = ?", (message_origine,)).fetchone()
        if existant:
            raise ValueError(f"Le message {message_origine} a déjà donné le ticket {existant[0]}.")
        annee = date.today().year if date.today().year >= 2026 else 2026
        dernier = cx.execute("SELECT MAX(CAST(SUBSTR(id, 9) AS INTEGER)) FROM tickets").fetchone()[0] or 0
        ticket_id = f"TK-{annee}-{dernier + 1:04d}"
        cx.execute(
            "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ouvert')",
            (ticket_id, service, categorie, adresse, int(adresse_a_preciser), int(urgent), description,
             message_origine, date.today().isoformat()),
        )
        return _ticket(cx, ticket_id)


def ajouter_commentaire(ticket_id: str, texte: str, message_origine: str | None = None) -> dict:
    with closing(connexion(ecriture=True)) as cx, cx:
        t = _ticket(cx, ticket_id)
        cx.execute(
            "INSERT INTO commentaires (ticket_id, texte, message_origine, date) VALUES (?, ?, ?, ?)",
            (t["id"], texte, message_origine, datetime.now().isoformat(timespec="seconds")),
        )
        n = cx.execute("SELECT COUNT(*) FROM commentaires WHERE ticket_id = ?", (t["id"],)).fetchone()[0]
        return {"ticket": t["id"], "statut": t["statut"], "commentaires": n}


def alerter_accueil(ticket_id: str, message: str) -> dict:
    """Inscrit une alerte pour l'agent d'accueil (consultée par tickets.py alertes)."""
    with closing(connexion(ecriture=True)) as cx, cx:
        t = _ticket(cx, ticket_id)
        curseur = cx.execute(
            "INSERT INTO alertes_accueil (ticket_id, message, date) VALUES (?, ?, ?)",
            (t["id"], message, datetime.now().isoformat(timespec="seconds")),
        )
        return {"alerte": curseur.lastrowid, "ticket": t["id"]}


def alertes() -> list[dict]:
    with closing(connexion()) as cx:
        return [dict(r) for r in cx.execute("SELECT * FROM alertes_accueil ORDER BY id")]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Outil de tickets local")
    sous = parser.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("lister")
    p.add_argument("--tous", action="store_true", help="inclure les tickets clos")
    p = sous.add_parser("voir")
    p.add_argument("id")
    sous.add_parser("alertes")
    args = parser.parse_args()
    if args.commande == "lister":
        with closing(connexion()) as cx:
            sql = "SELECT * FROM tickets" + ("" if args.tous else " WHERE statut != 'clos'") + " ORDER BY id"
            for t in cx.execute(sql):
                marques = ("URGENT " if t["urgent"] else "") + ("ADRESSE? " if t["adresse_a_preciser"] else "")
                print(f"{t['id']}  {t['statut']:<8}  {t['service']:<13}  {marques}{t['adresse']} : {t['description'][:60]}")
    elif args.commande == "voir":
        t = lire_ticket(args.id)
        for cle, valeur in t.items():
            print(f"{cle} : {valeur}")
    else:
        for a in alertes():
            print(f"{a['date']}  {a['ticket_id']}  {a['message']}")
