"""Planning, grille tarifaire et devis de l'hôtel (base hotel.db).

Fonctions utilisées par serveur_mcp.py :
    disponibilites_chambres, disponibilites_salles, calculer_devis, pre_reserver, pre_reservations

Ligne de commande (validation humaine des pré-réservations) :
    ..\\.venv\\Scripts\\python planning.py lister
    ..\\.venv\\Scripts\\python planning.py valider 1
La validation demande une confirmation dans le terminal, puis inscrit la pré-réservation au planning.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

CHEMIN_BASE = Path(os.environ.get("KIT_BASE", Path(__file__).resolve().parent / "hotel.db"))


def connexion(ecriture: bool = False) -> sqlite3.Connection:
    if not CHEMIN_BASE.exists():
        raise FileNotFoundError(f"Base absente : {CHEMIN_BASE}. Lancer init_donnees.py.")
    mode = "rw" if ecriture else "ro"
    cx = sqlite3.connect(f"{CHEMIN_BASE.resolve().as_uri()}?mode={mode}", uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def _date(texte: str) -> date:
    try:
        return date.fromisoformat(texte)
    except ValueError as e:
        raise ValueError(f"Date invalide (format AAAA-MM-JJ attendu) : {texte}") from e


def _jours(debut: date, fin: date) -> list[date]:
    return [debut + timedelta(days=i) for i in range((fin - debut).days)]


def _sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn").lower()


def _verifier_periode(cx: sqlite3.Connection, debut: date, fin: date) -> None:
    mini, maxi = cx.execute("SELECT MIN(debut), MAX(fin) FROM saisons").fetchone()
    if fin <= debut:
        raise ValueError("La date de fin doit suivre la date de début.")
    if debut < date.fromisoformat(mini) or fin - timedelta(days=1) > date.fromisoformat(maxi):
        raise ValueError(f"Planning et grille couvrent les nuits du {mini} au {maxi}.")


def nom_salle(cx: sqlite3.Connection, texte: str) -> str:
    """Retrouve le nom exact d'une salle, accents et casse ignorés."""
    for (salle,) in cx.execute("SELECT salle FROM salles"):
        if _sans_accent(salle) == _sans_accent(texte.strip()):
            return salle
    raise ValueError(f"Salle inconnue : {texte}")


# --- Disponibilités -----------------------------------------------------------


def disponibilites_chambres(arrivee: str, depart: str) -> dict:
    """Chambres libres par type pour chaque nuit de arrivee (incluse) à depart (exclue)."""
    debut, fin = _date(arrivee), _date(depart)
    with closing(connexion()) as cx:
        _verifier_periode(cx, debut, fin)
        capacite = {r["type"]: r["nombre"] for r in cx.execute("SELECT type, nombre FROM types_chambre")}
        nuits = []
        for jour in _jours(debut, fin):
            occupe = dict(cx.execute(
                "SELECT type, SUM(nombre) FROM occupation_chambres WHERE date_nuit = ? GROUP BY type",
                (jour.isoformat(),),
            ).fetchall())
            nuits.append({"nuit": jour.isoformat(), **{t: n - occupe.get(t, 0) for t, n in capacite.items()}})
    minimum = {t: min(n[t] for n in nuits) for t in capacite}
    return {"capacite": capacite, "libres_sur_toute_la_periode": minimum, "par_nuit": nuits}


def disponibilites_salles(date_debut: str, date_fin: str) -> list[dict]:
    """Salles libres pour chaque jour de date_debut à date_fin (incluses)."""
    debut, fin = _date(date_debut), _date(date_fin) + timedelta(days=1)
    with closing(connexion()) as cx:
        _verifier_periode(cx, debut, fin)
        salles = [dict(r) for r in cx.execute("SELECT salle, capacite FROM salles ORDER BY capacite DESC")]
        resultat = []
        for jour in _jours(debut, fin):
            prises = {r[0] for r in cx.execute("SELECT salle FROM occupation_salles WHERE date = ?", (jour.isoformat(),))}
            resultat.append({
                "date": jour.isoformat(),
                "libres": [s["salle"] for s in salles if s["salle"] not in prises],
                "occupees": sorted(prises),
            })
    return resultat


# --- Devis --------------------------------------------------------------------


