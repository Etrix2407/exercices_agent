"""Fausse boîte mail locale : messages .eml dans des dossiers, état dans etat.json.

Structure :
    boite/inbox/      messages reçus (m001.eml ...)
    boite/outbox/     messages « envoyés » par l'agent (e001.eml ...)
    boite/archive/    messages déplacés
    boite/etat.json   indicateur lu / non lu par identifiant

Usage en bibliothèque :
    from mailbox_fake import BoiteMail
    boite = BoiteMail()
    boite.lister(non_lus=True)
    boite.lire("m003")
    boite.envoyer("client@exemple.example", "Objet", "Texte", en_reponse_a="m003")

Usage en ligne de commande :
    py -3.12 mailbox_fake.py lister [--non-lus] [--dossier outbox] [--chercher texte]
    py -3.12 mailbox_fake.py lire m003
    py -3.12 mailbox_fake.py envoyer --a x@y.example --sujet "Objet" --corps "Texte" [--reponse-a m003]
    py -3.12 mailbox_fake.py marquer-lu m003
    py -3.12 mailbox_fake.py archiver m021
    py -3.12 mailbox_fake.py piece m010 CV_Hugo_Lambotte.txt
    py -3.12 mailbox_fake.py reinitialiser
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

RACINE_DEFAUT = Path(__file__).with_name("boite")
ADRESSE_BOITE = "Service clients Norvel <service.clients@norvel-fournitures.example>"
DOSSIERS = ("inbox", "outbox", "archive")


class BoiteMail:
    def __init__(self, racine: Path | str = RACINE_DEFAUT):
        self.racine = Path(racine)
        if not (self.racine / "inbox").exists():
            raise FileNotFoundError(f"Boîte absente : {self.racine}. Lancer generer_boite.py.")
        self._etat_chemin = self.racine / "etat.json"

    # --- état lu / non lu -------------------------------------------------
    def _etat(self) -> dict:
        if self._etat_chemin.exists():
            return json.loads(self._etat_chemin.read_text(encoding="utf-8"))
        return {}

    def _sauver_etat(self, etat: dict) -> None:
        self._etat_chemin.write_text(json.dumps(etat, indent=2), encoding="utf-8")

    # --- accès aux fichiers -----------------------------------------------
    def _chemin(self, identifiant: str) -> Path:
        # Un identifiant est un nom de fichier sans extension : pas de chemin relatif.
        if not identifiant or any(c in identifiant for c in ("/", "\\", ":")) or ".." in identifiant:
            raise KeyError(f"Identifiant invalide : {identifiant}")
        for dossier in DOSSIERS:
            p = self.racine / dossier / f"{identifiant}.eml"
            if p.exists():
                return p
        raise KeyError(f"Message introuvable : {identifiant}")

    @staticmethod
    def _charger(chemin: Path) -> EmailMessage:
        with chemin.open("rb") as f:
            return BytesParser(policy=policy.default).parse(f)

    def _resume(self, chemin: Path, msg: EmailMessage, etat: dict) -> dict:
        identifiant = chemin.stem
        return {
            "id": identifiant,
            "dossier": chemin.parent.name,
            "date": parsedate_to_datetime(msg["Date"]).isoformat() if msg["Date"] else None,
            "de": str(msg["From"]),
            "a": str(msg["To"]),
            "sujet": str(msg["Subject"]),
            "lu": etat.get(identifiant, {}).get("lu", chemin.parent.name == "outbox"),
            "pieces_jointes": [p.get_filename() for p in msg.iter_attachments()],
        }

    # --- opérations ---------------------------------------------------------
    def lister(
        self,
        dossier: str = "inbox",
        non_lus: bool = False,
        expediteur: str | None = None,
        chercher: str | None = None,
    ) -> list[dict]:
        """Liste les messages d'un dossier, du plus ancien au plus récent."""
        if dossier not in DOSSIERS:
            raise ValueError(f"Dossier inconnu : {dossier}")
        etat = self._etat()
        resultats = []
        for chemin in sorted((self.racine / dossier).glob("*.eml")):
            msg = self._charger(chemin)
            r = self._resume(chemin, msg, etat)
            if non_lus and r["lu"]:
                continue
            if expediteur and expediteur.lower() not in r["de"].lower():
                continue
            if chercher:
                corps = msg.get_body(preferencelist=("plain",))
                texte = (r["sujet"] + "\n" + (corps.get_content() if corps else "")).lower()
                if chercher.lower() not in texte:
                    continue
            resultats.append(r)
        resultats.sort(key=lambda r: r["date"] or "")
        return resultats

    def lire(self, identifiant: str, marquer_lu: bool = False) -> dict:
        """Renvoie en-têtes, corps texte et noms des pièces jointes."""
        chemin = self._chemin(identifiant)
        msg = self._charger(chemin)
        r = self._resume(chemin, msg, self._etat())
        corps = msg.get_body(preferencelist=("plain",))
        r["corps"] = corps.get_content() if corps else ""
        r["message_id"] = str(msg["Message-ID"])
        r["en_reponse_a"] = str(msg["In-Reply-To"]) if msg["In-Reply-To"] else None
        if marquer_lu:
            self.marquer_lu(identifiant)
            r["lu"] = True
        return r

    def piece_jointe(self, identifiant: str, nom: str) -> bytes:
        msg = self._charger(self._chemin(identifiant))
        for p in msg.iter_attachments():
            if p.get_filename() == nom:
                return p.get_payload(decode=True)
        raise KeyError(f"Pièce jointe introuvable : {nom}")

    def marquer_lu(self, identifiant: str, lu: bool = True) -> None:
        self._chemin(identifiant)  # vérifie l'existence
        etat = self._etat()
        etat.setdefault(identifiant, {})["lu"] = lu
        self._sauver_etat(etat)

    def archiver(self, identifiant: str) -> None:
        chemin = self._chemin(identifiant)
        chemin.rename(self.racine / "archive" / chemin.name)

    def envoyer(
        self,
        a: str,
        sujet: str,
        corps: str,
        cc: str | None = None,
        en_reponse_a: str | None = None,
    ) -> str:
        """« Envoie » un message : l'écrit dans outbox/ et renvoie son identifiant."""
        msg = EmailMessage(policy=policy.default)
        numero = len(list((self.racine / "outbox").glob("e*.eml"))) + 1
        identifiant = f"e{numero:03d}"
        msg["Message-ID"] = f"<{identifiant}@norvel-fournitures.example>"
        msg["Date"] = format_datetime(datetime.now(timezone.utc).astimezone())
        msg["From"] = ADRESSE_BOITE
        msg["To"] = a
        if cc:
            msg["Cc"] = cc
        if en_reponse_a:
            origine = self._charger(self._chemin(en_reponse_a))
            msg["In-Reply-To"] = str(origine["Message-ID"])
            msg["References"] = str(origine["Message-ID"])
        msg["Subject"] = sujet
        msg.set_content(corps)
        (self.racine / "outbox" / f"{identifiant}.eml").write_bytes(bytes(msg))
        return identifiant


