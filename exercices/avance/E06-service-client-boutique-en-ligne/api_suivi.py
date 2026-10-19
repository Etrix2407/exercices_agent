"""API HTTP locale simulant le suivi du transporteur (bibliothèque standard uniquement).

Points d'accès :
    GET /suivi/<numero_suivi>   statut, dernière étape, date estimée (404 si numéro inconnu)
    GET /sante                  vérification que l'API répond

Usage :
    ..\\.venv\\Scripts\\python api_suivi.py [--port 8765]
Données : donnees/suivi_transporteur.json, relu à chaque requête.
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

DONNEES = Path(__file__).resolve().parent / "donnees" / "suivi_transporteur.json"
PORT_DEFAUT = 8765


def chercher(numero: str) -> dict | None:
    donnees = json.loads(DONNEES.read_text(encoding="utf-8"))
    for suivi in donnees["suivis"]:
        if suivi["numero_suivi"].upper() == numero.strip().upper():
            return {"transporteur": donnees["transporteur"], **suivi}
    return None


class Gestionnaire(BaseHTTPRequestHandler):
    def _repondre(self, code: int, contenu: dict) -> None:
        corps = json.dumps(contenu, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self) -> None:  # noqa: N802 (nom imposé par http.server)
        chemin = unquote(self.path.split("?", 1)[0]).rstrip("/")
        if chemin == "/sante":
            self._repondre(200, {"etat": "ok"})
        elif chemin.startswith("/suivi/"):
            resultat = chercher(chemin.removeprefix("/suivi/"))
            if resultat:
                self._repondre(200, resultat)
            else:
                self._repondre(404, {"erreur": "numéro de suivi inconnu"})
        else:
            self._repondre(404, {"erreur": "chemin inconnu", "chemins": ["/suivi/<numero_suivi>", "/sante"]})

    def log_message(self, format, *args) -> None:
        # Une ligne par requête sur la sortie d'erreur
        sys.stderr.write("api_suivi : " + format % args + "\n")


def creer_serveur(port: int = PORT_DEFAUT) -> ThreadingHTTPServer:
    # Écoute sur 127.0.0.1 uniquement : l'API n'est pas joignable depuis le réseau
    return ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="API locale de suivi transporteur")
    parser.add_argument("--port", type=int, default=PORT_DEFAUT)
    args = parser.parse_args()
    serveur = creer_serveur(args.port)
    print(f"API de suivi sur http://127.0.0.1:{args.port}/suivi/<numero_suivi> (Ctrl+C pour arrêter)", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
