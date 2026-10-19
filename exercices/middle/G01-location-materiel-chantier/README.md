# G01 - Bréval Location : jeu de données fictif

Ce dossier contient des données entièrement fictives pour l'exercice G01 (repérage et priorisation d'agents IA dans une entreprise de location de matériel de chantier). Les personnes, clients, machines, contrats, factures et téléphones sont inventés. Les domaines utilisés se terminent par .test ou .example. Bréval Location et ses agences sont fictives.

Date de référence des données : 14/10/2026. Le montant HT d'un contrat vaut la durée facturée multipliée par le tarif journalier, plus le forfait de transport (`progiciel/catalogue_tarifs.csv`). Le montant d'un contrat en cours ou réservé est prévisionnel. Les factures sont en TTC (TVA à 20 %) et incluent les prestations facturées en plus (carburant, nettoyage).

## Sous-dossiers et fichiers

- `progiciel/` : exports du progiciel de gestion locative.
  - `export_parc.csv` : 60 machines réparties sur 5 agences (référence, famille, agence, statut déclaré, dernier retour, contrôle, prochaine échéance, contrat en cours, compteur).
  - `contrats_location.csv` : 37 contrats (terminés, en cours, réservés), avec durée prévue, durée facturée et montant.
  - `catalogue_tarifs.csv` : 8 familles de machines (tarif journalier, contrôle réglementaire) et 3 prestations forfaitaires.
  - `demandes_non_servies.csv` : 6 demandes de location refusées faute de disponibilité.
- `plateforme/` : demandes et documents logistiques.
  - `demande_01.eml` à `demande_18.eml` : 18 courriels des agences à la planification (livraisons, reprises, prolongation, devis acceptés à affecter).
  - `bons_livraison/` : 7 bons de livraison et de reprise en texte brut.
- `atelier/` : suivi des machines au retour.
  - `comptes_rendus_retour/` : 8 comptes rendus de retour en texte libre.
  - `echeancier_controles.csv` : 22 machines soumises à un contrôle réglementaire, avec date de dernière vérification, échéance semestrielle et statut.
- `facturation/` : litiges et impayés.
  - `contestations/` : 7 courriels de contestation de facture (durée, carburant, nettoyage, dommage).
  - `factures_impayees.csv` : 10 factures en attente de paiement, avec nombre de relances et historique simplifié.
- `rh_securite/` : habilitations et sécurité.
  - `habilitations.csv` : 16 habilitations (intervenant, type, date d'expiration, agence).
  - `fiches_securite/` : 2 fiches, un presque-accident et un accident, en texte libre.
- `README.md` : le présent fichier.

## Opportunités que ces données permettent de prototyper

- Répondre à une demande de disponibilité ou de devis en croisant le parc, les contrats et les demandes non servies.
- Classer les demandes de livraison reçues par courriel et signaler les informations manquantes.
- Préparer le planning des tournées à partir des demandes validées et des changements reçus par téléphone.
- Extraire les données utiles des bons de livraison et de reprise, y compris les réserves écrites à la main.
- Résumer les comptes rendus d'atelier et repérer les dommages à documenter avant facturation.
- Rassembler les pièces d'un dossier de contestation de facture.
- Suivre les échéances de contrôle réglementaire et signaler les machines à retenir avant leur sortie.
- Vérifier la cohérence entre le statut déclaré d'une machine dans le parc et son état signalé à l'atelier.
- Suivre les factures impayées et établir un calendrier de relance selon l'historique du client.
- Suivre les habilitations des intervenants et analyser les fiches de sécurité.
- Produire un tableau de bord du taux d'utilisation et des demandes non servies.