# Description des opérations au format JSON Schema, à reprendre comme
# définitions d'outils (tool use) dans un agent.
OUTILS = [
    {
        "name": "lister_mails",
        "description": "Liste les mails d'un dossier (inbox, outbox, archive) avec filtres optionnels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dossier": {"type": "string", "enum": list(DOSSIERS), "default": "inbox"},
                "non_lus": {"type": "boolean", "default": False},
                "expediteur": {"type": "string", "description": "Fragment de l'adresse ou du nom"},
                "chercher": {"type": "string", "description": "Texte à chercher dans le sujet et le corps"},
            },
        },
    },
    {
        "name": "lire_mail",
        "description": "Lit un mail complet à partir de son identifiant (ex. m003).",
        "input_schema": {
            "type": "object",
            "properties": {"identifiant": {"type": "string"}, "marquer_lu": {"type": "boolean", "default": False}},
            "required": ["identifiant"],
        },
    },
    {
        "name": "envoyer_mail",
        "description": "Envoie un mail (écrit dans outbox). Renvoie l'identifiant du message envoyé.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "sujet": {"type": "string"},
                "corps": {"type": "string"},
                "cc": {"type": "string"},
                "en_reponse_a": {"type": "string", "description": "Identifiant du mail auquel répondre"},
            },
            "required": ["a", "sujet", "corps"],
        },
    },
    {
        "name": "marquer_lu",
        "description": "Marque un mail comme lu.",
        "input_schema": {
            "type": "object",
            "properties": {"identifiant": {"type": "string"}},
            "required": ["identifiant"],
        },
    },
]


def executer_outil(boite: BoiteMail, nom: str, arguments: dict):
    """Aiguillage simple nom d'outil -> méthode, pour une boucle d'agent."""
    table = {
        "lister_mails": boite.lister,
        "lire_mail": boite.lire,
        "envoyer_mail": boite.envoyer,
        "marquer_lu": boite.marquer_lu,
    }
    return table[nom](**arguments)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Fausse boîte mail locale")
    parser.add_argument("--racine", type=Path, default=RACINE_DEFAUT)
    sous = parser.add_subparsers(dest="commande", required=True)

    p = sous.add_parser("lister")
    p.add_argument("--dossier", default="inbox", choices=DOSSIERS)
    p.add_argument("--non-lus", action="store_true")
    p.add_argument("--expediteur")
    p.add_argument("--chercher")

    p = sous.add_parser("lire")
    p.add_argument("identifiant")
    p.add_argument("--marquer-lu", action="store_true")

    p = sous.add_parser("envoyer")
    p.add_argument("--a", required=True)
    p.add_argument("--sujet", required=True)
    p.add_argument("--corps", required=True)
    p.add_argument("--cc")
    p.add_argument("--reponse-a")

    p = sous.add_parser("marquer-lu")
    p.add_argument("identifiant")

    p = sous.add_parser("archiver")
    p.add_argument("identifiant")

    p = sous.add_parser("piece")
    p.add_argument("identifiant")
    p.add_argument("nom")

    sous.add_parser("reinitialiser")

    args = parser.parse_args()
    if args.commande == "reinitialiser":
        from generer_boite import generer

        generer(args.racine)
        return

    boite = BoiteMail(args.racine)
    if args.commande == "lister":
        for r in boite.lister(args.dossier, args.non_lus, args.expediteur, args.chercher):
            marque = " " if r["lu"] else "*"
            pj = f" [{len(r['pieces_jointes'])} PJ]" if r["pieces_jointes"] else ""
            print(f"{marque} {r['id']}  {r['date'][:16]}  {r['de'][:45]:<45}  {r['sujet']}{pj}")
    elif args.commande == "lire":
        r = boite.lire(args.identifiant, args.marquer_lu)
        print(f"De : {r['de']}\nÀ : {r['a']}\nDate : {r['date']}\nSujet : {r['sujet']}")
        if r["pieces_jointes"]:
            print("Pièces jointes : " + ", ".join(r["pieces_jointes"]))
        print()
        print(r["corps"])
    elif args.commande == "envoyer":
        print(boite.envoyer(args.a, args.sujet, args.corps, args.cc, args.reponse_a))
    elif args.commande == "marquer-lu":
        boite.marquer_lu(args.identifiant)
    elif args.commande == "archiver":
        boite.archiver(args.identifiant)
    elif args.commande == "piece":
        sys.stdout.buffer.write(boite.piece_jointe(args.identifiant, args.nom))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _cli()
