# Modèles de réponse (Maison Lenoir, données fictives)

Les brouillons sont enregistrés dans un dossier. Aucun modèle n'est envoyé par l'agent.
Champs entre accolades : prenom, numero, statut_exact, derniere_etape, lieu, date_etape, date_estimee.

## suivi_statut_connu

Bonjour {prenom},

La commande {numero} a le statut suivant chez le transporteur : {statut_exact}.
Dernière étape : {derniere_etape} ({lieu}), le {date_etape}.
Date de livraison estimée : {date_estimee}.

Cordialement,
Service client Maison Lenoir

## suivi_incident

Bonjour {prenom},

Le statut de la commande {numero} chez le transporteur est : {statut_exact}.
Dernière étape : {derniere_etape} ({lieu}), le {date_etape}. Le service client suit la livraison avec le transporteur.

Cordialement,
Service client Maison Lenoir

## suivi_sans_numero

Bonjour {prenom},

Merci d'indiquer le numéro de commande (format ML-2026-XXXX) figurant sur la confirmation d'achat.

Cordialement,
Service client Maison Lenoir

## suivi_numero_introuvable

Bonjour {prenom},

Le numéro {numero} ne correspond à aucune commande. Merci de vérifier le numéro figurant sur la confirmation d'achat.

Cordialement,
Service client Maison Lenoir

## suivi_en_preparation

Bonjour {prenom},

La commande {numero} est en préparation. Aucun numéro de suivi n'est encore disponible.

Cordialement,
Service client Maison Lenoir

## retour_echange_dans_delai

Bonjour {prenom},

La politique de retour et d'échange prévoit un délai de 30 jours après la livraison. Les conditions de retour
figurent dans la politique publiée. Les frais de retour restent à la charge du client, sauf erreur de préparation.

Cordialement,
Service client Maison Lenoir

## accuse_escalade

Bonjour {prenom},

La demande concernant la commande {numero} a bien été reçue. Elle est transmise au responsable du service
client ; une réponse suivra après examen.

Cordialement,
Service client Maison Lenoir

## question_avant_achat

Bonjour {prenom},

[Réponse à compléter par le conseiller à partir de la fiche produit.]

Cordialement,
Service client Maison Lenoir

## note_interne_escalade

NOTE INTERNE, ne pas envoyer au client.
Courriel : {numero_courriel}. Type : {type_demande}. Priorité : {priorite}. Raison : {raison}.
