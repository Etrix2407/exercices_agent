"""Boîte mail du kit : reprise de ../fausse-boite-mail/mailbox_fake.py, avec un dossier de brouillons.

Structure :
    boite/inbox/       messages reçus (copiés depuis donnees/eml par init_donnees.py)
    boite/brouillons/  brouillons déposés par l'agent (b001.eml ...)
    boite/archive/     messages déplacés
    boite/etat.json    indicateur lu / non lu
    boite/etiquettes.json  étiquettes posées par l'agent (facultatif)

L'envoi est désactivé : un brouillon reste dans boite/brouillons/ jusqu'à relecture humaine.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

# Module générique de la fausse boîte mail, dossier voisin du palier avancé
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fausse-boite-mail"))
from mailbox_fake import BoiteMail  # noqa: E402


def normaliser_eml(source: Path, domaine: str) -> EmailMessage:
    """Relit un .eml (UTF-8, en-têtes parfois sans Content-Type) et le réécrit en MIME propre."""
    brut = Parser(policy=policy.default).parsestr(source.read_bytes().decode("utf-8"))
    corps = brut.get_body(preferencelist=("plain",)) or brut
    texte = corps.get_payload()
    msg = EmailMessage(policy=policy.default)
    for entete in ("From", "To", "Cc", "Date", "Subject"):
        if brut[entete]:
            msg[entete] = str(brut[entete])
    msg["Message-ID"] = str(brut["Message-ID"]) if brut["Message-ID"] else f"<{source.stem}@{domaine}>"
    msg.set_content(texte)
    return msg


def charger_boite(source: Path, racine: Path, domaine: str) -> int:
    """Recrée la boîte à partir des .eml du dossier source. Renvoie le nombre de messages."""
    if racine.exists():
        shutil.rmtree(racine)
    for dossier in ("inbox", "outbox", "archive", "brouillons"):
        (racine / dossier).mkdir(parents=True)
    etat = {}
    for chemin in sorted(source.glob("*.eml")):
        msg = normaliser_eml(chemin, domaine)
        (racine / "inbox" / chemin.name).write_bytes(bytes(msg))
        etat[chemin.stem] = {"lu": False}
    (racine / "etat.json").write_text(json.dumps(etat, indent=2), encoding="utf-8")
    return len(etat)


class BoiteKit(BoiteMail):
    def __init__(self, racine: Path | str, adresse: str):
        super().__init__(racine)
        self.adresse = adresse
        (self.racine / "brouillons").mkdir(exist_ok=True)

    def _chemin(self, identifiant: str) -> Path:
        # Un identifiant est un nom de fichier sans extension : aucun chemin accepté (« ../ », « \ »)
        if not identifiant or identifiant.startswith(".") or Path(identifiant).name != identifiant:
            raise KeyError(f"Identifiant invalide : {identifiant!r} (nom de message sans chemin ni extension)")
        return super()._chemin(identifiant)

    def envoyer(self, *args, **kwargs):
        raise PermissionError("Envoi désactivé : enregistrer un brouillon.")

    def enregistrer_brouillon(
        self,
        en_reponse_a: str,
        corps: str,
        sujet: str | None = None,
        pieces: dict[str, str] | None = None,
        a: str | None = None,
    ) -> dict:
        """Écrit un brouillon de réponse au message en_reponse_a dans brouillons/.

        Destinataire : a, sinon l'expéditeur du message d'origine. pieces : {nom_fichier: contenu texte}.
        """
        origine = self._charger(self._chemin(en_reponse_a))
        numero = len(list((self.racine / "brouillons").glob("b*.eml"))) + 1
        identifiant = f"b{numero:03d}"
        msg = EmailMessage(policy=policy.default)
        msg["Message-ID"] = f"<{identifiant}.{en_reponse_a}@brouillon.example>"
        msg["Date"] = format_datetime(datetime.now(timezone.utc).astimezone())
        msg["From"] = self.adresse
        msg["To"] = a or str(origine["From"])
        msg["Subject"] = sujet or f"Re: {origine['Subject']}"
        msg["In-Reply-To"] = str(origine["Message-ID"])
        msg["References"] = str(origine["Message-ID"])
        msg["X-Brouillon-Pour"] = en_reponse_a
        msg.set_content(corps)
        for nom, contenu in (pieces or {}).items():
            sous_type = "markdown" if nom.endswith(".md") else "plain"
            msg.add_attachment(contenu, subtype=sous_type, filename=nom)
        (self.racine / "brouillons" / f"{identifiant}.eml").write_bytes(bytes(msg))
        return {"brouillon": identifiant, "a": msg["To"], "sujet": msg["Subject"],
                "pieces_jointes": list(pieces or {})}

    def lister_brouillons(self) -> list[dict]:
        resultats = []
        for chemin in sorted((self.racine / "brouillons").glob("b*.eml")):
            msg = self._charger(chemin)
            resultats.append({
                "id": chemin.stem,
                "pour": str(msg["X-Brouillon-Pour"]),
                "a": str(msg["To"]),
                "sujet": str(msg["Subject"]),
                "date": parsedate_to_datetime(msg["Date"]).isoformat(),
                "pieces_jointes": [p.get_filename() for p in msg.iter_attachments()],
            })
        return resultats

    def lire_brouillon(self, identifiant: str) -> dict:
        chemin = self.racine / "brouillons" / f"{identifiant}.eml"
        if not chemin.exists():
            raise KeyError(f"Brouillon introuvable : {identifiant}")
        msg = self._charger(chemin)
        corps = msg.get_body(preferencelist=("plain",))
        return {
            "id": identifiant,
            "a": str(msg["To"]),
            "sujet": str(msg["Subject"]),
            "corps": corps.get_content() if corps else "",
            "pieces_jointes": {p.get_filename(): p.get_content() for p in msg.iter_attachments()},
        }

    # --- étiquettes (type, priorité, escalade...) --------------------------
    def poser_etiquette(self, identifiant: str, **champs) -> dict:
        self._chemin(identifiant)  # vérifie l'existence
        chemin = self.racine / "etiquettes.json"
        etiquettes = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
        etiquettes[identifiant] = {k: v for k, v in champs.items() if v is not None}
        chemin.write_text(json.dumps(etiquettes, indent=2, ensure_ascii=False), encoding="utf-8")
        return {identifiant: etiquettes[identifiant]}

    def etiquettes(self) -> dict:
        chemin = self.racine / "etiquettes.json"
        return json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
