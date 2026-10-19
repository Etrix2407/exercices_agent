"""Squelette d'orchestration E11 : répartition des serveurs MCP par rôle d'agent.

Pseudo-code sans appel au modèle. Les fonctions sont à écrire avec le SDK d'agent
ou le framework choisi ; seule la répartition des outils est fixée ici.
"""

SERVEURS = {
    "contrats": ["serveur_contrats.py"],
    "grille": ["serveur_grille.py"],
    "notes": ["serveur_notes.py"],
}

ROLES = {
    "extraction": {
        "serveurs": ["contrats", "grille"],
        "outils": ["lister_contrats", "sommaire_contrat", "lire_contrat", "lire_article",
                   "rechercher_passages", "verifier_citation", "lire_grille"],
    },
    "analyse": {
        "serveurs": ["grille"],
        "outils": ["lire_grille", "lire_clause_grille", "calculer_echeances_contrat"],
    },
    "redaction": {
        "serveurs": ["grille", "notes"],
        "outils": ["lire_clause_grille", "ecrire_note_revue", "ecrire_synthese_acheteur"],
    },
    "contradicteur": {
        "serveurs": ["contrats", "grille", "notes"],
        "outils": ["lire_article", "rechercher_passages", "verifier_citation", "verifier_citations_note",
                   "lire_clause_grille", "lister_notes", "lire_note", "enregistrer_remarque"],
    },
    "orchestrateur": {
        "serveurs": ["notes"],
        "outils": ["lister_notes", "lire_note", "lister_remarques", "enregistrer_remarque", "traiter_remarque"],
    },
}


def lancer_agent(role: str, consigne: str, contexte: dict) -> dict:
    """Démarre un agent limité aux outils de ROLES[role] et renvoie sa sortie structurée.

    À écrire : création de l'agent, connexion aux serveurs de ROLES[role]["serveurs"],
    filtrage des outils par ROLES[role]["outils"].
    """
    raise NotImplementedError


def revoir_contrat(contrat: str) -> None:
    # 1. clauses = lancer_agent("extraction", ...)        une entrée par clause G1 à G10 : article, citation ou absente
    # 2. contrôle en code des citations (verifier_citation) avant de poursuivre
    # 3. classement = lancer_agent("analyse", ..., {"clauses": clauses})
    # 4. note = lancer_agent("redaction", ..., {"classement": classement})
    # 5. remarques = lancer_agent("contradicteur", ..., {"note": note})
    # 6. traiter chaque remarque (traiter_remarque : correction ou maintien motivé), puis réécrire la note
    #    et la synthèse (nouvel appel à l'agent de rédaction)
    # La note reste un brouillon jusqu'à validation par un juriste.
    raise NotImplementedError


def main() -> None:
    # Pour chaque contrat de lister_contrats : revoir_contrat(id)
    # Test du contradicteur : le lancer seul sur la note de notes_test.
    raise NotImplementedError


if __name__ == "__main__":
    for role, conf in ROLES.items():
        print(f"{role:14} -> serveurs {', '.join(conf['serveurs'])}")
