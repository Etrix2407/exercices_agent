"""Serveur MCP exemple : accès en lecture seule à la base SQLite fictive.

Expose :
- des outils (tools) de lecture : clients, commandes, factures, stocks, tickets,
  plus une requête SELECT libre ;
- une ressource : le schéma de la base (schema://entreprise) ;
- un prompt : préparation d'une relance de factures pour un client.

Lancement (transport stdio) :
    .venv\\Scripts\\python serveur.py
Chemin de la base : variable ENTREPRISE_DB, sinon ../sqlite/entreprise.db.
"""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

CHEMIN_BASE = Path(os.environ.get("ENTREPRISE_DB", Path(__file__).parent.parent / "sqlite" / "entreprise.db"))
LIMITE_LIGNES = 200
LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

serveur = MCPServer(
    name="entreprise-sqlite",
    instructions=(
        "Base fictive d'un distributeur de fournitures (Norvel Fournitures). "
        "Accès en lecture seule. Lire la ressource schema://entreprise avant d'écrire une requête SQL."
    ),
)


def connexion() -> sqlite3.Connection:
    """Connexion en lecture seule (mode=ro) : aucune écriture possible, même par requête libre."""
    if not CHEMIN_BASE.exists():
        raise FileNotFoundError(f"Base absente : {CHEMIN_BASE}. Lancer sqlite/creer_base.py.")
    cx = sqlite3.connect(f"{CHEMIN_BASE.resolve().as_uri()}?mode=ro", uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def requete(sql: str, params: tuple = ()) -> list[dict]:
    with closing(connexion()) as cx:
        return [dict(r) for r in cx.execute(sql, params).fetchmany(LIMITE_LIGNES)]


def liste(cle: str, elements: list[dict]) -> dict:
    """Résultat de liste avec son nombre : une liste vide reste visible pour le modèle ({"nombre": 0, ...})."""
    return {"nombre": len(elements), cle: elements}


# --- Outils -------------------------------------------------------------------


@serveur.tool(annotations=LECTURE)
def rechercher_clients(texte: str = "") -> dict:
    """Recherche des clients par fragment de raison sociale, ville, contact ou code (vide = tous)."""
    # Les jokers SQL saisis (% et _) sont pris littéralement
    motif = "%" + texte.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    return liste("clients", requete(
        "SELECT code, raison_sociale, secteur, ville, contact_nom, contact_email, segment FROM clients "
        "WHERE raison_sociale LIKE ? ESCAPE '!' OR ville LIKE ? ESCAPE '!' OR contact_nom LIKE ? ESCAPE '!' "
        "OR code LIKE ? ESCAPE '!' ORDER BY code",
        (motif, motif, motif, motif),
    ))


@serveur.tool(annotations=LECTURE)
def commandes_client(code_client: str) -> dict:
    """Liste les commandes d'un client (code CLI-xxxx) avec la facture associée éventuelle."""
    return liste("commandes", requete(
        "SELECT co.numero, co.date_commande, co.statut, co.montant_ht, f.numero AS facture, f.statut AS statut_facture "
        "FROM commandes co JOIN clients c ON c.id = co.client_id LEFT JOIN factures f ON f.commande_id = co.id "
        "WHERE c.code = ? ORDER BY co.date_commande",
        (code_client,),
    ))


@serveur.tool(annotations=LECTURE)
def detail_commande(numero: str) -> dict:
    """Détail d'une commande (CMD-2026-xxxx) : en-tête, lignes, facture."""
    entete = requete(
        "SELECT co.numero, co.date_commande, co.statut, co.montant_ht, c.code AS code_client, c.raison_sociale "
        "FROM commandes co JOIN clients c ON c.id = co.client_id WHERE co.numero = ?",
        (numero,),
    )
    if not entete:
        return {"erreur": f"Commande inconnue : {numero}"}
    lignes = requete(
        "SELECT p.reference, p.designation, l.quantite, l.prix_unitaire, ROUND(l.quantite * l.prix_unitaire, 2) AS total_ht "
        "FROM lignes_commande l JOIN produits p ON p.id = l.produit_id JOIN commandes co ON co.id = l.commande_id "
        "WHERE co.numero = ?",
        (numero,),
    )
    facture = requete(
        "SELECT f.numero, f.date_emission, f.date_echeance, f.montant_ttc, f.statut, f.date_paiement "
        "FROM factures f JOIN commandes co ON co.id = f.commande_id WHERE co.numero = ?",
        (numero,),
    )
    return {**entete[0], "lignes": lignes, "facture": facture[0] if facture else None}


@serveur.tool(annotations=LECTURE)
def factures_impayees(code_client: str | None = None, en_retard_seulement: bool = False) -> dict:
    """Factures non payées, éventuellement filtrées par client et limitées aux factures en retard."""
    sql = (
        "SELECT f.numero, co.numero AS commande, c.code AS code_client, c.raison_sociale, f.date_echeance, "
        "f.montant_ttc, f.statut FROM factures f JOIN commandes co ON co.id = f.commande_id "
        "JOIN clients c ON c.id = co.client_id WHERE f.statut != 'payee'"
    )
    params: list = []
    if en_retard_seulement:
        sql += " AND f.statut = 'en_retard'"
    if code_client:
        sql += " AND c.code = ?"
        params.append(code_client)
    return liste("factures", requete(sql + " ORDER BY f.date_echeance", tuple(params)))


@serveur.tool(annotations=LECTURE)
def stocks_sous_seuil() -> dict:
    """Produits dont la quantité en stock est inférieure au seuil d'alerte."""
    return liste("produits", requete(
        "SELECT p.reference, p.designation, p.fournisseur, s.entrepot, s.quantite, s.seuil_alerte "
        "FROM stocks s JOIN produits p ON p.id = s.produit_id WHERE s.quantite < s.seuil_alerte ORDER BY p.reference"
    ))


@serveur.tool(annotations=LECTURE)
def tickets(statut: str | None = None, code_client: str | None = None) -> dict:
    """Tickets support, filtrables par statut (ouvert, en_cours, resolu, ferme) et par client."""
    sql = (
        "SELECT t.numero, t.ouvert_le, t.categorie, t.priorite, t.statut, t.sujet, c.code AS code_client, "
        "c.raison_sociale, co.numero AS commande FROM tickets t JOIN clients c ON c.id = t.client_id "
        "LEFT JOIN commandes co ON co.id = t.commande_id WHERE 1 = 1"
    )
    params: list = []
    if statut:
        sql += " AND t.statut = ?"
        params.append(statut)
    if code_client:
        sql += " AND c.code = ?"
        params.append(code_client)
    return liste("tickets", requete(sql + " ORDER BY t.ouvert_le", tuple(params)))


@serveur.tool(annotations=LECTURE)
def requete_sql(sql: str) -> dict:
    """Exécute une requête SELECT (une seule instruction). Résultat limité à 200 lignes."""
    instruction = sql.strip().rstrip(";")
    if ";" in instruction or not re.match(r"(?is)^\s*(select|with)\b", instruction):
        raise ToolError("Seule une instruction SELECT unique est acceptée.")
    try:
        return liste("lignes", requete(instruction))
    except sqlite3.Error as e:
        raise ToolError(f"Erreur SQL : {e}") from e


# --- Ressource ----------------------------------------------------------------


@serveur.resource("schema://entreprise", name="schema", mime_type="text/plain", description="Schéma SQL de la base")
def schema() -> str:
    with closing(connexion()) as cx:
        lignes = cx.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name")
        return "\n\n".join(r[0] + ";" for r in lignes)


# --- Prompt -------------------------------------------------------------------


@serveur.prompt(description="Préparer une relance des factures impayées d'un client")
def relance_factures(code_client: str) -> str:
    return (
        f"Pour le client {code_client} : appeler factures_impayees avec ce code, "
        "puis rédiger un mail de relance courtois en français qui liste chaque facture "
        "(numéro, échéance, montant TTC). Ne pas envoyer le mail : le présenter pour validation."
    )


if __name__ == "__main__":
    serveur.run("stdio")
