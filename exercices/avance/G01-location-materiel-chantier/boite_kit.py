r"""Boîte mail fictive des demandes : reprise de ../fausse-boite-mail/mailbox_fake.py.

Contenu de boite/inbox/ (créé par init_donnees.py) :
    demande_01 ... demande_18          courriels des agences à la planification
    contestation_01 ... contestation_07  courriels de clients au service facturation

Structure :
    boite/inbox/       messages reçus
    boite/outbox/      brouillons préparés par l'agent (b001.eml ...), en-tête X-Statut: brouillon
    boite/archive/     messages déplacés
    boite/etat.json    indicateur lu / non lu

L'envoi est désactivé : un brouillon reste dans outbox/ jusqu'à relecture humaine.

Usage en ligne de commande :
    ..\.venv\Scripts\python boite_kit.py lister [--chercher texte]
    ..\.venv\Scripts\python boite_kit.py lire contestation_02
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fausse-boite-mail"))
from mailbox_fake import BoiteMail  # noqa: E402

RACINE = Path(__file__).with_name("boite")
DOMAINE = "brevalocation.test"
ADRESSES = {
    "planification": f"Planification Bréval Location <planification@{DOMAINE}>",
    "facturation": f"Facturation Bréval Location <facturation@{DOMAINE}>",
}


def normaliser_eml(source: Path) -> bytes:
    """Relit un .eml écrit en UTF-8 brut et le réécrit en MIME propre (en-têtes encodés)."""
    brut = Parser(policy=policy.default).parsestr(source.read_bytes().decode("utf-8"))
    corps = brut.get_body(preferencelist=("plain",)) or brut
    # Texte déjà décodé par parsestr : get_content() le réencoderait en ASCII et
    # remplacerait chaque lettre accentuée par U+FFFD.
    texte = corps.get_payload()
    msg = EmailMessage(policy=policy.default)
    for entete in ("From", "To", "Cc", "Date", "Subject"):
        if brut[entete]:
            msg[entete] = str(brut[entete])
    msg["Message-ID"] = f"<{source.stem}@{DOMAINE}>"
    msg.set_content(texte)
    return bytes(msg)


class BoiteDemandes(BoiteMail):
    """Boîte en lecture, avec dépôt de brouillons ; aucun envoi."""

    def __init__(self, racine: Path | str = RACINE):
        super().__init__(racine)

    def envoyer(self, *args, **kwargs):
        raise PermissionError("Envoi désactivé : utiliser preparer_brouillon, la relecture humaine précède tout envoi.")

    def preparer_brouillon(
        self, a: str, sujet: str, corps: str, service: str = "planification", en_reponse_a: str | None = None
    ) -> str:
        """Écrit un brouillon dans outbox/ et renvoie son identifiant (b001 ...)."""
        if service not in ADRESSES:
            raise ValueError(f"Service inconnu : {service}. Valeurs : {', '.join(ADRESSES)}.")
        numero = len(list((self.racine / "outbox").glob("b*.eml"))) + 1
        identifiant = f"b{numero:03d}"
        msg = EmailMessage(policy=policy.default)
        msg["Message-ID"] = f"<{identifiant}@{DOMAINE}>"
        msg["Date"] = format_datetime(datetime.now(timezone.utc).astimezone())
        msg["From"] = ADRESSES[service]
        msg["To"] = a
        msg["X-Statut"] = "brouillon"
        if en_reponse_a:
            origine = self._charger(self._chemin(en_reponse_a))
            msg["In-Reply-To"] = str(origine["Message-ID"])
            msg["References"] = str(origine["Message-ID"])
        msg["Subject"] = sujet
        msg.set_content(corps)
        (self.racine / "outbox" / f"{identifiant}.eml").write_bytes(bytes(msg))
        return identifiant


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Boîte mail fictive des demandes")
    sous = parser.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("lister")
    p.add_argument("--dossier", default="inbox")
    p.add_argument("--chercher")
    p = sous.add_parser("lire")
    p.add_argument("identifiant")
    args = parser.parse_args()
    boite = BoiteDemandes()
    if args.commande == "lister":
        for r in boite.lister(args.dossier, chercher=args.chercher):
            print(f"{r['id']:<16} {r['date'][:16]}  {r['de'][:40]:<40}  {r['sujet']}")
    else:
        r = boite.lire(args.identifiant)
        print(f"De : {r['de']}\nÀ : {r['a']}\nDate : {r['date']}\nSujet : {r['sujet']}\n\n{r['corps']}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _cli()
