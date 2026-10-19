"""Client de test du kit E11 : démarre chaque serveur en stdio et appelle chaque outil.

Usage, depuis ce dossier :
    ..\\.venv\\Scripts\\python test_kit.py
Les écritures vont dans un dossier temporaire (variable E11_SORTIES).
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters

ICI = Path(__file__).parent
CITATION_EXACTE = "Le présent contrat est conclu pour une durée initiale de douze mois à compter de sa date de signature."
CITATION_FAUSSE = "Le présent contrat est conclu pour une durée initiale de six mois."


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
    sorties = tempfile.mkdtemp(prefix="e11_")
    env = {**os.environ, "E11_SORTIES": sorties, "PYTHONIOENCODING": "utf-8"}
    note = f'Durée : « {CITATION_EXACTE} » ; variante : « {CITATION_FAUSSE} » ; classement "conforme"'


    await verifier("serveur_contrats.py", [
        ("lister_contrats", {}, "CTR-2026-0438", False),
        ("lire_contrat", {"contrat": "CTR-2026-0412"}, "Transports Delrue", False),
        ("lire_contrat", {"contrat": "contrat-99"}, None, True),
        ("sommaire_contrat", {"contrat": "contrat-02"}, "Préambule", False),
        ("lire_article", {"contrat": "contrat-01", "numero_article": 14}, "douze mois", False),
        ("rechercher_passages", {"contrat": "contrat-01", "mots_cles": "durée initiale"}, '"article": 14', False),
        ("verifier_citation", {"contrat": "contrat-01", "citation": CITATION_EXACTE}, '"exacte": true', False),
        ("verifier_citation", {"contrat": "contrat-01", "citation": CITATION_FAUSSE}, "passage_le_plus_proche", False),
        ("verifier_citations_note", {"contrat": "contrat-01", "texte_note": note}, '"citations": 2, "exactes": 1', False),
    ], "contrats://liste", ("extraire_clauses", {"contrat": "contrat-01"}), env)

    await verifier("serveur_grille.py", [
        ("lire_grille", {}, "G10", False),
        ("lire_clause_grille", {"code": "g3"}, "Résiliation", False),
        ("lire_clause_grille", {"code": "G11"}, None, True),
        ("calculer_echeances_contrat", {"date_debut": "2026-01-31", "duree_mois": 13, "preavis_mois": 3,
                                        "reconduction_mois": 12},
         '"terme_periode_initiale": "2027-02-28"', False),
    ], "grille://reference", ("classer_clause", {"code": "G1", "citation": CITATION_EXACTE}), env)

    await verifier("serveur_notes.py", [
        ("ecrire_note_revue", {"contrat": "contrat-01", "contenu_markdown": "# Essai"}, "note-contrat-01.md", False),
        ("ecrire_synthese_acheteur", {"contrat": "CTR-2026-0412", "contenu_markdown": "# Essai"}, "synthese-contrat-01.md", False),
        ("enregistrer_remarque", {"contrat": "contrat-01", "agent": "test", "remarque": "essai"}, "R001", False),
        ("lister_remarques", {"contrat": "contrat-01"}, "essai", False),
        ("traiter_remarque", {"id_remarque": "R001", "traitement": "corrigé", "agent": "test"}, "corrigé", False),
        ("traiter_remarque", {"id_remarque": "R999", "traitement": "x", "agent": "test"}, None, True),
        ("lister_notes", {}, "notes/note-contrat-01.md", False),
        ("lire_note", {"nom": "notes/note-contrat-01.md"}, "brouillon", False),
        ("lire_note", {"nom": "../commun.py"}, None, True),
    ], "modele://note-revue", ("contredire_note", {"contrat": "contrat-01", "nom_note": "notes/note-contrat-01.md"}), env)

    print("OK : kit E11 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
