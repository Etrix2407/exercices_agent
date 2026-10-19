"""Squelette d'orchestration E10 : répartition des serveurs MCP par rôle d'agent.

Pseudo-code sans appel au modèle. Les agents ne s'échangent pas de messages directement :
ils lisent et écrivent l'état partagé (serveur e10-etat). Les fonctions sont à écrire.
"""

SERVEURS = {
    "referentiel": ["serveur_referentiel.py"],
    "etat": ["serveur_etat.py"],
    "redaction": ["serveur_redaction.py"],
}

ROLES = {
    "rh": {
        "serveurs": ["referentiel", "etat"],
        "outils": ["lire_fiche", "calculer_echeances", "lire_etat_arrivee", "enregistrer_demande",
                   "mettre_a_jour_tache", "journaliser"],
    },
    "informatique": {
        "serveurs": ["referentiel", "etat"],
        "outils": ["lire_fiche", "lister_metiers", "acces_metier", "calculer_echeances",
                   "lire_etat_arrivee", "enregistrer_demande", "journaliser"],
    },
    "logistique": {
        "serveurs": ["referentiel", "etat"],
        "outils": ["lire_fiche", "acces_metier", "bureaux_site", "infos_site", "calculer_echeances",
                   "lire_etat_arrivee", "enregistrer_demande", "proposer_bureau", "journaliser"],
    },
    "orchestrateur": {
        "serveurs": ["referentiel", "etat", "redaction"],
        "outils": ["lister_arrivees", "lire_fiche", "infos_site", "tableau_avancement", "taches_en_retard",
                   "lire_etat_arrivee", "journaliser", "ecrire_brouillon_relance", "ecrire_livret",
                   "ecrire_tableau_avancement", "lister_sorties"],
    },
}


def lancer_agent(role: str, consigne: str, contexte: dict) -> dict:
    """Démarre un agent limité aux outils de ROLES[role] et renvoie sa sortie.

    À écrire : création de l'agent, connexion aux serveurs de ROLES[role]["serveurs"],
    filtrage des outils par ROLES[role]["outils"].
    """
    raise NotImplementedError


def preparer_arrivee(id_arrivee: str) -> None:
    # 1. lancer_agent("rh", ...), lancer_agent("informatique", ...), lancer_agent("logistique", ...)
    #    (indépendants : exécution possible en parallèle, l'état partagé est protégé par un verrou)
    # 2. chaque agent enregistre ses demandes dans l'état ; un cas non couvert par le référentiel
    #    reste à traiter selon les contraintes de l'énoncé
    raise NotImplementedError


def executer() -> None:
    # 1. pour chaque arrivée de lister_arrivees : preparer_arrivee si ses demandes ne sont pas encore enregistrées
    # 2. lancer_agent("orchestrateur", ...) : tableau d'avancement, relances en brouillon, livrets
    # Une exécution par jour : relancer avec un fichier d'état modifié pour simuler les retards.
    raise NotImplementedError


if __name__ == "__main__":
    for role, conf in ROLES.items():
        print(f"{role:14} -> serveurs {', '.join(conf['serveurs'])}")
