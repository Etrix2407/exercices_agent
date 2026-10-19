"""Client MCP de test : lance serveur.py en stdio et appelle chaque élément exposé.

Usage :
    .venv\\Scripts\\python client_test.py
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

SERVEUR = Path(__file__).with_name("serveur.py")


def texte(resultat) -> str:
    return "\n".join(getattr(c, "text", "") for c in resultat.content)


async def main() -> None:
    parametres = StdioServerParameters(command=sys.executable, args=[str(SERVEUR)])
    async with Client(parametres) as client:
        print("Protocole :", client.protocol_version)

        outils = await client.list_tools()
        noms = sorted(o.name for o in outils.tools)
        print("Outils :", ", ".join(noms))
        assert {"rechercher_clients", "factures_impayees", "requete_sql"} <= set(noms)

        r = await client.call_tool("rechercher_clients", {"texte": "Namur"})
        print("rechercher_clients(Namur) :", r.structured_content or texte(r))
        assert not r.is_error

        r = await client.call_tool("rechercher_clients", {"texte": "%"})
        print("rechercher_clients(%) :", texte(r))
        assert '"nombre": 0' in texte(r) + json.dumps(r.structured_content), "joker % pris littéralement"

        r = await client.call_tool("factures_impayees", {"code_client": "CLI-0009", "en_retard_seulement": True})
        print("factures_impayees(CLI-0009) :", texte(r)[:300])
        assert "FAC-2026-0073" in texte(r) + json.dumps(r.structured_content)

        r = await client.call_tool("detail_commande", {"numero": "CMD-2026-0120"})
        assert "Destructeur" in texte(r) + json.dumps(r.structured_content, ensure_ascii=False)

        r = await client.call_tool("stocks_sous_seuil", {})
        assert "PRD-123" in texte(r) + json.dumps(r.structured_content)

        r = await client.call_tool("requete_sql", {"sql": "SELECT statut, COUNT(*) AS n FROM tickets GROUP BY statut"})
        print("requete_sql :", texte(r))
        assert not r.is_error

        r = await client.call_tool("requete_sql", {"sql": "DELETE FROM clients"})
        print("requete_sql(DELETE) refusée :", r.is_error)
        assert r.is_error

        ressources = await client.list_resources()
        print("Ressources :", [str(x.uri) for x in ressources.resources])
        contenu = await client.read_resource("schema://entreprise")
        assert "CREATE TABLE factures" in contenu.contents[0].text

        prompts = await client.list_prompts()
        print("Prompts :", [p.name for p in prompts.prompts])
        p = await client.get_prompt("relance_factures", {"code_client": "CLI-0009"})
        assert "CLI-0009" in p.messages[0].content.text

    print("OK : serveur MCP fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
