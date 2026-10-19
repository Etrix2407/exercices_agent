"""Vérification rapide de la fausse boîte mail et du serveur SMTP local."""

import smtplib
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

from generer_boite import generer
from mailbox_fake import OUTILS, BoiteMail, executer_outil

sys.stdout.reconfigure(encoding="utf-8")

with tempfile.TemporaryDirectory() as tmp:
    racine = Path(tmp) / "boite"
    generer(racine)
    boite = BoiteMail(racine)

    tous = boite.lister()
    assert len(tous) == 30, len(tous)
    assert len(boite.lister(non_lus=True)) == 29
    assert [r["id"] for r in boite.lister(chercher="FAC-2026-0072")] == ["m019"]

    m = boite.lire("m023", marquer_lu=True)
    assert m["pieces_jointes"] == ["bon_commande_octobre.csv"]
    assert b"PRD-118" in boite.piece_jointe("m023", "bon_commande_octobre.csv")
    assert len(boite.lister(non_lus=True)) == 28

    ident = executer_outil(boite, "envoyer_mail", {"a": "x@y.example", "sujet": "Re: test", "corps": "ok", "en_reponse_a": "m002"})
    envoye = boite.lire(ident)
    assert envoye["dossier"] == "outbox" and envoye["en_reponse_a"] == "<m002@boite-fictive.example>"
    assert {o["name"] for o in OUTILS} == {"lister_mails", "lire_mail", "envoyer_mail", "marquer_lu"}

    try:
        boite.lire("../inbox/m001")
        raise AssertionError("identifiant avec chemin relatif accepté")
    except KeyError:
        pass

    boite.archiver("m021")
    assert len(boite.lister()) == 29 and len(boite.lister("archive")) == 1

    try:
        from smtp_local import demarrer
    except ImportError:
        print("aiosmtpd absent : test SMTP ignoré")
    else:
        ctl = demarrer(racine, "outbox", 8026)
        try:
            msg = EmailMessage()
            msg["From"] = "service.clients@norvel-fournitures.example"
            msg["To"] = "claire.lemaire@boulangerie-lemaire.example"
            msg["Subject"] = "Confirmation SMTP"
            msg.set_content("Commande confirmée.")
            with smtplib.SMTP("127.0.0.1", 8026) as s:
                s.send_message(msg)
        finally:
            ctl.stop()
        sujets = [r["sujet"] for r in boite.lister("outbox")]
        assert "Confirmation SMTP" in sujets, sujets

print("OK : boîte mail fonctionnelle")
