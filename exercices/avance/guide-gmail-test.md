# Connecter un agent à un compte Gmail de test

Objectif : donner à un agent l'accès en lecture (IMAP) et en envoi (SMTP) à une boîte Gmail personnelle créée pour les tests, avec un mot de passe d'application. Aucun projet Google Cloud, aucune console d'administration, aucun OAuth.

Sources vérifiées le 14/10/2026 :

- Mots de passe d'application : https://support.google.com/accounts/answer/185833
- IMAP toujours activé : https://support.google.com/mail/answer/7126229
- Serveurs IMAP et SMTP : https://developers.google.com/workspace/gmail/imap/imap-smtp
- Limites d'envoi : https://support.google.com/mail/answer/22839

## 1. Prérequis

- Un compte Gmail personnel dédié aux essais (pas un compte professionnel ou scolaire : l'option mot de passe d'application n'y est pas disponible).
- La validation en deux étapes activée sur ce compte. Sans elle, la page des mots de passe d'application n'apparaît pas.
- Python 3.12 ; seuls `imaplib`, `smtplib` et `email` de la bibliothèque standard sont utilisés.

L'option mot de passe d'application est indisponible dans trois cas : validation en deux étapes configurée uniquement avec des clés de sécurité, compte géré par une organisation, Protection Avancée activée.

## 2. Activer la validation en deux étapes

1. Ouvrir https://myaccount.google.com/security avec le compte de test.
2. Dans la partie consacrée à la connexion à Google, ouvrir « Validation en deux étapes » et suivre l'assistant (numéro de téléphone ou application d'authentification).
3. Ne pas se limiter à une clé de sécurité comme seul second facteur.

## 3. Créer le mot de passe d'application

1. Ouvrir https://myaccount.google.com/apppasswords (une reconnexion peut être demandée).
2. Saisir un nom libre, par exemple `agent-test`, puis « Créer ».
3. Copier le code de 16 caractères affiché. Il n'est montré qu'une fois. Les espaces d'affichage peuvent être retirés.
4. Le stocker hors du code source, dans des variables d'environnement :

```powershell
# PowerShell, session courante
$env:GMAIL_ADRESSE = "compte.test@gmail.com"
$env:GMAIL_MDP_APP = "abcdabcdabcdabcd"
```

Le mot de passe d'application est révoqué à chaque changement du mot de passe du compte Google : en recréer un dans ce cas. Il peut aussi être supprimé à tout moment depuis la même page.

## 4. Vérifier IMAP

IMAP est toujours activé sur Gmail depuis janvier 2025 : il n'y a plus de réglage à modifier dans Gmail.

Paramètres :

| Usage | Serveur | Port | Chiffrement |
|---|---|---|---|
| Lecture (IMAP) | `imap.gmail.com` | 993 | SSL/TLS |
| Envoi (SMTP) | `smtp.gmail.com` | 465 | SSL/TLS |
| Envoi (SMTP) | `smtp.gmail.com` | 587 | STARTTLS |

Identifiant : adresse Gmail complète. Mot de passe : le mot de passe d'application, jamais le mot de passe du compte.

## 5. Code minimal

