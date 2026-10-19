"""Test du kit E08 : démarre le serveur MCP (stdio) et appelle chaque outil.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python test_kit.py
Les données sont réinitialisées au début et à la fin du test.
"""

import asyncio
import json
import sys
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


async def verifier() -> None:
    async with Client(StdioServerParameters(command=sys.executable, args=[str(SERVEUR)])) as client:
        noms = sorted(o.name for o in (await client.list_tools()).tools)
        print("Outils :", ", ".join(noms))
        assert not any(m in n for n in noms for m in ("envoy", "clore", "clotur", "supprim"))

        r = await client.call_tool("lister_signalements", {"non_lus": True})
        assert donnees(r)["nombre"] == 30
        r = await client.call_tool("lire_signalement", {"identifiant": "signalement_01", "marquer_lu": True})
        assert "Moulin" in contenu(r)
        print("lister_signalements / lire_signalement : 30 signalements")

        r = await client.call_tool("rechercher_voie", {"texte": "à hauteur du 8 r. du Moulin"})
        assert donnees(r)["voies"][0]["nom_normalise"] == "Rue du Moulin", donnees(r)
        r = await client.call_tool("rechercher_voie", {"texte": "en face de la boulangerie de la place"})
        assert donnees(r)["voies"][0].get("voie_rattachee") == "Place de la Mairie", donnees(r)
        r = await client.call_tool("rechercher_voie", {"texte": "rue Imaginaire"})
        assert donnees(r)["nombre"] == 0 and r.content, "liste vide visible dans le texte"
        print("rechercher_voie : voie, repère, inconnue")

        r = await client.call_tool("chercher_tickets_ouverts", {"service": "voirie"})
        ids = [t["id"] for t in donnees(r)["tickets"]]
        assert "TK-2026-0387" in ids and "TK-2026-0355" not in ids
        print("chercher_tickets_ouverts : ok")

        r = await client.call_tool("creer_ticket", {
            "service": "proprete", "categorie": "test", "adresse": "Rue de Verdun",
            "description": "Ticket de test", "message_origine": "signalement_01",
        })
        nouveau = donnees(r)["id"]
        assert nouveau.endswith("-0411"), nouveau  # numérotation à la suite des tickets existants
        r = await client.call_tool("creer_ticket", {
            "service": "proprete", "categorie": "test", "adresse": "Rue de Verdun",
            "description": "Doublon", "message_origine": "signalement_01",
        })
        assert r.is_error, "deuxième ticket pour le même message refusé"
        r = await client.call_tool("creer_ticket", {
            "service": "police", "categorie": "x", "adresse": "x", "description": "x", "message_origine": "x",
        })
        assert r.is_error, "service hors liste refusé"
        r = await client.call_tool("creer_ticket", {
            "service": "voirie", "categorie": "x", "adresse": "x", "description": "x",
            "message_origine": "signalement_99",
        })
        assert r.is_error, "signalement d'origine inconnu refusé"
        print(f"creer_ticket : {nouveau}, doublon et service inconnu refusés")

        r = await client.call_tool("ajouter_commentaire", {"ticket_id": nouveau, "texte": "Commentaire de test",
                                                           "message_origine": "signalement_01"})
        assert donnees(r)["commentaires"] == 1
        r = await client.call_tool("alerter_accueil", {"ticket_id": nouveau, "message": "Alerte de test"})
        assert not r.is_error
        r = await client.call_tool("lire_ticket", {"ticket_id": nouveau})
        assert "Commentaire de test" in contenu(r)
        print("ajouter_commentaire / alerter_accueil / lire_ticket : ok")

        r = await client.call_tool("enregistrer_brouillon", {
            "identifiant_signalement": "signalement_01", "corps": f"Bonjour,\n\nTicket {nouveau}.",
            "destinataire": "test@courriel.example",
        })
        assert "b001" in contenu(r)
        r = await client.call_tool("lister_brouillons", {})
        assert "test@courriel.example" in contenu(r)
        print("enregistrer_brouillon / lister_brouillons : ok")

        texte = (await client.read_resource("commune://referentiel-voies")).contents[0].text
        assert texte.startswith("nom_normalise")
        p = await client.get_prompt("traiter_signalement", {"identifiant": "signalement_02"})
        assert "signalement_02" in p.messages[0].content.text
        print("Ressource et prompt : ok")

    assert not list((init_donnees.BOITE / "outbox").glob("*.eml")), "aucun envoi attendu"


def main() -> None:
    init_donnees.initialiser()
    try:
        asyncio.run(verifier())
    finally:
        init_donnees.initialiser()
    print("OK : kit E08 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
