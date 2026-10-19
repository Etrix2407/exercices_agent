# Base SQLite fictive

Base d'un distributeur fictif de fournitures de bureau (Norvel Fournitures) : clients, produits, stocks, commandes, factures, tickets support. Toutes les données sont inventées ; les adresses utilisent le domaine réservé `.example`.

## Créer la base

```powershell
py -3.12 creer_base.py
```

Résultat : `entreprise.db` à côté du script. La génération est déterministe (graine 42) : deux exécutions produisent un fichier identique. Options : `--sortie chemin.db`, `--graine 7` pour un autre jeu.

La date de référence des données est le 30/09/2026 : statuts de commandes, échéances et tickets sont calculés par rapport à elle.

## Contenu (graine 42)

| Table | Lignes | Remarques |
|---|---|---|
| clients | 24 | codes `CLI-0001` à `CLI-0024`, trois segments |
| produits | 30 | références `PRD-101` à `PRD-130`, prix HT |
| stocks | 30 | 8 produits sous le seuil d'alerte |
| commandes | 120 | `CMD-2026-0001` à `CMD-2026-0120`, janvier à septembre 2026 |
| lignes_commande | 380 | 1 à 5 lignes par commande |
| factures | 114 | 89 payées, 20 en retard, 5 en attente ; TVA 21 % |
| tickets | 40 | 3 ouverts, 14 en cours, 6 résolus, 17 fermés |

Les clients, commandes, factures, tickets et produits cités dans la fausse boîte mail (`../fausse-boite-mail`) existent dans cette base.

## Schéma

```
clients (id, code, raison_sociale, secteur, ville, contact_nom, contact_email,
         telephone, segment, cree_le)
produits (id, reference, designation, categorie, prix_unitaire, fournisseur)
stocks (produit_id -> produits.id, entrepot, quantite, seuil_alerte, maj_le)
commandes (id, numero, client_id -> clients.id, date_commande, statut, montant_ht)
lignes_commande (id, commande_id -> commandes.id, produit_id -> produits.id,
                 quantite, prix_unitaire)
factures (id, numero, commande_id -> commandes.id, date_emission, date_echeance,
          montant_ttc, statut, date_paiement)
tickets (id, numero, client_id -> clients.id, commande_id -> commandes.id (nullable),
         ouvert_le, categorie, priorite, statut, sujet, description)
```

Valeurs contrôlées :

- `clients.segment` : `standard`, `premium`, `grand_compte`
- `commandes.statut` : `en_preparation`, `expediee`, `livree`, `annulee`
- `factures.statut` : `payee`, `en_attente`, `en_retard`
- `tickets.categorie` : `livraison`, `produit`, `facturation`, `compte`
- `tickets.priorite` : `basse`, `normale`, `haute`
- `tickets.statut` : `ouvert`, `en_cours`, `resolu`, `ferme`

Dates au format ISO `AAAA-MM-JJ` (texte). Montants en euros, `montant_ht` sur la commande, `montant_ttc` sur la facture. Une commande annulée ou en préparation n'a pas de facture.

## Exemples de requêtes

```sql
-- Factures en retard avec le client
SELECT f.numero, c.raison_sociale, f.date_echeance, f.montant_ttc
FROM factures f
JOIN commandes co ON co.id = f.commande_id
JOIN clients c ON c.id = co.client_id
WHERE f.statut = 'en_retard'
ORDER BY f.date_echeance;

-- Produits à réapprovisionner
SELECT p.reference, p.designation, s.quantite, s.seuil_alerte, p.fournisseur
FROM stocks s JOIN produits p ON p.id = s.produit_id
WHERE s.quantite < s.seuil_alerte;

-- Clients avec plusieurs tickets non clos
SELECT c.raison_sociale, COUNT(*) AS n
FROM tickets t JOIN clients c ON c.id = t.client_id
WHERE t.statut IN ('ouvert', 'en_cours')
GROUP BY c.id HAVING n > 1;
```

Accès depuis Python :

```python
import sqlite3
cx = sqlite3.connect("file:entreprise.db?mode=ro", uri=True)  # lecture seule
print(cx.execute("SELECT COUNT(*) FROM clients").fetchone())
```

Pour un accès par un agent via MCP, voir `../serveur-mcp-exemple`.
