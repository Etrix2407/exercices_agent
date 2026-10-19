"""Création d'une base SQLite fictive d'entreprise (distribution de fournitures).

Toutes les données sont inventées et générées de façon déterministe :
la même graine produit toujours la même base.

Usage :
    py -3.12 creer_base.py                      # crée entreprise.db à côté du script
    py -3.12 creer_base.py --sortie autre.db --graine 7
"""

import argparse
import random
import sqlite3
import unicodedata
from datetime import date, timedelta
from pathlib import Path

GRAINE_DEFAUT = 42
DATE_REFERENCE = date(2026, 9, 30)  # « aujourd'hui » dans les données
DEBUT = date(2026, 1, 5)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE clients (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,         -- ex. CLI-0007
    raison_sociale TEXT NOT NULL,
    secteur        TEXT NOT NULL,
    ville          TEXT NOT NULL,
    contact_nom    TEXT NOT NULL,
    contact_email  TEXT NOT NULL,
    telephone      TEXT NOT NULL,
    segment        TEXT NOT NULL CHECK (segment IN ('standard', 'premium', 'grand_compte')),
    cree_le        TEXT NOT NULL                 -- date ISO
);

CREATE TABLE produits (
    id             INTEGER PRIMARY KEY,
    reference      TEXT NOT NULL UNIQUE,         -- ex. PRD-104
    designation    TEXT NOT NULL,
    categorie      TEXT NOT NULL,
    prix_unitaire  REAL NOT NULL,                -- euros HT
    fournisseur    TEXT NOT NULL
);

CREATE TABLE stocks (
    produit_id     INTEGER PRIMARY KEY REFERENCES produits(id),
    entrepot       TEXT NOT NULL,
    quantite       INTEGER NOT NULL,
    seuil_alerte   INTEGER NOT NULL,
    maj_le         TEXT NOT NULL
);

CREATE TABLE commandes (
    id             INTEGER PRIMARY KEY,
    numero         TEXT NOT NULL UNIQUE,         -- ex. CMD-2026-0012
    client_id      INTEGER NOT NULL REFERENCES clients(id),
    date_commande  TEXT NOT NULL,
    statut         TEXT NOT NULL CHECK (statut IN ('en_preparation', 'expediee', 'livree', 'annulee')),
    montant_ht     REAL NOT NULL
);

CREATE TABLE lignes_commande (
    id             INTEGER PRIMARY KEY,
    commande_id    INTEGER NOT NULL REFERENCES commandes(id),
    produit_id     INTEGER NOT NULL REFERENCES produits(id),
    quantite       INTEGER NOT NULL,
    prix_unitaire  REAL NOT NULL
);

CREATE TABLE factures (
    id             INTEGER PRIMARY KEY,
    numero         TEXT NOT NULL UNIQUE,         -- ex. FAC-2026-0008
    commande_id    INTEGER NOT NULL UNIQUE REFERENCES commandes(id),
    date_emission  TEXT NOT NULL,
    date_echeance  TEXT NOT NULL,
    montant_ttc    REAL NOT NULL,
    statut         TEXT NOT NULL CHECK (statut IN ('payee', 'en_attente', 'en_retard')),
    date_paiement  TEXT
);

CREATE TABLE tickets (
    id             INTEGER PRIMARY KEY,
    numero         TEXT NOT NULL UNIQUE,         -- ex. TCK-0031
    client_id      INTEGER NOT NULL REFERENCES clients(id),
    commande_id    INTEGER REFERENCES commandes(id),
    ouvert_le      TEXT NOT NULL,
    categorie      TEXT NOT NULL,
    priorite       TEXT NOT NULL CHECK (priorite IN ('basse', 'normale', 'haute')),
    statut         TEXT NOT NULL CHECK (statut IN ('ouvert', 'en_cours', 'resolu', 'ferme')),
    sujet          TEXT NOT NULL,
    description    TEXT NOT NULL
);

