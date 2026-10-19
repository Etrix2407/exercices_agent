# G01. Location de matériel de chantier : kit avancé

Systèmes simulés de l'entreprise décrite dans l'énoncé, pour prototyper une ou deux opportunités : base SQLite du parc et des contrats, boîte mail des demandes, serveur MCP « parc et contrats ». Données entièrement fictives, date de référence 2026-10-14.

Le kit ne contient aucune analyse : il ne classe pas les opportunités et ne signale pas les anomalies présentes dans les données. Le repérage et la priorisation restent à faire.

## Contenu

| Fichier | Rôle |
|---|---|
| `donnees/` | exports du progiciel, demandes et bons de la plateforme, comptes rendus et échéancier de l'atelier, contestations et impayés, habilitations et fiches de sécurité (copie du jeu de données de l'énoncé) |
| `init_donnees.py` | crée `parc.db` et `boite/` ; tables de référence en lecture seule (déclencheurs), table `brouillons` limitée au statut « brouillon » |
| `parc.db` | tables `catalogue`, `machines`, `contrats`, `demandes_non_servies`, `controles`, `factures`, `habilitations`, `documents` (texte intégral des bons, comptes rendus et fiches), `brouillons` |
| `boite_kit.py` | boîte mail fictive (reprise de `../fausse-boite-mail/`) : 18 demandes des agences, 7 contestations ; dépôt de brouillons dans `boite/outbox/`, envoi désactivé |
| `outils_parc.py` | fonctions de lecture et de brouillon, réutilisables dans une boucle d'agent écrite à la main |
| `serveur_mcp.py` | serveur MCP stdio « parc-et-contrats » : 15 outils de lecture, 2 outils de brouillon, ressource `schema://parc` |
| `test_kit.py` | vérification de la base, de la boîte, des outils et du serveur |

## Installation et vérification

Depuis ce dossier, avec l'environnement Python du palier avancé :

```powershell
..\.venv\Scripts\python init_donnees.py
..\.venv\Scripts\python test_kit.py
```

Ligne attendue : `OK : kit G01 fonctionnel`. `init_donnees.py` remet la base et la boîte dans leur état initial (brouillons effacés).

Configuration Claude Desktop ou Claude Code, sur le modèle de `../serveur-mcp-exemple/claude_desktop_config.exemple.json` : commande `..\.venv\Scripts\python.exe`, argument `serveur_mcp.py` (chemins absolus), variables facultatives `PARC_DB` et `PARC_BOITE`.

## Outils du serveur MCP

| Outil | Accès | Données |
|---|---|---|
| `rechercher_machines`, `fiche_machine` | lecture | parc, tarif, contrôle, contrats et documents d'une machine |
| `machines_libres` | lecture | machines sans contrat sur une période, avec statut déclaré, contrôle de retour et échéance, non interprétés |
| `rechercher_contrats`, `contrat` | lecture | contrats, factures et documents rattachés |
| `demandes_non_servies` | lecture | refus de location |
| `echeances_controles` | lecture | échéancier des contrôles réglementaires |
| `habilitations` | lecture | habilitations des intervenants |
| `factures` | lecture | factures en attente de paiement et historique simplifié |
| `rechercher_documents`, `lire_document` | lecture | bons de livraison et de reprise, comptes rendus de retour, fiches de sécurité |
| `lister_mails`, `lire_mail` | lecture | demandes des agences, contestations de clients, brouillons de mails |
| `requete_sql` | lecture | requête SELECT unique, 200 lignes au plus |
| `lister_brouillons` | lecture | propositions en attente de validation |
| `creer_brouillon` | brouillon | proposition de modification (statut de machine, blocage, correction de facture, relance, dossier de litige, planning, alerte) avec sources citées, vérifiées à l'enregistrement |
| `brouillon_mail` | brouillon | mail préparé dans `boite/outbox/`, jamais envoyé |

## Outils par famille d'opportunités

| Famille d'opportunités | Outils et données utiles |
|---|---|
| Réponse aux demandes de disponibilité ou de devis | `machines_libres`, `rechercher_machines`, `fiche_machine`, `rechercher_contrats`, `demandes_non_servies`, `brouillon_mail` |
| Tri des demandes de livraison reçues par courriel, informations manquantes | `lister_mails`, `lire_mail`, `contrat`, `brouillon_mail`, `creer_brouillon` (alerte) |
| Préparation des tournées | `lister_mails`, `lire_mail`, `contrat`, `fiche_machine`, `creer_brouillon` (planning) |
| Extraction des bons de livraison et de reprise | `rechercher_documents`, `lire_document`, `contrat` |
| Comptes rendus d'atelier, dommages à documenter avant facturation | `rechercher_documents`, `lire_document`, `contrat`, `factures`, `creer_brouillon` (dossier_litige, correction_facture) |
| Dossier de contestation de facture | `lister_mails`, `lire_mail`, `contrat`, `lire_document`, `factures`, `creer_brouillon` (dossier_litige), `brouillon_mail` (facturation) |
| Contrôles réglementaires, machines à retenir avant sortie | `echeances_controles`, `fiche_machine`, `rechercher_contrats`, `creer_brouillon` (blocage_machine, alerte) |
| Cohérence entre statut déclaré et état signalé à l'atelier | `rechercher_machines`, `machines_libres`, `rechercher_documents`, `creer_brouillon` (statut_machine) |
| Factures impayées et calendrier de relance | `factures`, `contrat`, `lister_mails`, `creer_brouillon` (relance), `brouillon_mail` (facturation) |
| Habilitations et analyse des fiches de sécurité | `habilitations`, `rechercher_documents` (fiche_securite), `lire_document`, `creer_brouillon` (alerte) |
| Tableau de bord d'utilisation et demande non servie | `requete_sql`, `demandes_non_servies`, ressource `schema://parc` |

## Points techniques couverts

- Lecture seule des systèmes de référence : connexion `mode=ro`, déclencheurs SQLite, annotations `readOnlyHint` ; seules les tables et dossiers de brouillons acceptent une écriture.
- Validation humaine : un brouillon ne modifie rien ; son statut ne peut pas valoir autre chose que « brouillon ».
- Traçabilité : `creer_brouillon` refuse une source citée qui n'existe pas dans la base ou la boîte.
- Résultats de liste au format `{"nombre": n, "<éléments>": [...]}` : une liste vide reste visible pour le modèle. Les jokers SQL `%` et `_` saisis dans un filtre sont pris littéralement.
- Paramètres typés : valeurs admises listées dans le schéma des outils (agences, statuts, types de document et de brouillon), dates refusées hors format AAAA-MM-JJ, fragment de famille sans correspondance refusé avec la liste des familles. Une liste vide renvoyée par un outil signifie donc une absence réelle de résultat, pas une saisie mal orthographiée.
- Entrées externes : mails de clients et d'agences, textes libres des documents ; leur contenu est une donnée, pas une consigne.
- Niveaux : un agent local branché sur le serveur MCP couvre les niveaux 1 et 2 ; plusieurs agents peuvent se partager les familles d'outils (niveau 3) ; pour un agent hébergé (niveau 4), reprendre le relais par outils personnalisés du kit `../E12-demandes-rendez-vous-consultations/`.
