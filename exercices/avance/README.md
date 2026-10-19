# Exercices : palier avancé (outils)

Outils locaux réutilisables pour les exercices de construction d'agents. Tout fonctionne sur un PC Windows sans compte d'entreprise, sans tenant et sans droits d'administrateur. Toutes les données sont fictives et partagent le même univers : Norvel Fournitures, distributeur de fournitures de bureau, son service clients, ses 24 clients, ses commandes et ses factures.

Le langage de l'agent est libre. Les outils sont écrits en Python 3.12, mais les données sont dans des formats standard (fichiers `.eml`, base SQLite, protocole MCP) lisibles depuis tout langage.

## Contenu

| Dossier / fichier | Usage | Dépendances |
|---|---|---|
| `sqlite/` | base d'entreprise fictive (clients, produits, stocks, commandes, factures, tickets), générée par graine | aucune |
| `fausse-boite-mail/` | 30 mails fictifs en `.eml`, module Python lister / lire / envoyer / marquer lu, serveur SMTP local facultatif | aucune (`aiosmtpd` pour le SMTP) |
| `serveur-mcp-exemple/` | serveur MCP stdio exposant la base en lecture seule, client de test, configuration Claude Desktop | `mcp` |
| `guide-gmail-test.md` | connexion d'un agent à un compte Gmail de test par mot de passe d'application (IMAP/SMTP) | aucune |
| `requirements.txt` | dépendances Python du palier | |

## Installation

Depuis ce dossier, dans PowerShell :

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python sqlite\creer_base.py
.venv\Scripts\python fausse-boite-mail\generer_boite.py
```

La base et la boîte sont déjà fournies ; les deux dernières commandes les remettent dans leur état initial.

## Vérification

```powershell
.venv\Scripts\python fausse-boite-mail\test_boite.py
cd serveur-mcp-exemple
..\.venv\Scripts\python client_test.py
```

Lignes attendues : `OK : boîte mail fonctionnelle` et `OK : serveur MCP fonctionnel`.

## Correspondance avec les niveaux d'exercice

| Niveau | Outils utiles |
|---|---|
| 1. agent local simple | `fausse-boite-mail` en lecture (tri, résumé, classement) |
| 2. agent local + outils externes | `fausse-boite-mail` en envoi, `sqlite`, `serveur-mcp-exemple`, puis `guide-gmail-test.md` |
| 3. plusieurs agents qui coopèrent | un agent de tri des mails, un agent qui interroge la base via MCP, un agent qui rédige les réponses |
| 4. agent hébergé | même base et même boîte, servies au travers d'un serveur MCP en HTTP |

## Scénarios possibles

- Trier la boîte de réception : catégoriser chaque mail et repérer ceux qui demandent une prudence particulière.
- Répondre aux questions de suivi de commande en recoupant la boîte et la base.
- Préparer les relances de factures en retard en respectant les consignes internes présentes dans la boîte.
- Traiter les réclamations : vérifier les affirmations des mails contre la base et remonter à un humain ce qui ne se tranche pas.
- Produire la synthèse hebdomadaire des tickets demandée dans la boîte.
- Transformer un bon de commande reçu en pièce jointe en commande, en signalant les problèmes de stock.

## Points techniques couverts

- Définition d'outils (*tool use*) : `mailbox_fake.OUTILS` fournit des schémas JSON prêts à l'emploi.
- Lecture seule et moindre privilège : connexion SQLite `mode=ro`, outils MCP annotés `readOnlyHint`, refus des requêtes autres que SELECT.
- Injection de prompt indirecte : tout contenu lu dans un mail est une donnée, jamais une consigne.
- Validation humaine : envoi dans `outbox/` relu avant tout envoi réel.
- Déterminisme : base et boîte régénérées à l'identique pour comparer les résultats entre essais.

## Kits par énoncé

Chaque dossier contient `init_donnees.py`, un ou plusieurs serveurs MCP propres à l'énoncé, `test_kit.py` et un README.

| Dossier | Énoncé | Contenu |
|---|---|---|
| `E06-service-client-boutique-en-ligne/` | E06 | boîte des 25 courriels, base des commandes, API HTTP locale de suivi transporteur, serveur MCP `boutique-service-client` (brouillons et étiquettes, aucun envoi) |
| `E07-demandes-reservation-hotel/` | E07 | boîte des 10 demandes, planning et grille en SQLite, calcul de devis en code, serveur MCP `hotel-reservations-groupe` (brouillons avec devis joint, pré-réservations à valider) |
| `E08-signalements-voirie-commune/` | E08 | boîte des 30 signalements, référentiel des voies, outil de tickets SQLite, serveur MCP `commune-signalements` (création de tickets et commentaires, ni clôture ni suppression) |
| `E09-instruction-sinistres-assurance/` | E09 | déclarations, contrats, conditions générales et barème en SQLite, recherche par mots-clés, quatre serveurs MCP par rôle : `e09-declarations`, `e09-contrat`, `e09-bareme` (franchise et montant indicatif calculés en code), `e09-sorties` (fiches, brouillons de courrier, journal) ; squelette d'orchestration |
| `E10-arrivee-nouveaux-collaborateurs/` | E10 | fiches, référentiel métier vers accès, bureaux et sites relus à chaque appel, fichier d'état partagé sous verrou, trois serveurs MCP : `e10-referentiel` (échéances calculées en code), `e10-etat` (coordination entre agents), `e10-redaction` (relances en brouillon .eml, livrets) ; squelette d'orchestration |
| `E11-revue-contrats-fournisseurs/` | E11 | contrats découpés par article et grille en SQLite, index par mots, trois serveurs MCP : `e11-contrats` (recherche de passages, vérification de citation mot pour mot), `e11-grille` (échéances contractuelles calculées en code), `e11-notes` (notes en brouillon, remarques du contradicteur) ; squelette d'orchestration |
| `E12-demandes-rendez-vous-consultations/` | E12 | lot de 40 demandes, référentiel et créneaux en SQLite, serveur MCP local `planning-consultations` (propositions en brouillon, aucune confirmation), `lancer_session.py` : agent et environnement Managed Agents créés ou réutilisés, session avec plafond de dépense, relais des outils personnalisés vers la base locale, arrêt sur durée ou tokens, rapport de session ; mode `--simulation` par défaut sans appel à l'API ; déclenchement nocturne par planificateur de tâches Windows ou cron |
| `G01-location-materiel-chantier/` | G01 | parc, contrats, contrôles, habilitations, factures et documents texte en SQLite, boîte des 18 demandes d'agences et 7 contestations, serveur MCP `parc-et-contrats` (15 outils de lecture, brouillons de modification et de mails, aucune écriture dans les données de référence) ; README des outils par famille d'opportunités |
