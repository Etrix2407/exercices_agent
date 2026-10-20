# Exercices pratiques : agents IA

Énoncés d'exercices (voir `README.md`) et kits Python du palier avancé (`avance/`).

Tu es un expert en Python et en développement d'applications évolutives. Tu écris du code fonctionnel, maintenable, performant et accessible, en suivant les bonnes pratiques Python décrites dans ton skill.

## techno

- python 3.12
- pandas (lecture des fichiers CSV)
- pypdf (lecture des fichiers PDF)

## Structure
 
- À la racine du dépôt : `README.md` (présentation complète du projet).

## Règles de contenu

- Pas de doublon 
- Ne jamais inventer ni modifier des faits (dates, postes, entreprises, chiffres, compétences). Si une information manque ou semble incohérente, poser la question.
- Code en anglais uniquement (identifiants, noms de fichiers, routes internes).
- Markdown, commentaires et textes affichés aux utilisateurs en français.
- test uniquement ce qui est necesaire

### Outils à exposer (noms fixes, repris par le prompt système)
- read_email(demande_id) -> str
- read_planning(date_debut, date_fin, besoins) -> dispo (lecture seule)
- read_grille() -> grille tarifaire
- calc_devis(besoins) -> détail chiffré  # calcul en CODE, jamais par le LLM
- write_draft(fiche_json) -> None

Exposition via un serveur MCP local.

### Contraintes non négociables
- Planning en lecture seule : ne jamais réserver ni bloquer.
- Prix exclusivement issus de la grille, via calc_devis. Aucune remise.
- calc_devis relit la grille lui-même ; il ne reçoit que les besoins.

## Revue de code

- Après chaque modification de code non triviale, lancer le skill `code-review` (`/code-review`) sur les changements avant de déclarer la tâche terminée, puis corriger les problèmes confirmés.
- Pour un simple nettoyage (lisibilité, duplication) sans recherche de bugs, utiliser `/simplify`.
- Signaler honnêtement ce qui n'a pas été vérifié (tests non lancés, cas non couverts).

## workflow GIT

- La branche `main` est protégée : ne jamais pousser directement dessus.
- Pour toute modification : créer une branche (`git checkout -b <nom-court>`), committer, pousser la branche, puis ouvrir une pull request.
- Messages de commit courts, à l'impératif, en français (ex. : « Ajoute la section compétences »).
- Un commit = un changement cohérent.
- Ne jamais utiliser `git push --force`, `git reset --hard` ni supprimer de branche distante.
- une branche = une feature
- Demander confirmation avant chaque commit et chaque push.
- Ne jamais committer de secrets, de clés API ou de données personnelles non destinées à être publiques (adresse postale complète, numéro de téléphone, etc.) sans validation.

## Services

- Concevoir chaque service autour d'une responsabilité unique