def calculer_devis(
    arrivee: str,
    depart: str,
    chambres: dict[str, int],
    salles: list[dict] | None = None,
    repas: list[dict] | None = None,
) -> dict:
    """Devis indicatif d'après la grille.

    chambres : {type: nombre} ; salles : [{"salle": "Cèdre", "jours": 1}] ;
    repas : [{"prestation": "diner", "couverts": 60, "nombre": 1}].
    Le petit-déjeuner est ajouté pour chaque personne logée et chaque nuit.
    """
    debut, fin = _date(arrivee), _date(depart)
    lignes = []
    with closing(connexion()) as cx:
        _verifier_periode(cx, debut, fin)
        types = {r["type"]: dict(r) for r in cx.execute("SELECT * FROM types_chambre")}
        saisons = [dict(r) for r in cx.execute("SELECT * FROM saisons")]
        tarifs = {(r["type"], r["saison"]): r["prix_nuit"] for r in cx.execute("SELECT * FROM tarifs_chambre")}
        prestations = {r["code"]: dict(r) for r in cx.execute("SELECT * FROM prestations")}

        def saison_de(jour: date) -> str:
            return next(s["saison"] for s in saisons if s["debut"] <= jour.isoformat() <= s["fin"])

        # Chambres : une ligne par type et par saison
        personnes_nuits = 0
        for type_, nombre in chambres.items():
            type_ = type_.strip().lower()
            if type_ not in types:
                raise ValueError(f"Type de chambre inconnu : {type_} (attendu : {', '.join(types)})")
            if nombre <= 0:
                continue
            par_saison: dict[str, int] = {}
            for jour in _jours(debut, fin):
                par_saison[saison_de(jour)] = par_saison.get(saison_de(jour), 0) + 1
            for saison, nuits in par_saison.items():
                prix = tarifs[(type_, saison)]
                lignes.append({
                    "libelle": f"Chambre {type_}, saison {saison}",
                    "quantite": nombre * nuits,
                    "unite": "chambre x nuit",
                    "prix_unitaire": prix,
                    "montant": round(nombre * nuits * prix, 2),
                })
            personnes_nuits += nombre * types[type_]["personnes"] * len(_jours(debut, fin))

        if personnes_nuits:
            p = prestations["petit_dejeuner"]
            lignes.append({
                "libelle": p["libelle"], "quantite": personnes_nuits, "unite": "personne x nuit",
                "prix_unitaire": p["prix"], "montant": round(personnes_nuits * p["prix"], 2),
            })

        for s in salles or []:
            salle = nom_salle(cx, s["salle"])
            prix = cx.execute("SELECT prix_jour FROM salles WHERE salle = ?", (salle,)).fetchone()[0]
            jours = int(s.get("jours", 1))
            lignes.append({
                "libelle": f"Salle {salle}", "quantite": jours, "unite": "jour",
                "prix_unitaire": prix, "montant": round(jours * prix, 2),
            })

        for r in repas or []:
            code = r["prestation"]
            if code not in prestations or code == "petit_dejeuner":
                autorises = [c for c in prestations if c != "petit_dejeuner"]
                raise ValueError(f"Prestation inconnue : {code} (attendu : {', '.join(autorises)})")
            p = prestations[code]
            quantite = int(r["couverts"]) * int(r.get("nombre", 1))
            lignes.append({
                "libelle": p["libelle"], "quantite": quantite, "unite": p["unite"],
                "prix_unitaire": p["prix"], "montant": round(quantite * p["prix"], 2),
            })

    total = round(sum(l["montant"] for l in lignes), 2)
    return {
        "arrivee": arrivee, "depart": depart, "nuits": (fin - debut).days,
        "lignes": lignes, "total_ttc": total,
        "mentions": "Montants en euros TTC, sans remise, taxe de séjour non incluse.",
        "markdown": devis_markdown(arrivee, depart, lignes, total),
    }


def devis_markdown(arrivee: str, depart: str, lignes: list[dict], total: float) -> str:
    texte = [
        "# Devis indicatif",
        "",
        f"Séjour : arrivée le {arrivee}, départ le {depart}.",
        "",
        "| Prestation | Quantité | Prix unitaire (EUR) | Montant (EUR) |",
        "|---|---|---|---|",
    ]
    texte += [f"| {l['libelle']} | {l['quantite']} | {l['prix_unitaire']:.2f} | {l['montant']:.2f} |" for l in lignes]
    texte += ["", f"Total TTC : {total:.2f} EUR", "", "Montants TTC, sans remise. Taxe de séjour non incluse."]
    return "\n".join(texte) + "\n"


