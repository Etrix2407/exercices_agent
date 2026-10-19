"""Squelette d'orchestration E09 : répartition des serveurs MCP par rôle d'agent.

Pseudo-code sans appel au modèle. Les fonctions sont à écrire avec le SDK d'agent
ou le framework choisi ; seule la répartition des outils est fixée ici.
"""

# Serveurs MCP du kit (commande de lancement relative au dossier du kit).
SERVEURS = {
    "declarations": ["serveur_declarations.py"],
    "contrat": ["serveur_contrat.py"],
    "bareme": ["serveur_bareme.py"],
    "sorties": ["serveur_sorties.py"],
}

# Chaque rôle ne reçoit que les outils de son périmètre.
ROLES = {
    "extraction": {
        "serveurs": ["declarations", "sorties"],
        "outils": ["lister_declarations", "lire_declaration", "compter_jours_ouvres", "journaliser"],
    },
    "couverture": {
        "serveurs": ["contrat", "bareme", "sorties"],
        "outils": [
            "rechercher_contrat", "lire_conditions_particulieres", "garanties_contrat",
            "lire_article_cg", "rechercher_conditions_generales",
            "lire_bareme", "calculer_franchise", "calculer_montant_indicatif", "journaliser",
        ],
    },
    "redaction": {
        "serveurs": ["sorties"],
        "outils": ["ecrire_brouillon_courrier", "journaliser"],
    },
    "orchestrateur": {
        "serveurs": ["sorties"],
        "outils": ["ecrire_fiche", "lire_journal", "lister_sorties", "journaliser"],
    },
}


def lancer_agent(role: str, consigne: str, contexte: dict) -> dict:
    """Démarre un agent limité aux outils de ROLES[role] et renvoie sa sortie structurée.

    À écrire : création de l'agent (sous-agent, appel API avec outils, etc.),
    connexion aux serveurs de ROLES[role]["serveurs"], filtrage par ROLES[role]["outils"].
    """
    raise NotImplementedError


def traiter_dossier(numero_dossier: str) -> None:
    # 1. extraction = lancer_agent("extraction", "...", {"dossier": numero_dossier})
    # 2. si l'extraction est incomplète : décider de la suite (question, pièce à demander, arrêt)
    # 3. couverture = lancer_agent("couverture", "...", {"extraction": extraction})
    # 4. courrier = lancer_agent("redaction", "...", {"synthese": couverture})
    #    (l'agent de rédaction ne reçoit que la synthèse, pas le contrat)
    # 5. assembler la fiche et l'écrire avec ecrire_fiche ; chaque étape passe par journaliser
    raise NotImplementedError


def main() -> None:
    # Pour chaque dossier renvoyé par lister_declarations : traiter_dossier(numero)
    # Variante : traiter plusieurs dossiers en parallèle.
    raise NotImplementedError


if __name__ == "__main__":
    for role, conf in ROLES.items():
        print(f"{role:14} -> serveurs {', '.join(conf['serveurs'])}")
