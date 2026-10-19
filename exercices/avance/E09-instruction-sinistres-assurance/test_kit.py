"""Client de test du kit E09 : démarre chaque serveur en stdio et appelle chaque outil.

Usage, depuis ce dossier :
    ..\\.venv\\Scripts\\python test_kit.py
Les écritures vont dans un dossier temporaire (variable E09_SORTIES).
"""

import asyncio
import json
import os
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
    sorties = tempfile.mkdtemp(prefix="e09_")
    env = {**os.environ, "E09_SORTIES": sorties, "PYTHONIOENCODING": "utf-8"}

    await verifier("serveur_declarations.py", [
        ("lister_declarations", {}, "SIN-2026-0008", False),
        ("lire_declaration", {"numero_dossier": "SIN-2026-0001"}, "flexible", False),
        ("lire_declaration", {"numero_dossier": "SIN-2026-9999"}, None, True),
        ("compter_jours_ouvres", {"date_debut": "2026-09-03", "date_fin": "07/09/2026"}, '"jours_ouvres": 2', False),
    ], "modele://extraction", ("extraire_declaration", {"numero_dossier": "SIN-2026-0001"}), env)

    await verifier("serveur_contrat.py", [
        ("rechercher_contrat", {"texte": "Tilleville"}, "PH-HAB-1001", False),
        ("rechercher_contrat", {"texte": "Mme Hélène Varnier"}, "PH-HAB-1001", False),
        ("lire_conditions_particulieres", {"numero_contrat": "PH-HAB-1003"}, "Conditions particulières", False),
        ("garanties_contrat", {"numero_contrat": "PH-HAB-1004"}, "Vol hors domicile", False),
        ("garanties_contrat", {"numero_contrat": "PH-HAB-0000"}, None, True),
        ("lire_article_cg", {"numero": 14}, "Franchises", False),
        ("rechercher_conditions_generales", {"mots_cles": "expertise montant estimé"}, '"numero": 18', False),
    ], "cg://sommaire", ("verifier_couverture", {"numero_dossier": "SIN-2026-0001", "numero_contrat": "PH-HAB-1002"}), env)

    await verifier("serveur_bareme.py", [
        ("lire_bareme", {}, "vol_domicile", False),
        ("calculer_franchise", {"nature": "vol_domicile", "montant_estime": 500}, '"franchise": 100', False),
        ("calculer_franchise", {"nature": "inondation", "montant_estime": 500}, None, True),
        ("calculer_franchise", {"nature": "bris_de_glace", "montant_estime": 500, "options": ["renforcé"]}, None, True),
        ("calculer_montant_indicatif",
         {"nature": "bris_de_glace", "montant_estime": 3000, "plafond": 2500, "options": ["bris_de_glace_renforce"]},
         '"montant_indicatif_net": 2475', False),
    ], "bareme://franchises", ("calculer_montants", {"nature": "incendie", "montant_estime": "1000", "plafond": "150000"}), env)

    await verifier("serveur_sorties.py", [
        ("journaliser", {"agent": "test", "numero_dossier": "SIN-2026-0001", "evenement": "essai"}, "essai", False),
        ("ecrire_fiche", {"numero_dossier": "SIN-2026-0001", "contenu_markdown": "# Essai"}, "SIN-2026-0001.md", False),
        ("ecrire_brouillon_courrier",
         {"numero_dossier": "SIN-2026-0001", "destinataire": "Assuré", "objet": "Essai", "corps": "Texte"},
         "SIN-2026-0001.txt", False),
        ("lire_journal", {"numero_dossier": "SIN-2026-0001"}, "essai", False),
        ("lister_sorties", {}, "fiches/SIN-2026-0001.md", False),
    ], "modele://fiche", ("rediger_courrier", {"numero_dossier": "SIN-2026-0001", "synthese": "Essai"}), env)

    print("OK : kit E09 fonctionnel")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
