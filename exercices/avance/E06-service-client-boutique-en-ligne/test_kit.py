"""Test du kit E06 : démarre l'API de suivi et le serveur MCP (stdio), appelle chaque outil.

Usage (depuis ce dossier) :
    ..\\.venv\\Scripts\\python test_kit.py
Les données sont réinitialisées au début et à la fin du test.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from mcp import Client, StdioServerParameters

import api_suivi
import init_donnees

SERVEUR = Path(__file__).with_name("serveur_mcp.py")


def contenu(resultat) -> str:
    """Texte et contenu structuré d'un résultat d'outil, concaténés pour les vérifications."""
    textes = "\n".join(getattr(c, "text", "") for c in resultat.content)
    return textes + json.dumps(resultat.structured_content, ensure_ascii=False)


async def verifier(url_api: str) -> None:
    parametres = StdioServerParameters(
        command=sys.executable, args=[str(SERVEUR)], env={**os.environ, "SUIVI_API_URL": url_api}
    )
    async with Client(parametres) as client:
        noms = sorted(o.name for o in (await client.list_tools()).tools)
        print("Outils :", ", ".join(noms))
        assert not any("envoy" in n for n in noms), "aucun outil d'envoi attendu"

        r = await client.call_tool("lister_courriels", {"non_lus": True})
        assert not r.is_error and "courriel-25" in contenu(r)
        print("lister_courriels : 25 non lus")

        r = await client.call_tool("lire_courriel", {"identifiant": "courriel-01", "marquer_lu": True})
        assert "ML-2026-1002" in contenu(r)
        r = await client.call_tool("lire_courriel", {"identifiant": "../../donnees/eml/courriel-01"})
        assert r.is_error, "identifiant avec chemin refusé"
        r = await client.call_tool("lister_courriels", {"non_lus": True})
        assert "courriel-01" not in contenu(r)
        print("lire_courriel : courriel-01 lu")

        r = await client.call_tool("chercher_commande", {"numero": "ML-2026-1002"})
        assert "ETX261002BE" in contenu(r)
        r = await client.call_tool("chercher_commande", {"numero": "ML-2026-9999"})
        assert "inconnue" in contenu(r)
        print("chercher_commande : connue et inconnue")

        r = await client.call_tool("commandes_client", {"email_ou_nom": "lucie.vermeulen@client.test"})
        assert "ML-2026-1002" in contenu(r)
        r = await client.call_tool("commandes_client", {"email_ou_nom": "inconnu@mail.test"})
        assert '"nombre": 0' in contenu(r), "liste vide visible dans le texte"
        r = await client.call_tool("commandes_client", {"email_ou_nom": "%%%"})
        assert '"nombre": 0' in contenu(r), "jokers SQL pris littéralement"
        r = await client.call_tool("commandes_client", {"email_ou_nom": "a"})
        assert r.is_error, "recherche trop courte refusée"
        print("commandes_client : ok, liste vide explicite, jokers neutralisés")

        r = await client.call_tool("suivi_colis", {"numero_suivi": "ETX261002BE"})
        assert "Pris en charge" in contenu(r), contenu(r)
        r = await client.call_tool("suivi_colis", {"numero_suivi": "INCONNU"})
        assert "inconnu" in contenu(r)
        print("suivi_colis : statut lu via l'API HTTP")

        r = await client.call_tool(
            "enregistrer_brouillon", {"identifiant_courriel": "courriel-01", "corps": "Bonjour Lucie,\n\nTest."}
        )
        assert not r.is_error and "b001" in contenu(r)
        r = await client.call_tool("lister_brouillons", {})
        assert "lucie.vermeulen@client.test" in contenu(r)
        print("enregistrer_brouillon / lister_brouillons : b001")

        r = await client.call_tool(
            "poser_etiquette",
            {"identifiant_courriel": "courriel-01", "type_demande": "suivi_livraison", "priorite": "normale",
             "numero_commande": "ML-2026-1002"},
        )
        assert not r.is_error
        r = await client.call_tool("poser_etiquette", {"identifiant_courriel": "courriel-01",
                                                       "type_demande": "rembourser", "priorite": "normale"})
        assert r.is_error, "type de demande hors liste refusé"
        r = await client.call_tool("lister_etiquettes", {})
        assert "suivi_livraison" in contenu(r)
        print("poser_etiquette / lister_etiquettes : ok, valeur hors liste refusée")

        ressources = [str(x.uri) for x in (await client.list_resources()).resources]
        print("Ressources :", ressources)
        texte = (await client.read_resource("boutique://politique-retour")).contents[0].text
        assert "30 jours" in texte
        texte = (await client.read_resource("boutique://modeles-reponse")).contents[0].text
        assert "suivi_statut_connu" in texte

        p = await client.get_prompt("traiter_courriel", {"identifiant": "courriel-07"})
        assert "courriel-07" in p.messages[0].content.text
        print("Prompt : traiter_courriel")

    outbox = list((init_donnees.BOITE / "outbox").glob("*.eml"))
    assert not outbox, "aucun message ne doit être envoyé"


def main() -> None:
    init_donnees.initialiser()
    api = api_suivi.creer_serveur(0)  # port libre choisi par le système
    threading.Thread(target=api.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{api.server_address[1]}"
    try:
        asyncio.run(verifier(url))
    finally:
        api.shutdown()
        init_donnees.initialiser()
    print("OK : kit E06 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
