r"""Vérification du kit E12, sans aucun appel à l'API.

Contrôles :
    1. base : effectifs, tables protégées, statut « brouillon » imposé ;
    2. outils : lecture, brouillons, refus des propositions contraires au référentiel ;
    3. serveur MCP local (stdio) : liste des outils, appels, erreurs ;
    4. lancer_session.py en simulation : rejeu complet, interruption sur limite de tokens,
       planning.db inchangée ;
    5. paramètres des appels Managed Agents confrontés aux signatures du SDK installé.

Usage :
    ..\.venv\Scripts\python test_kit.py
"""

from __future__ import annotations

import asyncio
import csv
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import typing
from pathlib import Path

DOSSIER = Path(__file__).parent
sys.path.insert(0, str(DOSSIER))

import init_donnees  # noqa: E402
import outils_planning as op  # noqa: E402


def verifier(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def refus(fonction, *args, **kwargs) -> str:
    try:
        fonction(*args, **kwargs)
    except op.ErreurOutil as e:
        return str(e)
    raise AssertionError(f"refus attendu : {fonction.__name__}{args}")


def test_base(base: Path) -> None:
    print("1. Base")
    with sqlite3.connect(base) as cx:
        n = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("specialites", "demandes", "creneaux")}
        verifier(n == {"specialites": 22, "demandes": 40, "creneaux": 122}, f"effectifs {n}")
        for sql in ("UPDATE creneaux SET statut = 'pris'", "DELETE FROM demandes", "UPDATE specialites SET delai_standard_j = 0"):
            try:
                cx.execute(sql)
                raise AssertionError(f"écriture acceptée : {sql}")
            except sqlite3.DatabaseError:
                pass
        verifier(True, "tables demandes, specialites et creneaux en lecture seule")
        try:
            cx.execute("INSERT INTO propositions (id_demande, specialite_retenue, priorite, justification, statut) "
                       "VALUES ('DEM-20261013-002', 'Cardiologie', 'standard', 'x', 'confirmé')")
            raise AssertionError("statut « confirmé » accepté")
        except sqlite3.IntegrityError:
            verifier(True, "statut autre que « brouillon » refusé par la base")
    cx.close()


def test_outils() -> None:
    print("2. Outils")
    demandes = op.lister_demandes()
    verifier(len(demandes) == 40 and "niss_fictif" not in demandes[0], "40 demandes, NISS non exposé")
    verifier(len(op.referentiel()) == 22, "référentiel de 22 spécialités")
    libres = op.lister_creneaux_libres("Cardiologie")
    verifier(len(libres) > 0, f"{len(libres)} créneaux libres en cardiologie")
    premier = libres[0]["id_creneau"]

    r = op.proposer_creneau("DEM-20261013-002", "Cardiologie", "standard", "Suivi programmé.", id_creneau=premier)
    verifier(r["statut"] == "brouillon", "proposition enregistrée en brouillon")
    verifier(premier not in [c["id_creneau"] for c in op.lister_creneaux_libres("Cardiologie")],
             "créneau retenu retiré de la liste des libres")
    m = refus(op.proposer_creneau, "DEM-20261013-003", "Cardiologie", "standard", "x", id_creneau=premier)
    verifier("déjà proposé" in m, "créneau déjà proposé refusé")
    m = refus(op.proposer_creneau, "DEM-20261013-003", "Pneumologie", "standard", "x", id_creneau=premier)
    verifier("relève de" in m, "créneau d'une autre spécialité refusé")
    autre = op.lister_creneaux_libres("Cardiologie")[0]["id_creneau"]
    m = refus(op.proposer_creneau, "DEM-20261013-003", "Cardiologie", "urgent", "x", id_creneau=autre)
    verifier("urgences" in m, "créneau pour une priorité urgente refusé")
    requis = {r["nom"] for r in op.referentiel() if r["courrier_requis"] == "oui"}
    sans = next(d for d in demandes if d["specialite_demandee"] in requis and d["courrier_adressage"] == "non"
                and op.lister_creneaux_libres(d["specialite_demandee"], date_min=d["date_depot"]))
    cr = op.lister_creneaux_libres(sans["specialite_demandee"], date_min=sans["date_depot"])[0]["id_creneau"]
    m = refus(op.proposer_creneau, sans["id_demande"], sans["specialite_demandee"], "standard", "x", id_creneau=cr)
    verifier("courrier" in m, "créneau sans courrier d'adressage requis refusé")
    m = refus(op.lister_creneaux_libres, "Gastro-enterologie")
    verifier("Spécialité inconnue" in m and "Gastro-entérologie" in m, "spécialité mal orthographiée refusée, noms exacts rappelés")
    m = refus(op.lister_creneaux_libres, "ORL", date_min="14/10/2026")
    verifier("AAAA-MM-JJ" in m, "date hors format AAAA-MM-JJ refusée")
    m = refus(op.proposer_creneau, "DEM-20261013-003", "Cardiologie", "standard", "x")
    verifier("motif_sans_creneau" in m, "absence de créneau sans motif refusée")
    refus(op.proposer_creneau, "DEM-20261013-003", "Cardiologie", "confirmé", "x")
    refus(op.proposer_creneau, "DEM-99999999-999", "Cardiologie", "standard", "x", motif_sans_creneau="y")
    verifier(True, "priorité hors liste et demande inconnue refusées")
    r = op.proposer_creneau("DEM-20261013-003", "Cardiologie", "incertaine", "Motif imprécis.",
                            motif_sans_creneau="priorité à établir")
    verifier(r["a_revoir"] is True, "priorité incertaine marquée à revoir")
    op.proposer_creneau("DEM-20261013-002", "Cardiologie", "standard", "Suivi programmé.", motif_sans_creneau="test")
    verifier(premier in [c["id_creneau"] for c in op.lister_creneaux_libres("Cardiologie")],
             "remplacement d'un brouillon : créneau libéré")
    op.retirer_proposition("DEM-20261013-002")
    op.retirer_proposition("DEM-20261013-003")
    verifier(op.bilan()["traitees"] == 0, "brouillons retirés")
    texte, erreur = op.executer_outil("confirmer_rendez_vous", {})
    verifier(erreur, "outil de confirmation inexistant dans le relais")
    texte, erreur = op.executer_outil("lister_creneaux_libres", {"specialite": "ORL"})
    verifier(not erreur and json.loads(texte), "relais : appel valide")