# --- Pré-réservations (soumises à validation humaine) --------------------------


def pre_reserver(demande: str, arrivee: str, depart: str, chambres: dict[str, int], salles: list[dict] | None = None) -> dict:
    """Enregistre une pré-réservation au statut a_valider. Le planning n'est pas modifié.

    Refus si rien n'est demandé, si une salle est hors séjour ou si le planning ne laisse pas assez de place.
    """
    debut, fin = _date(arrivee), _date(depart)
    chambres = {t: n for t, n in chambres.items() if n > 0}
    if not chambres and not salles:
        raise ValueError("Pré-réservation vide : indiquer des chambres ou des salles.")
    libres = disponibilites_chambres(arrivee, depart)["libres_sur_toute_la_periode"]
    manque = [f"{t} : {n} demandées, {libres.get(t, 0)} libres" for t, n in chambres.items() if n > libres.get(t, 0)]
    if manque:
        raise ValueError("Chambres insuffisantes sur toute la période (" + " ; ".join(manque) + ").")
    with closing(connexion(ecriture=True)) as cx, cx:
        _verifier_periode(cx, debut, fin)
        salles_norm = [{"salle": nom_salle(cx, s["salle"]), "date": _date(s["date"]).isoformat()} for s in salles or []]
        for s in salles_norm:
            if not debut.isoformat() <= s["date"] <= fin.isoformat():
                raise ValueError(f"Salle {s['salle']} le {s['date']} : date hors du séjour {arrivee} - {depart}.")
            if cx.execute("SELECT 1 FROM occupation_salles WHERE date = ? AND salle = ?",
                          (s["date"], s["salle"])).fetchone():
                raise ValueError(f"Salle {s['salle']} déjà occupée le {s['date']} dans le planning.")
        curseur = cx.execute(
            "INSERT INTO pre_reservations (demande, arrivee, depart, chambres, salles, cree_le) VALUES (?, ?, ?, ?, ?, ?)",
            (demande, arrivee, depart, json.dumps(chambres), json.dumps(salles_norm, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )
        return {"id": curseur.lastrowid, "statut": "a_valider",
                "note": "Planning inchangé. Validation par une personne : planning.py valider <id>."}


def pre_reservations(statut: str | None = None) -> list[dict]:
    with closing(connexion()) as cx:
        sql, params = "SELECT * FROM pre_reservations", ()
        if statut:
            sql, params = sql + " WHERE statut = ?", (statut,)
        return [dict(r) for r in cx.execute(sql + " ORDER BY id", params)]


def valider(identifiant: int) -> None:
    """Validation humaine dans le terminal : inscrit la pré-réservation au planning."""
    with closing(connexion(ecriture=True)) as cx, cx:
        pre = cx.execute("SELECT * FROM pre_reservations WHERE id = ?", (identifiant,)).fetchone()
        if not pre or pre["statut"] != "a_valider":
            print("Pré-réservation introuvable ou déjà traitée.")
            return
        print(json.dumps(dict(pre), indent=2, ensure_ascii=False))
        if input("Inscrire au planning ? (oui/non) ").strip().lower() != "oui":
            print("Abandon.")
            return
        reference = f"PRE-{identifiant:03d}"
        for type_, nombre in json.loads(pre["chambres"]).items():
            for jour in _jours(_date(pre["arrivee"]), _date(pre["depart"])):
                cx.execute("INSERT INTO occupation_chambres VALUES (?, ?, ?, ?)",
                           (jour.isoformat(), type_, reference, nombre))
        for s in json.loads(pre["salles"]):
            cx.execute("INSERT INTO occupation_salles VALUES (?, ?, ?, 'journée')", (s["date"], s["salle"], reference))
        cx.execute("UPDATE pre_reservations SET statut = 'validee', valide_le = ? WHERE id = ?",
                   (datetime.now().isoformat(timespec="seconds"), identifiant))
        print(f"Inscrite au planning sous la référence {reference}.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Pré-réservations de l'hôtel")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("lister")
    v = sous.add_parser("valider")
    v.add_argument("id", type=int)
    args = parser.parse_args()
    if args.commande == "lister":
        for p in pre_reservations():
            print(f"{p['id']:>3}  {p['statut']:<10}  {p['demande']:<35}  {p['arrivee']} -> {p['depart']}  {p['chambres']}")
    else:
        valider(args.id)