CREATE INDEX idx_commandes_client ON commandes(client_id);
CREATE INDEX idx_factures_statut ON factures(statut);
CREATE INDEX idx_tickets_statut ON tickets(statut);
"""

# Clients : liste fixe, réutilisée par la fausse boîte mail.
# (raison sociale, secteur, ville, contact, segment)
CLIENTS = [
    ("Boulangerie Lemaire", "alimentation", "Namur", "Claire Lemaire", "premium"),
    ("Garage Vandenberghe", "automobile", "Liège", "Marc Vandenberghe", "standard"),
    ("Cabinet Dufresne et Associés", "services juridiques", "Bruxelles", "Hélène Dufresne", "premium"),
    ("Imprimerie du Canal", "imprimerie", "Charleroi", "Yves Martens", "grand_compte"),
    ("Crèche Les Petits Pas", "petite enfance", "Mons", "Sophie Renard", "standard"),
    ("Hôtel Belvédère", "hôtellerie", "Spa", "Antoine Leclercq", "grand_compte"),
    ("Menuiserie Collard", "construction", "Arlon", "Julien Collard", "standard"),
    ("Pharmacie Centrale Wavre", "santé", "Wavre", "Nadia Benali", "premium"),
    ("École Saint-Exupéry", "enseignement", "Louvain-la-Neuve", "Pierre Dumont", "grand_compte"),
    ("Atelier Vélo Mobile", "commerce", "Gand", "Tom Peeters", "standard"),
    ("Clinique vétérinaire des Prés", "santé animale", "Dinant", "Laura Simon", "standard"),
    ("Traiteur Moreau", "alimentation", "Tournai", "Isabelle Moreau", "premium"),
    ("Bureau d'études Archimède", "ingénierie", "Bruxelles", "Karim Haddad", "grand_compte"),
    ("Fleurs et Jardins Delvaux", "commerce", "Nivelles", "Chantal Delvaux", "standard"),
    ("Salle de sport Énergie", "loisirs", "Liège", "Kevin Lambert", "standard"),
    ("Agence immobilière Horizon", "immobilier", "Namur", "Sarah Wouters", "premium"),
    ("Brasserie artisanale La Fontaine", "alimentation", "Huy", "Olivier Fontaine", "premium"),
    ("Maison de repos Les Tilleuls", "santé", "Verviers", "Martine Goffin", "grand_compte"),
    ("Studio graphique Pixel", "communication", "Bruxelles", "Léa Janssens", "standard"),
    ("Transports Henrard", "logistique", "Marche-en-Famenne", "Paul Henrard", "grand_compte"),
    ("Librairie Le Marque-Page", "commerce", "Ottignies", "Anne Lejeune", "standard"),
    ("Cabinet dentaire Smile", "santé", "Waterloo", "David Cohen", "standard"),
    ("Camping des Ardennes", "loisirs", "Bouillon", "Michel Gérard", "standard"),
    ("Coopérative Terre Vive", "agriculture", "Gembloux", "Elise Noël", "premium"),
]

# Produits : (désignation, catégorie, prix HT, fournisseur)
PRODUITS = [
    ("Ramette papier A4 80 g (500 f.)", "papeterie", 4.90, "Papeteries Ardoise"),
    ("Ramette papier A3 80 g (500 f.)", "papeterie", 9.80, "Papeteries Ardoise"),
    ("Enveloppes C5 (boîte de 500)", "papeterie", 18.50, "Papeteries Ardoise"),
    ("Classeur à levier dos 8 cm", "classement", 2.40, "Bureau Plus Distribution"),
    ("Chemises cartonnées (lot de 100)", "classement", 12.90, "Bureau Plus Distribution"),
    ("Stylo bille bleu (boîte de 50)", "écriture", 11.50, "Scripta"),
    ("Surligneurs assortis (lot de 4)", "écriture", 3.60, "Scripta"),
    ("Cartouche toner noir TN-2420", "consommables", 64.00, "Tonerix"),
    ("Cartouche toner couleur pack CMY", "consommables", 189.00, "Tonerix"),
    ("Tambour imprimante DR-2400", "consommables", 92.00, "Tonerix"),
    ("Chaise de bureau ergonomique", "mobilier", 249.00, "Mobilia Pro"),
    ("Bureau réglable en hauteur 160 cm", "mobilier", 529.00, "Mobilia Pro"),
    ("Caisson 3 tiroirs", "mobilier", 139.00, "Mobilia Pro"),
    ("Lampe LED de bureau", "mobilier", 44.90, "Mobilia Pro"),
    ("Gel hydroalcoolique 5 L", "hygiène", 21.00, "Hygiena"),
    ("Essuie-mains papier (carton de 20)", "hygiène", 32.50, "Hygiena"),
    ("Savon liquide 5 L", "hygiène", 14.20, "Hygiena"),
    ("Café en grains 1 kg", "pause", 16.80, "Torréfaction Mosane"),
    ("Gobelets carton 20 cl (lot de 1000)", "pause", 27.00, "Torréfaction Mosane"),
    ("Étiquettes adresse (boîte de 2100)", "étiquetage", 19.90, "Scripta"),
    ("Clé USB 64 Go", "informatique", 9.90, "Numeris"),
    ("Souris sans fil", "informatique", 14.50, "Numeris"),
    ("Clavier filaire AZERTY", "informatique", 19.00, "Numeris"),
    ("Écran 24 pouces", "informatique", 169.00, "Numeris"),
    ("Casque audio USB", "informatique", 39.00, "Numeris"),
    ("Destructeur de documents", "équipement", 189.00, "Bureau Plus Distribution"),
    ("Plastifieuse A4", "équipement", 59.00, "Bureau Plus Distribution"),
    ("Tableau blanc 120 x 90", "équipement", 89.00, "Bureau Plus Distribution"),
    ("Marqueurs tableau blanc (lot de 8)", "écriture", 7.90, "Scripta"),
    ("Cartons de déménagement (lot de 10)", "emballage", 15.00, "Emballages Meuse"),
]

TICKETS_TYPES = {
    "livraison": [
        ("Colis non reçu", "La commande indiquée comme expédiée n'est pas arrivée."),
        ("Livraison partielle", "Une partie des articles manque dans le colis."),
        ("Retard de livraison", "La date de livraison annoncée est dépassée."),
    ],
    "produit": [
        ("Article endommagé", "Un article est arrivé abîmé, l'emballage était écrasé."),
        ("Mauvaise référence livrée", "La référence reçue ne correspond pas à la commande."),
        ("Produit défectueux", "Le produit ne fonctionne pas dès la mise en service."),
    ],
    "facturation": [
        ("Erreur de montant", "Le montant facturé ne correspond pas au devis."),
        ("Duplicata de facture", "Demande d'un duplicata de facture au format PDF."),
        ("Changement d'adresse de facturation", "L'adresse de facturation a changé."),
    ],
    "compte": [
        ("Accès espace client", "Impossible de se connecter à l'espace client."),
        ("Ajout d'un contact", "Ajouter un second contact pour les commandes."),
    ],
}


def sans_accents(texte: str) -> str:
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()


def email_contact(contact: str, raison_sociale: str) -> str:
    """Adresse fictive sous le domaine réservé .example."""
    local = ".".join(sans_accents(contact).lower().split())
    mots = [m for m in sans_accents(raison_sociale).lower().replace("'", " ").split() if len(m) > 3][:2]
    return f"{local}@{'-'.join(mots)}.example"


def construire(chemin: Path, graine: int) -> None:
    rnd = random.Random(graine)
    if chemin.exists():
        chemin.unlink()
    cx = sqlite3.connect(chemin)
    cx.executescript(SCHEMA)

    # Clients
    for i, (nom, secteur, ville, contact, segment) in enumerate(CLIENTS, start=1):
        tel = "+32 " + " ".join(str(rnd.randint(10, 99)) for _ in range(4))
        cree = DEBUT - timedelta(days=rnd.randint(30, 1500))
        cx.execute(
            "INSERT INTO clients VALUES (?,?,?,?,?,?,?,?,?,?)",
            (i, f"CLI-{i:04d}", nom, secteur, ville, contact, email_contact(contact, nom), tel, segment, cree.isoformat()),
        )

    # Produits et stocks
    for i, (designation, categorie, prix, fournisseur) in enumerate(PRODUITS, start=1):
        cx.execute(
            "INSERT INTO produits VALUES (?,?,?,?,?,?)",
            (i, f"PRD-{100 + i}", designation, categorie, prix, fournisseur),
        )
        seuil = rnd.choice([5, 10, 20, 50])
        # Environ un produit sur cinq sous le seuil d'alerte
        if rnd.random() < 0.2:
            quantite = rnd.randint(0, seuil - 1)
        else:
            quantite = rnd.randint(seuil, seuil * 12)
        entrepot = rnd.choice(["Namur-Nord", "Liège-Bressoux"])
        maj = DATE_REFERENCE - timedelta(days=rnd.randint(0, 10))
        cx.execute("INSERT INTO stocks VALUES (?,?,?,?,?)", (i, entrepot, quantite, seuil, maj.isoformat()))

    # Commandes, lignes de commande et factures
    nb_commandes = 120
    jours = (DATE_REFERENCE - DEBUT).days
    dates = sorted(DEBUT + timedelta(days=rnd.randint(0, jours)) for _ in range(nb_commandes))
    ligne_id = 0
    facture_num = 0
    for n, d in enumerate(dates, start=1):
        client_id = rnd.randint(1, len(CLIENTS))
        age = (DATE_REFERENCE - d).days
        if rnd.random() < 0.05:
            statut = "annulee"
        elif age <= 3:
            statut = "en_preparation"
        elif age <= 8:
            statut = rnd.choice(["expediee", "livree"])
        else:
            statut = "livree"
        cx.execute(
            "INSERT INTO commandes VALUES (?,?,?,?,?,?)",
            (n, f"CMD-2026-{n:04d}", client_id, d.isoformat(), statut, 0.0),
        )
        total = 0.0
        for produit_id in rnd.sample(range(1, len(PRODUITS) + 1), rnd.randint(1, 5)):
            qte = rnd.randint(1, 20)
            prix = PRODUITS[produit_id - 1][2]
            ligne_id += 1
            cx.execute("INSERT INTO lignes_commande VALUES (?,?,?,?,?)", (ligne_id, n, produit_id, qte, prix))
            total += qte * prix
        total = round(total, 2)
        cx.execute("UPDATE commandes SET montant_ht = ? WHERE id = ?", (total, n))

        if statut in ("expediee", "livree"):
            facture_num += 1
            emission = d + timedelta(days=rnd.randint(0, 3))
            echeance = emission + timedelta(days=30)
            paiement = None
            if echeance >= DATE_REFERENCE:
                f_statut = rnd.choice(["en_attente", "en_attente", "payee"])
            elif rnd.random() < 0.15:
                f_statut = "en_retard"
            else:
                f_statut = "payee"
            if f_statut == "payee":
                paiement = min(emission + timedelta(days=rnd.randint(2, 35)), DATE_REFERENCE).isoformat()
            cx.execute(
                "INSERT INTO factures VALUES (?,?,?,?,?,?,?,?)",
                (
                    facture_num,
                    f"FAC-2026-{facture_num:04d}",
                    n,
                    emission.isoformat(),
                    echeance.isoformat(),
                    round(total * 1.21, 2),
                    f_statut,
                    paiement,
                ),
            )

    # Tickets support
    for t in range(1, 41):
        categorie = rnd.choice(list(TICKETS_TYPES))
        sujet, description = rnd.choice(TICKETS_TYPES[categorie])
        commande_id, client_id, d = cx.execute(
            "SELECT id, client_id, date_commande FROM commandes WHERE statut != 'annulee' "
            "ORDER BY id LIMIT 1 OFFSET ?",
            (rnd.randint(0, 100),),
        ).fetchone()
        ouvert = min(date.fromisoformat(d) + timedelta(days=rnd.randint(2, 15)), DATE_REFERENCE)
        if t > 32:
            # Les derniers tickets sont récents pour disposer de tickets ouverts
            ouvert = DATE_REFERENCE - timedelta(days=rnd.randint(0, 6))
        if (DATE_REFERENCE - ouvert).days < 7:
            statut = rnd.choice(["ouvert", "en_cours"])
        else:
            statut = rnd.choice(["resolu", "ferme", "ferme", "en_cours"])
        priorite = rnd.choice(["basse", "normale", "normale", "haute"])
        if categorie == "compte":
            commande_id = None
        cx.execute(
            "INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?)",
            (t, f"TCK-{t:04d}", client_id, commande_id, ouvert.isoformat(), categorie, priorite, statut, sujet, description),
        )

    cx.commit()
    cx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sortie", type=Path, default=Path(__file__).with_name("entreprise.db"))
    parser.add_argument("--graine", type=int, default=GRAINE_DEFAUT)
    args = parser.parse_args()
    construire(args.sortie, args.graine)
    cx = sqlite3.connect(args.sortie)
    for table in ("clients", "produits", "stocks", "commandes", "lignes_commande", "factures", "tickets"):
        n = cx.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<16} {n:>4} lignes")
    cx.close()
    print(f"Base créée : {args.sortie}")


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    main()