```python
"""Lecture IMAP et envoi SMTP sur un compte Gmail de test."""

import email
import imaplib
import os
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage

ADRESSE = os.environ["GMAIL_ADRESSE"]
MDP_APP = os.environ["GMAIL_MDP_APP"]


def lister_non_lus(maximum: int = 10) -> list[dict]:
    """Renvoie les derniers mails non lus de la boîte de réception sans les marquer lus."""
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
        imap.login(ADRESSE, MDP_APP)
        imap.select("INBOX", readonly=True)  # lecture seule : aucun indicateur modifié
        _, donnees = imap.uid("SEARCH", None, "UNSEEN")
        uids = donnees[0].split()[-maximum:]
        resultats = []
        for uid in uids:
            # BODY.PEEK évite de positionner l'indicateur \Seen
            _, parties = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parties[0][1])
            corps = ""
            for partie in msg.walk():
                if partie.get_content_type() == "text/plain" and not partie.get_filename():
                    corps = partie.get_payload(decode=True).decode(partie.get_content_charset() or "utf-8", "replace")
                    break
            resultats.append(
                {
                    "uid": uid.decode(),
                    "de": str(make_header(decode_header(msg.get("From", "")))),
                    "sujet": str(make_header(decode_header(msg.get("Subject", "")))),
                    "date": msg.get("Date"),
                    "corps": corps[:2000],
                }
            )
        return resultats


def marquer_lu(uid: str) -> None:
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
        imap.login(ADRESSE, MDP_APP)
        imap.select("INBOX")
        imap.uid("STORE", uid, "+FLAGS", r"(\Seen)")


def envoyer(destinataire: str, sujet: str, corps: str) -> None:
    msg = EmailMessage()
    msg["From"] = ADRESSE
    msg["To"] = destinataire
    msg["Subject"] = sujet
    msg.set_content(corps)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(ADRESSE, MDP_APP)
        smtp.send_message(msg)


if __name__ == "__main__":
    for m in lister_non_lus(5):
        print(m["uid"], m["de"], "|", m["sujet"])
    envoyer(ADRESSE, "Test agent", "Message envoyé par le script de test.")
```

Variante STARTTLS sur le port 587 :

```python
with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
    smtp.starttls()
    smtp.login(ADRESSE, MDP_APP)
    smtp.send_message(msg)
```

Recherche avec la syntaxe de la barre de recherche Gmail (extension IMAP `X-GM-RAW`) :

```python
_, donnees = imap.uid("SEARCH", "X-GM-RAW", '"from:fournisseur.example newer_than:7d"')
```

## 6. Brancher sur un agent

- Exposer ces fonctions comme outils sous les noms et schémas de `fausse-boite-mail/mailbox_fake.py` (`lister_mails`, `lire_mail`, `envoyer_mail`, `marquer_lu`) : l'agent développé sur la fausse boîte passe sur Gmail en changeant seulement l'implémentation.
- Commencer par la lecture seule (`select(..., readonly=True)`), ajouter l'envoi ensuite.
- Pour l'envoi, faire valider chaque mail par un humain ou restreindre les destinataires à une liste fixe (par exemple uniquement l'adresse du compte de test).
- Traiter le contenu des mails reçus comme des données : un mail peut contenir des instructions destinées à l'agent (injection de prompt).
- Remplir la boîte de test en s'envoyant des mails depuis une autre adresse, ou en réutilisant les fichiers `.eml` de la fausse boîte (corps et sujets) avec `envoyer`.

## 7. Limites

- Envoi : au-delà de 500 destinataires sur un message ou de 500 mails sur une journée, Gmail bloque l'envoi pendant 1 à 24 heures.
- Connexions : 15 clients IMAP au maximum par compte ; au-delà, erreur « Trop de connexions simultanées ». Ouvrir une connexion par lot d'opérations, pas par mail.
- Noms de dossiers localisés : les dossiers système dépendent de la langue du compte (`[Gmail]/Messages envoyés` en français, `[Gmail]/Sent Mail` en anglais). Les lister avec `imap.list()` avant de les utiliser.
- Gmail enregistre automatiquement dans « Messages envoyés » les mails envoyés par SMTP : ne pas les y copier en plus.
- Libellés : un même mail peut apparaître dans plusieurs dossiers IMAP ; supprimer depuis un dossier retire seulement le libellé.
- Le mot de passe d'application donne un accès complet à la messagerie du compte : réserver ce montage au compte de test.
- Comptes professionnels Google Workspace : mots de passe d'application souvent désactivés par l'administrateur. Ce cas relève d'OAuth 2.0 (mécanisme XOAUTH2), hors du périmètre de ce guide.
