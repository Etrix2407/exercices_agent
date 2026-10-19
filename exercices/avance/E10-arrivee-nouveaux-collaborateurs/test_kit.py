"""Client de test du kit E10 : démarre chaque serveur en stdio et appelle chaque outil.

Usage, depuis ce dossier :
    ..\\.venv\\Scripts\\python test_kit.py
Le test travaille sur une copie temporaire de l'état partagé (E10_ETAT) et des sorties (E10_SORTIES) :
le fichier etat/etat_partage.json n'est pas modifié.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters

ICI = Path(__file__).parent


def contenu(resultat) -> str:
    texte = "\n".join(getattr(c, "text", "") for c in resultat.content)
    return texte + json.dumps(resultat.structured_content or {}, ensure_ascii=False)


async def verifier(script: str, appels: list[tuple[str, dict, str | None, bool]], ressource: str,
                   prompt: tuple[str, dict], env: dict) -> None:
    """appels : (outil, arguments, texte attendu ou None, erreur attendue)."""
    parametres = StdioServerParameters(command=sys.executable, args=[str(ICI / script)], cwd=str(ICI), env=env)
    async with Client(parametres) as client:
        noms = {o.name for o in (await client.list_tools()).tools}
        testes = {a[0] for a in appels}
        assert noms == testes, f"{script} : outils non testés ou inconnus {noms ^ testes}"
        for outil, arguments, attendu, erreur in appels:
            r = await client.call_tool(outil, arguments)
            assert r.is_error == erreur, f"{script} {outil} : is_error={r.is_error} : {contenu(r)[:300]}"
            if attendu:
                assert attendu in contenu(r), f"{script} {outil} : « {attendu} » absent de {contenu(r)[:300]}"
        res = await client.read_resource(ressource)
        assert res.contents[0].text.strip(), f"{script} : ressource vide"
        p = await client.get_prompt(*prompt)
        assert p.messages[0].content.text.strip()
        print(f"{script} : {len(noms)} outils, ressource {ressource}, prompt {prompt[0]} : OK")


async def main() -> None:
    temp = Path(tempfile.mkdtemp(prefix="e10_"))
    shutil.copyfile(ICI / "etat" / "etat_partage.json", temp / "etat_partage.json")
    env = {**os.environ, "E10_ETAT": str(temp / "etat_partage.json"), "E10_SORTIES": str(temp / "sorties"),
           "PYTHONIOENCODING": "utf-8"}

    await verifier("serveur_referentiel.py", [
        ("lister_arrivees", {}, "ARR-2026-106", False),
        ("lire_fiche", {"id_arrivee": "ARR-2026-102"}, "Ingénieur calcul", False),
        ("lire_fiche", {"id_arrivee": "ARR-2026-999"}, None, True),
        ("lister_metiers", {}, "TOUS", False),
        ("acces_metier", {"metier": "dev"}, "APP-GIT", False),
        ("acces_metier", {"metier": "XYZ"}, '"present_dans_referentiel": false', False),
        ("infos_site", {"code_site": "OST"}, "Ostrevel", False),
        ("bureaux_site", {"code_site": "COR", "zone": "labo"}, "L-401", False),
        ("calculer_echeances", {"date_arrivee": "2026-10-19"}, '"echeance": "2026-10-05"', False),
    ], "parametres://arrivees", ("preparer_demandes", {"id_arrivee": "ARR-2026-102", "service": "informatique"}), env)

    await verifier("serveur_etat.py", [
        ("lire_etat_arrivee", {"id_arrivee": "ARR-2026-102"}, "INF-01", False),
        ("enregistrer_demande", {"id_arrivee": "ARR-2026-102", "service": "informatique", "objet": "Logiciel de calcul",
                                 "echeance": "2026-10-19", "agent": "test", "code_acces": "APP-SIM"},
         '"dans_referentiel": true', False),
        ("enregistrer_demande", {"id_arrivee": "ARR-2026-102", "service": "informatique", "objet": "Accès hors liste",
                                 "echeance": "2026-10-19", "agent": "test", "code_acces": "APP-XYZ"}, None, True),
        ("enregistrer_demande", {"id_arrivee": "ARR-2026-102", "service": "informatique", "objet": "Messagerie",
                                 "echeance": "19/10", "agent": "test", "code_acces": "MSG"}, None, True),
        ("mettre_a_jour_tache", {"id_arrivee": "ARR-2026-105", "id_tache": "RH-02", "statut": "fait",
                                 "agent": "test", "date_reponse": "2026-10-14"}, '"statut": "fait"', False),
        ("proposer_bureau", {"id_arrivee": "ARR-2026-102", "identifiant_bureau": "B-301", "agent": "test"}, "B-301", False),
        ("proposer_bureau", {"id_arrivee": "ARR-2026-106", "identifiant_bureau": "B-301", "agent": "test"}, None, True),
        ("journaliser", {"agent": "test", "id_arrivee": "ARR-2026-102", "evenement": "essai"}, "essai", False),
        ("taches_en_retard", {"date_reference": "2026-12-31"}, "ARR-2026-104", False),
        ("tableau_avancement", {}, "ARR-2026-101", False),
    ], "etat://partage", ("point_avancement", {}), env)

    await verifier("serveur_redaction.py", [
        ("ecrire_brouillon_relance", {"id_arrivee": "ARR-2026-102", "id_tache": "INF-01", "destinataire": "it@vandamme.example",
                                      "sujet": "Essai", "corps": "Texte", "agent": "test"}, "brouillon", False),
        ("ecrire_brouillon_relance", {"id_arrivee": "ARR-2026-102", "id_tache": "INF-01", "destinataire": "it@vandamme.example",
                                      "sujet": "Essai", "corps": "Texte", "agent": "test"}, None, True),
        ("ecrire_livret", {"id_arrivee": "ARR-2026-102", "contenu_markdown": "# Essai"}, "ARR-2026-102.md", False),
        ("ecrire_tableau_avancement", {"contenu_markdown": "# Essai"}, "avancement-", False),
        ("lister_sorties", {}, "brouillons/REL-0001.eml", False),
    ], "modele://livret", ("rediger_livret", {"id_arrivee": "ARR-2026-102"}), env)

    etat = json.loads((temp / "etat_partage.json").read_text(encoding="utf-8"))
    assert len(etat["demandes"]) == 1 and len(etat["relances"]) == 1 and len(etat["journal"]) == 2
    assert len(etat["propositions_bureau"]) == 1
    print("OK : kit E10 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
