"""Test du kit E07 : démarre le serveur MCP (stdio) et appelle chaque outil.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python test_kit.py
Les données sont réinitialisées au début et à la fin du test.
"""

import asyncio
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from mcp import Client, StdioServerParameters

import init_donnees

SERVEUR = Path(__file__).with_name("serveur_mcp.py")


def contenu(resultat) -> str:
    textes = "\n".join(getattr(c, "text", "") for c in resultat.content)
    return textes + json.dumps(resultat.structured_content, ensure_ascii=False)


def donnees(resultat):
    """Résultat d'outil décodé : contenu structuré, sinon texte JSON."""
    if resultat.structured_content is not None:
        sc = resultat.structured_content
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(resultat.content[0].text)


def occupation() -> tuple[int, int]:
    with closing(sqlite3.connect(init_donnees.BASE)) as cx:
        return (cx.execute("SELECT COUNT(*) FROM occupation_chambres").fetchone()[0],
                cx.execute("SELECT COUNT(*) FROM occupation_salles").fetchone()[0])


async def verifier() -> None:
    avant = occupation()
    async with Client(StdioServerParameters(command=sys.executable, args=[str(SERVEUR)])) as client:
        noms = sorted(o.name for o in (await client.list_tools()).tools)
        print("Outils :", ", ".join(noms))
        assert not any("envoy" in n for n in noms)

        r = await client.call_tool("lister_demandes", {"non_lues": True})
        assert "demande_10_voyage_etudes" in contenu(r)
        r = await client.call_tool("lire_demande", {"identifiant": "demande_05_fete_famille"})
        assert "décembre" in contenu(r)
        print("lister_demandes / lire_demande : ok, accents lus")

        r = await client.call_tool("disponibilites_chambres", {"arrivee": "2026-11-01", "depart": "2026-11-03"})
        dispo = donnees(r)
        assert dispo["capacite"]["double"] == 35 and len(dispo["par_nuit"]) == 2
        assert dispo["par_nuit"][0]["simple"] == 26, dispo["par_nuit"][0]  # 30 - 4 occupées
        r = await client.call_tool("disponibilites_chambres", {"arrivee": "2027-03-01", "depart": "2027-03-02"})
        assert r.is_error, "période hors planning refusée"
        print("disponibilites_chambres : ok")

        r = await client.call_tool("disponibilites_salles", {"date_debut": "2026-11-01", "date_fin": "2026-11-02"})
        jours = donnees(r)
        assert "Cèdre" in jours[0]["occupees"] and "Lys" in jours[0]["libres"]
        print("disponibilites_salles : ok")

        # Séjour à cheval sur deux saisons (nuits du 13 et 14 en basse, du 15 en haute)
        devis = {
            "arrivee": "2026-12-13", "depart": "2026-12-16",
            "chambres": {"simple": 3, "twin": 1},
            "salles": [{"salle": "lys", "jours": 1}],
            "repas": [{"prestation": "pause_cafe", "couverts": 10, "nombre": 2}],
        }
        r = await client.call_tool("calculer_devis", devis)
        d = donnees(r)
        assert d["total_ttc"] == 1980, d["lignes"]
        print("calculer_devis : total 1980,00 EUR (contrôle manuel)")
        r = await client.call_tool("calculer_devis", {**devis, "repas": [{"prestation": "remise", "couverts": 1}]})
        assert r.is_error, "prestation hors grille refusée"
        r = await client.call_tool("calculer_devis", {**devis, "chambres": {"double": -3}})
        assert r.is_error, "nombre de chambres négatif refusé"

        r = await client.call_tool("enregistrer_fiche_besoins",
                                   {"identifiant_demande": "demande_05_fete_famille", "fiche": {"test": True}})
        assert not r.is_error
        r = await client.call_tool("enregistrer_fiche_besoins",
                                   {"identifiant_demande": "../inbox/demande_05_fete_famille", "fiche": {"test": True}})
        assert r.is_error, "identifiant avec chemin refusé"
        r = await client.call_tool("enregistrer_brouillon", {
            "identifiant_demande": "demande_05_fete_famille", "corps": "Bonjour,\n\nTest.",
            "devis_markdown": d["markdown"],
        })
        assert "b001" in contenu(r)
        r = await client.call_tool("lister_brouillons", {})
        assert "devis.md" in contenu(r) and "helene.dubuisson" in contenu(r)
        print("enregistrer_fiche_besoins / enregistrer_brouillon / lister_brouillons : ok, devis joint")

        r = await client.call_tool("pre_reserver", {
            "identifiant_demande": "demande_05_fete_famille", "arrivee": "2026-12-13", "depart": "2026-12-14",
            "chambres": {"double": 2}, "salles": [{"salle": "Érable", "date": "2026-12-13"}],
        })
        assert "a_valider" in contenu(r)
        r = await client.call_tool("lister_pre_reservations", {"statut": "a_valider"})
        assert "demande_05_fete_famille" in contenu(r)
        r = await client.call_tool("pre_reserver", {
            "identifiant_demande": "demande_05_fete_famille", "arrivee": "2026-12-13", "depart": "2026-12-14",
            "chambres": {"double": 300},
        })
        assert r.is_error, "pré-réservation au-delà des chambres libres refusée"
        r = await client.call_tool("pre_reserver", {
            "identifiant_demande": "demande_05_fete_famille", "arrivee": "2026-12-12", "depart": "2026-12-13",
            "chambres": {"double": 1}, "salles": [{"salle": "Cèdre", "date": "2026-12-12"}],
        })
        assert r.is_error, "salle déjà occupée refusée"
        r = await client.call_tool("pre_reserver", {
            "identifiant_demande": "demande_99", "arrivee": "2026-12-13", "depart": "2026-12-14",
            "chambres": {"double": 1},
        })
        assert r.is_error, "demande inconnue refusée"
        r = await client.call_tool("lister_pre_reservations", {"statut": "validee"})
        assert '"nombre": 0' in contenu(r), "liste vide visible dans le texte"
        print("pre_reserver / lister_pre_reservations : a_valider, dépassement et demande inconnue refusés")

        texte = (await client.read_resource("hotel://grille-tarifaire")).contents[0].text
        assert "Basse" in texte
        p = await client.get_prompt("traiter_demande", {"identifiant": "demande_02_seminaire_equipe"})
        assert "demande_02_seminaire_equipe" in p.messages[0].content.text
        print("Ressource et prompt : ok")

    assert occupation() == avant, "le planning ne doit pas être modifié par l'agent"
    assert not list((init_donnees.BOITE / "outbox").glob("*.eml")), "aucun envoi attendu"
    print("Planning inchangé, aucun envoi")


def main() -> None:
    init_donnees.initialiser()
    try:
        asyncio.run(verifier())
    finally:
        init_donnees.initialiser()
    print("OK : kit E07 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