def _contenu(r) -> str:
    """Texte et contenu structuré d'un résultat d'outil MCP."""
    texte = " ".join(getattr(c, "text", "") for c in r.content)
    return texte + json.dumps(r.structured_content, ensure_ascii=False)


async def _test_mcp(base: Path) -> None:
    from mcp import Client, StdioServerParameters

    parametres = StdioServerParameters(
        command=sys.executable, args=[str(DOSSIER / "serveur_mcp.py")],
        env={**os.environ, "PLANNING_DB": str(base)}, cwd=str(DOSSIER),
    )
    async with Client(parametres) as client:
        liste = (await client.list_tools()).tools
        noms = sorted(o.name for o in liste)
        attendus = {"lister_demandes", "lire_demande", "referentiel", "lister_creneaux_libres", "lister_propositions",
                    "bilan_propositions", "proposer_creneau", "retirer_proposition"}
        verifier(set(noms) == attendus, f"outils exposés : {', '.join(noms)}")
        schema = next(o for o in liste if o.name == "proposer_creneau").input_schema
        verifier("enum" in json.dumps(schema["properties"]["priorite"]), "priorité typée (enum) dans le schéma MCP")
        r = await client.call_tool("lister_creneaux_libres", {"specialite": "ORL"})
        verifier(not r.is_error and "CR-06" in _contenu(r), "lister_creneaux_libres")
        r = await client.call_tool("lister_propositions", {})
        verifier('"nombre": 0' in _contenu(r), "liste vide visible ({\"nombre\": 0})")
        r = await client.call_tool("lire_demande", {"id_demande": "DEM-20261013-016"})
        verifier("Otite" in _contenu(r), "lire_demande")
        r = await client.call_tool("proposer_creneau", {
            "id_demande": "DEM-20261013-016", "specialite": "ORL", "priorite": "standard",
            "justification": "test", "id_creneau": "CR-06-001"})
        verifier(not r.is_error, "proposer_creneau en brouillon")
        r = await client.call_tool("proposer_creneau", {
            "id_demande": "DEM-20261013-017", "specialite": "ORL", "priorite": "standard",
            "justification": "test", "id_creneau": "CR-06-001"})
        verifier(r.is_error, "doublon de créneau renvoyé en erreur MCP")
        r = await client.call_tool("retirer_proposition", {"id_demande": "DEM-20261013-016"})
        verifier(not r.is_error, "retirer_proposition")


