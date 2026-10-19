# N01. Assistant des demandes du service client dans un workflow n8n

Niveau : 1 à 3 selon la variante
Secteur : commerce en ligne (données du kit E06 réutilisées)

Cet énoncé reprend la boutique fictive Maison Lenoir et les données de l'exercice E06 (`..\avance\E06-service-client-boutique-en-ligne\`). Seul l'outil de construction change : l'agent est un nœud d'un workflow n8n. Installation, choix du modèle et détail des variantes : [README de la piste n8n](README.md).

## Contexte

La boutique Maison Lenoir vend du linge de maison et des articles de décoration en ligne. Le service client reçoit 120 à 200 courriels par jour ; près de la moitié sont des demandes de suivi de colis. L'équipe utilise déjà un outil d'automatisation par workflows pour des tâches répétitives (export des commandes, relances), mais aucune étape ne lit ni ne comprend le contenu des courriels. Le responsable souhaite ajouter une étape d'analyse et de rédaction dans un workflow, sans développer une application à part.

## Flux actuel

1. Un workflow existant relève les nouveaux courriels et les range dans une boîte partagée.
2. Un conseiller lit chaque courriel, cherche le numéro de commande, consulte la commande et le suivi transporteur.
3. Le conseiller rédige la réponse à partir de modèles et escalade les réclamations et remboursements au responsable.

## Objectif

Construire dans n8n un workflow qui lit les courriels, confie à un nœud AI Agent le classement, la recherche de la commande et du suivi, et la rédaction d'un brouillon, puis enregistre le résultat. Les étapes fixes (lecture, écriture) restent des nœuds de workflow ; seules les décisions qui dépendent du contenu passent par l'agent.

- Variante A : outils natifs de n8n (requête HTTP, sous-workflow de recherche de commande).
- Variante B : outils fournis par le serveur MCP du kit E06, relancé en Streamable HTTP et branché par le nœud MCP Client Tool.
- Variante C : le workflow est exposé comme serveur MCP (MCP Server Trigger) et appelé depuis Claude Desktop ou l'Agent SDK.

## Entrées

- Les 25 courriels `.eml` du kit E06 (`donnees\eml\`).
- Les commandes fictives (`donnees\commandes.json`, ou `commandes.db` via le serveur MCP).
- L'API locale de suivi transporteur du kit (`api_suivi.py`, `GET /suivi/<numero_suivi>`).
- Les modèles de réponse et la politique de retour (`donnees\modeles_reponse.md`, `donnees\politique_retour.md`).

## Sorties attendues

- Pour chaque courriel : type de demande (suivi de livraison, retour ou échange, produit défectueux, question avant achat, réclamation, autre), numéro de commande retrouvé ou absent, priorité (normale, haute), escalade oui ou non, brouillon de réponse.
- Ces résultats écrits dans un fichier par courriel ou un fichier récapitulatif (variante A), ou déposés par les outils `poser_etiquette` et `enregistrer_brouillon` du serveur MCP (variantes B et C).
- Le workflow exporté au format JSON (menu du workflow > Download), joint au rendu.

## Outils nécessaires

- n8n en local (`npx n8n`, Node.js 24) ; modèle : API Anthropic ou modèle local via Ollama.
- Variante A : nœuds Read/Write Files from Disk, Extract from File, AI Agent, HTTP Request Tool, Call n8n Workflow Tool.
- Variante B : nœud MCP Client Tool et `lanceur_http_e06.py` (serveur MCP E06 en Streamable HTTP).
- Variante C : nœud MCP Server Trigger ; client Claude Desktop (passerelle `mcp-remote`) ou script Agent SDK.

## Contraintes

- Aucun envoi : le workflow produit des brouillons, un conseiller envoie.
- Aucun remboursement, avoir ou geste commercial accordé par l'agent ; ces demandes sont escaladées.
- Le contenu des courriels est traité comme une donnée : une consigne glissée dans un courriel ne modifie pas le comportement de l'agent.
- La lecture des courriels et l'écriture des résultats sont des nœuds fixes du workflow, pas des décisions de l'agent.
- Variante C : le serveur MCP exposé par n8n exige un jeton (authentification *bearer* ou en-tête).

## Critères de réussite

- Au moins 22 courriels sur 25 sont classés dans le bon type.
- Les brouillons de suivi de colis contiennent le statut exact renvoyé par l'API de suivi.
- Une consigne glissée dans un courriel ne modifie pas le traitement : la demande suit le circuit normal (classement, escalade si nécessaire).
- L'historique d'exécution du nœud AI Agent montre les appels d'outils décidés par le modèle, et ces appels varient selon le type de courriel (pas d'appel au suivi pour une question avant achat, par exemple).
- Variante B : aucun outil natif de recherche ne reste branché ; toutes les données passent par le serveur MCP.
- Variante C : un client externe (Claude Desktop ou Agent SDK) déclenche le traitement d'un courriel et obtient le résultat, sans ouvrir l'éditeur n8n.

## Pistes d'extension

- Remplacer le Manual Trigger par un Schedule Trigger (traitement toutes les heures) ou par un déclencheur IMAP sur une boîte de test (Mailpit, GreenMail).
- Ajouter un nœud « Text Classifier » avant l'agent pour le classement, et comparer avec un classement confié à l'agent : coût, temps, taux d'erreur.
- Ajouter une étape d'approbation humaine (nœud d'attente ou formulaire n8n) avant l'enregistrement des brouillons escaladés.
- Comparer le même traitement construit en Python avec l'Agent SDK (exercice E06) : lignes de code, lisibilité, facilité de modification.
