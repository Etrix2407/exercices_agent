r"""Serveur SMTP local (facultatif) qui dépose les messages reçus dans la fausse boîte.

Permet de tester un agent qui envoie ses mails avec smtplib, sans compte réel.
Aucune authentification, écoute uniquement sur 127.0.0.1.

Prérequis : aiosmtpd, installé dans le venv du palier avancé (requirements.txt).

Usage (depuis ce dossier) :
    ..\.venv\Scripts\python smtp_local.py                    # port 8025, dépôt dans boite/outbox
    ..\.venv\Scripts\python smtp_local.py --dossier inbox    # simuler l'arrivée de nouveaux mails

Côté agent :
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = "service.clients@norvel-fournitures.example"
    msg["To"] = "claire.lemaire@boulangerie-lemaire.example"
    msg["Subject"] = "Confirmation"
    msg.set_content("Bonjour, ...")
    with smtplib.SMTP("127.0.0.1", 8025) as s:
        s.send_message(msg)
"""

import argparse
import json
import sys
import time
from pathlib import Path

from aiosmtpd.controller import Controller

RACINE_DEFAUT = Path(__file__).with_name("boite")


class Depot:
    """Gestionnaire aiosmtpd : écrit chaque message reçu en .eml."""

    def __init__(self, racine: Path, dossier: str):
        self.racine = racine
        self.dossier = racine / dossier
        self.prefixe = "e" if dossier == "outbox" else "m"

    def _prochain_identifiant(self) -> str:
        numeros = [int(p.stem[1:]) for p in self.dossier.glob(f"{self.prefixe}*.eml") if p.stem[1:].isdigit()]
        return f"{self.prefixe}{max(numeros, default=0) + 1:03d}"

    async def handle_DATA(self, server, session, envelope):
        identifiant = self._prochain_identifiant()
        (self.dossier / f"{identifiant}.eml").write_bytes(envelope.original_content or envelope.content)
        if self.prefixe == "m":
            # Nouveau message entrant : non lu
            etat_chemin = self.racine / "etat.json"
            etat = json.loads(etat_chemin.read_text(encoding="utf-8")) if etat_chemin.exists() else {}
            etat[identifiant] = {"lu": False}
            etat_chemin.write_text(json.dumps(etat, indent=2), encoding="utf-8")
        print(f"{identifiant} : {envelope.mail_from} -> {', '.join(envelope.rcpt_tos)}", flush=True)
        return "250 Message accepted"


def demarrer(racine: Path = RACINE_DEFAUT, dossier: str = "outbox", port: int = 8025) -> Controller:
    controleur = Controller(Depot(racine, dossier), hostname="127.0.0.1", port=port)
    controleur.start()
    return controleur


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        # Sortie UTF-8 et ligne par ligne, y compris redirigée vers un fichier ou un autre processus.
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    parser = argparse.ArgumentParser(description="Serveur SMTP local vers la fausse boîte")
    parser.add_argument("--port", type=int, default=8025)
    parser.add_argument("--dossier", default="outbox", choices=["outbox", "inbox"])
    parser.add_argument("--racine", type=Path, default=RACINE_DEFAUT)
    args = parser.parse_args()
    controleur = demarrer(args.racine, args.dossier, args.port)
    print(f"SMTP local sur 127.0.0.1:{args.port}, dépôt dans {args.racine / args.dossier}. Ctrl+C pour arrêter.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controleur.stop()


if __name__ == "__main__":
    main()