def test_simulation(dossier_tmp: Path) -> None:
    print("4. lancer_session.py --simulation")
    import lancer_session as ls

    ls.SORTIES = dossier_tmp / "sorties"
    reference = init_donnees.BASE_DEFAUT
    empreinte_avant = reference.stat().st_mtime_ns if reference.exists() else None

    r = ls.main(["--simulation"])
    verifier(r["fin"] == "end_turn" and r["arret_par_garde"] is None, "rejeu complet jusqu'à end_turn")
    verifier(r["bilan_lot"]["traitees"] == 2, "deux brouillons écrits par le relais d'outils")
    verifier(r["evenements"].get("autorisation refusée") == 1, "demande d'autorisation refusée sans surveillance")
    verifier(r["usage_api"]["tokens_entree"] > 0, "usage relevé dans le rapport")
    sortie = next(ls.SORTIES.glob("*_simulation"))
    with (sortie / "propositions.csv").open(encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    ids = [l["id_demande"] for l in lignes]
    verifier(len(ids) == 40 and len(set(ids)) == 40, "fichier de propositions : 40 lignes sans doublon")
    creneaux = [l["id_creneau"] for l in lignes if l["id_creneau"]]
    verifier(len(creneaux) == len(set(creneaux)), "aucun créneau proposé deux fois")
    verifier((sortie / "rapport_session.json").exists() and (sortie / "evenements.jsonl").exists(),
             "rapport et journal d'événements écrits")

    import time as _t
    _t.sleep(1.1)  # dossier horodaté à la seconde
    r = ls.main(["--simulation", "--tokens-max", "10000"])
    verifier(r["arret_par_garde"] and "tokens" in r["arret_par_garde"], "interruption sur limite de tokens")
    verifier(r["bilan_lot"]["traitees"] == 0, "aucun brouillon après interruption précoce")
    apres = reference.stat().st_mtime_ns if reference.exists() else None
    verifier(empreinte_avant == apres, "planning.db non modifiée par la simulation")


def _cles(typed_dict) -> set[str]:
    return set(typing.get_type_hints(typed_dict, include_extras=False).keys())


def test_sdk() -> None:
    print("5. Paramètres confrontés au SDK installé (aucune requête)")
    import anthropic
    from anthropic.types.beta import (
        BetaCloudConfigParams,
        BetaLimitedNetworkParams,
        BetaManagedAgentsBudgetLimitParam,
        BetaManagedAgentsCustomToolParams,
        BetaManagedAgentsFileResourceParams,
    )
    from anthropic.types.beta.sessions import (
        BetaManagedAgentsUserCustomToolResultEventParams,
        BetaManagedAgentsUserInterruptEventParams,
        BetaManagedAgentsUserMessageEventParams,
        BetaManagedAgentsUserToolConfirmationEventParams,
    )

    import lancer_session as ls

    print(f"  SDK anthropic {anthropic.__version__}")
    client = anthropic.Anthropic(api_key="cle-de-test-non-utilisee")
    pa, pe = ls.parametres_agent(), ls.parametres_environnement()
    ps = ls.parametres_session("agent_x", 1, "env_x", {"demandes_jour.csv": "file_x"}, 500)
    inspect.signature(client.beta.agents.create).bind(**pa)
    inspect.signature(client.beta.agents.update).bind("agent_x", version=1, **{k: v for k, v in pa.items() if k != "name"})
    inspect.signature(client.beta.agents.retrieve).bind("agent_x")
    inspect.signature(client.beta.environments.create).bind(**pe)
    inspect.signature(client.beta.environments.retrieve).bind("env_x")
    inspect.signature(client.beta.sessions.create).bind(**ps)
    inspect.signature(client.beta.sessions.events.stream).bind("sesn_x")
    inspect.signature(client.beta.sessions.events.send).bind("sesn_x", events=[])
    inspect.signature(client.beta.sessions.retrieve).bind("sesn_x")
    inspect.signature(client.beta.sessions.archive).bind("sesn_x")
    inspect.signature(client.beta.files.list).bind(scope_id="sesn_x", betas=["managed-agents-2026-04-01"])
    inspect.signature(client.files.upload).bind(file=("a.csv", b"", "text/plain"))
    inspect.signature(client.files.download).bind("file_x")
    verifier(True, "signatures : agents, environments, sessions, events, files")

    outil = next(t for t in pa["tools"] if t["type"] == "custom")
    verifier(set(outil) <= _cles(BetaManagedAgentsCustomToolParams), "champs des outils personnalisés")
    verifier(set(pe["config"]) <= _cles(BetaCloudConfigParams)
             and set(pe["config"]["networking"]) <= _cles(BetaLimitedNetworkParams), "champs de l'environnement")
    verifier(set(ps["resources"][0]) <= _cles(BetaManagedAgentsFileResourceParams), "champs des fichiers montés")
    verifier(set(ps["budget"]) <= _cles(BetaManagedAgentsBudgetLimitParam), "champs du plafond de session")
    envois = {
        BetaManagedAgentsUserMessageEventParams: {"type", "content"},
        BetaManagedAgentsUserCustomToolResultEventParams: {"type", "custom_tool_use_id", "content", "is_error"},
        BetaManagedAgentsUserToolConfirmationEventParams: {"type", "tool_use_id", "result", "deny_message"},
        BetaManagedAgentsUserInterruptEventParams: {"type"},
    }
    verifier(all(champs <= _cles(td) for td, champs in envois.items()), "champs des événements envoyés")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base = init_donnees.creer_base(tmp / "planning_test.db")
        os.environ["PLANNING_DB"] = str(base)
        test_base(base)
        test_outils()
        print("3. Serveur MCP local")
        asyncio.run(_test_mcp(base))
        test_simulation(tmp)
        test_sdk()
    print("OK : kit E12 fonctionnel (aucun appel à l'API)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
