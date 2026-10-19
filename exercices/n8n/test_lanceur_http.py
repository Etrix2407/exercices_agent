"""Vérifie le lanceur HTTP : démarre l'API de suivi et le serveur, appelle trois outils, arrête tout.

Usage (depuis ce dossier) :
    ..\avance\.venv\Scripts\python test_lanceur_http.py
Les données du kit E06 ne sont pas modifiées (outils en lecture seule uniquement).
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from mcp import Client

ICI = Path(__file__).resolve().parent
KIT = ICI.parent / "avance" / "E06-service-client-boutique-en-ligne"
PORT_API, PORT_MCP = 8766, 8001


def attendre(url: str, delai: float = 15) -> None:
    fin = time.time() + delai
    while time.time() < fin:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return  # le serveur répond, même avec un code d'erreur
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"Pas de réponse : {url}")


def texte(resultat) -> str:
    return "\n".join(getattr(c, "text", "") for c in resultat.content) + json.dumps(
        resultat.structured_content, ensure_ascii=False
    )


async def verifier() -> None:
    async with Client(f"http://127.0.0.1:{PORT_MCP}/mcp") as client:
        noms = sorted(o.name for o in (await client.list_tools()).tools)
        print("Outils :", ", ".join(noms))
        r = await client.call_tool("chercher_commande", {"numero": "ML-2026-1002"})
        assert "ETX261002BE" in texte(r)
        r = await client.call_tool("suivi_colis", {"numero_suivi": "ETX261002BE"})
        assert "Pris en charge" in texte(r), texte(r)
        r = await client.call_tool("lister_courriels", {"non_lus": True})
        assert not r.is_error
        print("chercher_commande, suivi_colis, lister_courriels : ok")


def main() -> None:
    py = sys.executable
    api = subprocess.Popen([py, "api_suivi.py", "--port", str(PORT_API)], cwd=KIT)
    mcp = subprocess.Popen(
        [py, str(ICI / "lanceur_http_e06.py"), "--port", str(PORT_MCP)],
        env={**os.environ, "SUIVI_API_URL": f"http://127.0.0.1:{PORT_API}"},
    )
    try:
        attendre(f"http://127.0.0.1:{PORT_API}/suivi/ETX261002BE")
        attendre(f"http://127.0.0.1:{PORT_MCP}/mcp")
        asyncio.run(verifier())
        print("OK : serveur E06 joignable en Streamable HTTP")
    finally:
        for p in (mcp, api):
            p.terminate()
            p.wait(timeout=10)


if __name__ == "__main__":
    main()
