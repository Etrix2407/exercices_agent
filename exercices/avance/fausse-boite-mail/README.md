# Fausse boîte mail

Boîte du service clients d'un distributeur fictif (Norvel Fournitures, `service.clients@norvel-fournitures.example`) : 30 messages `.eml` reçus entre le 24 et le 30/09/2026. Aucun serveur ni compte requis : les messages sont des fichiers, l'envoi écrit un fichier.

## Fichiers

| Fichier | Rôle |
|---|---|
| `generer_boite.py` | recrée `boite/` à l'identique (contenu des 30 mails inclus dans le script) |
| `mailbox_fake.py` | module et ligne de commande : lister, lire, envoyer, marquer lu, archiver, pièces jointes |
| `smtp_local.py` | facultatif : serveur SMTP local (`aiosmtpd`) qui dépose les mails reçus dans la boîte |
| `test_boite.py` | vérification automatique |
| `boite/inbox/` | messages reçus `m001.eml` à `m030.eml` |
| `boite/outbox/` | messages envoyés par l'agent `e001.eml`, `e002.eml`... |
| `boite/archive/` | messages archivés |
| `boite/etat.json` | indicateur lu / non lu |

Les `.eml` sont au format standard (RFC 5322) : lisibles par le module `email` de Python, par tout langage disposant d'un parseur MIME, ou en les ouvrant dans un client de messagerie.

## Démarrer

```powershell
py -3.12 generer_boite.py                # (re)crée la boîte, efface l'outbox et l'état
py -3.12 mailbox_fake.py lister           # * = non lu, [n PJ] = pièces jointes
py -3.12 mailbox_fake.py lister --non-lus --chercher facture
py -3.12 mailbox_fake.py lire m005
py -3.12 mailbox_fake.py lire m005 --marquer-lu
py -3.12 mailbox_fake.py piece m023 bon_commande_octobre.csv
py -3.12 mailbox_fake.py envoyer --a chantal.delvaux@fleurs-jardins.example --sujet "Re: Contestation" --corps "Bonjour, ..." --reponse-a m005
py -3.12 mailbox_fake.py lister --dossier outbox
py -3.12 mailbox_fake.py archiver m021
py -3.12 mailbox_fake.py reinitialiser
```

## Depuis Python

```python
from mailbox_fake import BoiteMail, OUTILS, executer_outil

boite = BoiteMail()
for m in boite.lister(non_lus=True):
    print(m["id"], m["de"], m["sujet"])

mail = boite.lire("m002")           # dict : id, de, a, date, sujet, corps, pieces_jointes, lu...
boite.envoyer("isabelle.moreau@traiteur-moreau.example", "Re: CMD-2026-0119", "Bonjour, ...", en_reponse_a="m002")
boite.marquer_lu("m002")
```

`OUTILS` contient la description JSON Schema de quatre outils (`lister_mails`, `lire_mail`, `envoyer_mail`, `marquer_lu`) à reprendre dans les définitions d'outils d'un agent ; `executer_outil(boite, nom, arguments)` aiguille un appel d'outil vers la bonne méthode.

Un agent écrit dans un autre langage lit directement les fichiers `.eml` et `etat.json`, et écrit ses réponses dans `boite/outbox/`.

## Contenu de la boîte

30 courriels fictifs : commandes, suivis de livraison, réclamations, consignes internes, notifications, publicités et cas à traiter avec prudence. Le tri fait partie de l'exercice.

## Serveur SMTP local (facultatif)

Pour un agent qui envoie avec `smtplib` (ou toute bibliothèque SMTP) sans compte réel :

`aiosmtpd` est installé dans le venv du palier avancé (`..\requirements.txt`) ; le Python système ne l'a pas. Depuis ce dossier :

```powershell
..\.venv\Scripts\python smtp_local.py                 # écoute 127.0.0.1:8025, dépôt dans boite/outbox
..\.venv\Scripts\python smtp_local.py --dossier inbox # injecter de nouveaux mails entrants (non lus)
```

Arrêt par Ctrl+C.

```python
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["From"] = "service.clients@norvel-fournitures.example"
msg["To"] = "claire.lemaire@boulangerie-lemaire.example"
msg["Subject"] = "Confirmation de commande"
msg.set_content("Bonjour, ...")
with smtplib.SMTP("127.0.0.1", 8025) as s:
    s.send_message(msg)
```

Pas d'authentification ni de TLS. Aucun serveur IMAP n'est fourni : la lecture passe par `mailbox_fake.py` ou les fichiers. Pour un vrai IMAP, voir `../guide-gmail-test.md`.

## Vérifier

```powershell
..\.venv\Scripts\python test_boite.py   # travaille dans un dossier temporaire, ne touche pas boite/
```

Le test SMTP est exécuté si `aiosmtpd` est installé, ignoré sinon.
