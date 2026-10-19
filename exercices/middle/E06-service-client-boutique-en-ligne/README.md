# E06. Service client de la boutique Maison Lenoir (données fictives)

## Fichiers d'entrée (29)

- boite_test/ : 25 courriels .eml (courriel-01.eml à courriel-25.eml).
- commandes.json : 50 commandes ML-2026-1001 à ML-2026-1050 (client, articles, date, statut, numéro de suivi).
- suivi_transporteur.json : statuts simulés du transporteur pour les commandes expédiées ou livrées.
- modeles_reponse.md : modèles de brouillons et note interne d'escalade.
- politique_retour.md : délais, conditions, remboursement, produits défectueux, erreurs de préparation.

suivi_transporteur.json sert de données à la petite API locale de suivi à écrire (statut, dernière étape, date estimée). Les fichiers .eml peuvent être injectés dans une boîte de test locale (Mailpit, GreenMail) ou lus directement. Les courriels n'ont pas de pièce jointe.
