"""Lance le serveur MCP du kit E06 en Streamable HTTP, pour le nœud MCP Client Tool de n8n.

Le kit n'est pas modifié : le module serveur_mcp.py est importé tel quel, seul le transport change.

Usage (depuis ce dossier, venv du palier avancé) :
    ..\avance\.venv\Scripts\python lanceur_http_e06.py [--port 8000]
Point d'accès : http://127.0.0.1:8000/mcp
L'API de suivi (api_suivi.py --port 8765) doit tourner à côté, comme pour le transport stdio.
"""

import argparse
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "avance" / "E06-service-client-boutique-en-ligne"
sys.path.insert(0, str(KIT))

from serveur_mcp import serveur  # noqa: E402  (import après ajout du kit au chemin)


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--host", default="127.0.0.1")
    parseur.add_argument("--port", type=int, default=8000)
    args = parseur.parse_args()
    print(f"Serveur MCP E06 : http://{args.host}:{args.port}/mcp", flush=True)
    # stateless_http : aucune session côté serveur, chaque requête se suffit à elle-même
    serveur.run("streamable-http", host=args.host, port=args.port, stateless_http=True)


if __name__ == "__main__":
    main()
