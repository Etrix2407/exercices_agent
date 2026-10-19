# E01. Réponses aux questions récurrentes d'un cabinet comptable

Niveau : 0
Secteur : cabinet comptable

## Contexte

Le cabinet Derval & Associés tient la comptabilité de 180 indépendants et petites sociétés. Trois collaborateurs répondent aux questions envoyées par les clients via un formulaire du site. Entre janvier et avril, période de clôture et de déclarations, le volume passe de 40 à 150 questions par semaine. Environ 60 % des questions portent sur les mêmes sujets : pièces à fournir, échéances, frais déductibles, notes de frais, délais de remboursement. Les réponses existent déjà dans un document interne de 25 pages, rarement consulté. Le cabinet souhaite un assistant qui prépare les réponses à partir de ce document, sans développement lourd.

## Flux actuel

1. Le client remplit le formulaire (nom, numéro de dossier, question libre).
2. Le formulaire arrive dans une boîte partagée.
3. Un collaborateur lit la question, cherche la réponse de mémoire ou dans le document interne, rédige la réponse.
4. Les questions complexes sont transmises au comptable responsable du dossier.

## Objectif

Configurer un assistant conversationnel pré-prompté qui reçoit une question client collée par un collaborateur et produit un brouillon de réponse fondé uniquement sur le document interne. Ajouter une routine hebdomadaire qui produit la liste des sujets les plus fréquents à partir des questions de la semaine.

## Entrées

- Document interne de référence (FAQ du cabinet), à rédiger de façon fictive : 15 à 20 questions-réponses, échéances, liste des pièces par type de client.
- Un lot de 20 questions clients fictives, dont 5 hors périmètre (question fiscale complexe, contestation d'honoraires, demande de rendez-vous).

## Sorties attendues

- Pour chaque question : un brouillon de réponse, la référence de la section du document utilisée, et une étiquette « traitable » ou « à transmettre au comptable ».
- Chaque semaine : un tableau des sujets classés par fréquence, avec les questions restées sans réponse dans le document.

## Outils nécessaires

- Assistant conversationnel avec instructions système et fichiers de référence (projet, ou prompt système chargé depuis un fichier).
- Fonction de routine ou de tâche planifiée de l'outil choisi, ou procédure relancée à la main.

## Contraintes

- Répondre uniquement à partir du document de référence ; signaler l'absence de réponse plutôt qu'inventer.
- Ne jamais donner de montant d'impôt ni de conseil fiscal personnalisé.
- Le collaborateur relit et envoie lui-même chaque réponse.

## Critères de réussite

- Les 15 questions traitables reçoivent une réponse conforme au document, avec la section citée.
- Les 5 questions hors périmètre sont toutes étiquetées « à transmettre au comptable ».
- Le prompt système tient dans un fichier versionné et, rejoué sur un nouveau lot, produit le même étiquetage.
- La synthèse hebdomadaire fait apparaître les trois sujets dominants du lot.

## Pistes d'extension

- Ajouter des exemples de réponses dans le prompt (*few-shot*) et comparer la qualité.
- Proposer une mise à jour du document de référence pour les questions sans réponse.
- Passer au niveau 1 : un script qui lit les questions depuis un fichier CSV et écrit les brouillons dans un dossier.
