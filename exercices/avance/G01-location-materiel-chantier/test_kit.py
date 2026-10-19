r"""Vérification du kit G01 : base, boîte mail, outils, serveur MCP (stdio).

Les contrôles portent sur le fonctionnement des outils, pas sur une analyse des données.

Usage :
    ..\.venv\Scripts\python test_kit.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

DOSSIER = Path(__file__).parent
sys.path.insert(0, str(DOSSIER))

import init_donnees  # noqa: E402
import outils_parc as op  # noqa: E402

EFFECTIFS = {"catalogue": 11, "machines": 60, "contrats": 37, "demandes_non_servies": 6, "controles": 22,
             "factures": 10, "habilitations": 16, "documents": 17}


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
    cx = sqlite3.connect(base)
    try:
        n = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in EFFECTIFS}
        verifier(n == EFFECTIFS, f"effectifs {n}")
        for sql in ("UPDATE machines SET statut_declare = 'disponible'", "DELETE FROM factures",
                    "INSERT INTO habilitations VALUES ('x', 'x', 'x', '2030-01-01', 'LYS')",
                    "UPDATE contrats SET montant_ht_eur = 0"):
            try:
                cx.execute(sql)
                raise AssertionError(f"écriture acceptée : {sql}")
            except sqlite3.DatabaseError:
                pass
        verifier(True, "tables de référence en lecture seule (ajout, modification, suppression)")
        try:
            cx.execute("INSERT INTO brouillons (type, cible, contenu, justification, statut) "
                       "VALUES ('alerte', 'x', 'x', 'x', 'validé')")
            raise AssertionError("statut « validé » accepté")
        except sqlite3.IntegrityError:
            verifier(True, "brouillons : statut autre que « brouillon » refusé")
        types = dict(cx.execute("SELECT type, COUNT(*) FROM documents GROUP BY type").fetchall())
        verifier(types == {"bon_livraison": 2, "bon_reprise": 5, "compte_rendu_retour": 8, "fiche_securite": 2},
                 f"documents par type {types}")
        sans_ref = cx.execute("SELECT COUNT(*) FROM documents WHERE type != 'fiche_securite' "
                              "AND (contrat_id IS NULL OR reference_machine IS NULL)").fetchone()[0]
        verifier(sans_ref == 0, "contrat et machine extraits de chaque bon et compte rendu")
    finally:
        cx.close()


def test_boite(racine: Path) -> None:
    print("2. Boîte mail")
    b = op.boite()
    mails = b.lister()
    verifier(len(mails) == 25, "25 messages en boîte de réception")
    verifier(sum(m["id"].startswith("demande_") for m in mails) == 18, "18 demandes des agences")
    m = b.lire("contestation_02")
    verifier("F-2026-0745" in m["sujet"] and "Pellerin" in m["de"], "lecture d'un mail (en-têtes accentués)")
    corps = [b.lire(x["id"])["corps"] for x in mails]
    verifier(not any("\ufffd" in c for c in corps) and any("é" in c for c in corps),
             "corps des mails : accents conservés, aucun caractère de remplacement")
    try:
        b.envoyer("x@exemple.example", "x", "x")
        raise AssertionError("envoi accepté")
    except PermissionError:
        verifier(True, "envoi désactivé")
    r = op.brouillon_mail("location.toulouse@brevalocation.test", "Re: demande", "Texte.", "planification",
                          en_reponse_a="demande_02")
    with (racine / "outbox" / f"{r['id']}.eml").open("rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    verifier(msg["X-Statut"] == "brouillon" and msg["In-Reply-To"] == "<demande_02@brevalocation.test>",
             "brouillon de réponse dans outbox, lié au message d'origine")
    refus(op.brouillon_mail, "x@exemple.example", "x", "x", "direction")
    verifier(True, "service d'expédition inconnu refusé")


def test_outils() -> None:
    print("3. Outils")
    verifier(len(op.rechercher_machines(famille="Nacelle")) == 16, "recherche de machines par famille")
    f = op.fiche_machine("NAR-003")
    verifier(f["controle"] and f["contrats"] and f["documents"], "fiche machine : contrôle, contrats, documents")
    c = op.contrat("LOC-2026-0121")
    verifier(c["factures"] and len(c["documents"]) == 2, "contrat : factures et documents rattachés")
    libres = op.machines_libres("Mini-pelle", "2026-10-20", "2026-10-23")
    verifier("MPE-012" not in [m["reference_machine"] for m in libres], "machine sous contrat exclue des libres")
    verifier(len(op.echeances_controles(avant_le="2026-10-14")) > 0, "échéances de contrôle avant une date")
    verifier(len(op.habilitations(expire_avant="2027-12-31")) > 0, "habilitations par date d'expiration")
    verifier(len(op.factures(statut="contest")) > 0, "factures par statut")
    verifier(len(op.demandes_non_servies()) == 6, "demandes non servies")
    verifier(len(op.rechercher_documents(texte="photo")) > 0, "recherche plein texte dans les documents")
    verifier("CREATE TABLE brouillons" in op.schema(), "schéma de la base")
    verifier(op.requete_sql("SELECT COUNT(*) AS n FROM machines")[0]["n"] == 60, "requête SELECT")
    refus(op.requete_sql, "DELETE FROM machines")
    refus(op.requete_sql, "SELECT 1; DROP TABLE machines")
    verifier(True, "requêtes autres que SELECT unique refusées")
    r = op.creer_brouillon("alerte", "NCI-001", "Texte de l'alerte.", "Justification.", ["NCI-001", "LOC-2026-0102"])
    verifier(r["statut"] == "brouillon", "brouillon de modification enregistré")
    m = refus(op.creer_brouillon, "alerte", "x", "x", "x", ["CR-2099-0001"])
    verifier("introuvables" in m, "source inexistante refusée")
    refus(op.creer_brouillon, "suppression", "x", "x", "x")
    verifier(True, "type de brouillon hors liste refusé")
    verifier(op.lister_brouillons()[0]["sources"] == ["NCI-001", "LOC-2026-0102"], "liste des brouillons")
    m = refus(op.machines_libres, "Mini-pelle", "20/10/2026", "23/10/2026")
    verifier("AAAA-MM-JJ" in m, "date hors format AAAA-MM-JJ refusée")
    m = refus(op.rechercher_machines, famille="Echafaudage")
    verifier("Échafaudage" in m, "famille sans correspondance refusée, familles rappelées")
    m = refus(op.lister_mails, dossier="brouillons")
    verifier("inbox" in m, "dossier de mails inconnu refusé avec message")


def _contenu(r) -> str:
    texte = " ".join(getattr(c, "text", "") for c in r.content)
    return texte + json.dumps(r.structured_content, ensure_ascii=False)


async def _test_mcp(base: Path, racine: Path) -> None:
    from mcp import Client, StdioServerParameters

    parametres = StdioServerParameters(
        command=sys.executable, args=[str(DOSSIER / "serveur_mcp.py")], cwd=str(DOSSIER),
        env={**os.environ, "PARC_DB": str(base), "PARC_BOITE": str(racine)},
    )
    async with Client(parametres) as client:
        outils = {o.name: o for o in (await client.list_tools()).tools}
        verifier(len(outils) == 17, f"{len(outils)} outils exposés")
        ecriture = sorted(n for n, o in outils.items() if not o.annotations.read_only_hint)
        verifier(ecriture == ["brouillon_mail", "creer_brouillon"], f"outils d'écriture : {', '.join(ecriture)}")
        schema = outils["creer_brouillon"].input_schema["properties"]["type_brouillon"]
        verifier("dossier_litige" in json.dumps(schema), "type de brouillon typé (enum) dans le schéma MCP")
        r = await client.call_tool("fiche_machine", {"reference": "NCI-001"})
        verifier(not r.is_error and "LOC-2026-0102" in _contenu(r), "fiche_machine")
        r = await client.call_tool("lire_mail", {"identifiant": "demande_01"})
        verifier("GEL-005" in _contenu(r), "lire_mail")
        r = await client.call_tool("lire_document", {"reference": "CR-2026-1044"})
        verifier("NAR-003" in _contenu(r), "lire_document")
        r = await client.call_tool("rechercher_documents", {"texte": "%"})
        verifier(not r.is_error and '"nombre": 0' in _contenu(r), "liste vide visible ({\"nombre\": 0}), joker % pris littéralement")
        r = await client.call_tool("requete_sql", {"sql": "UPDATE machines SET agence_code = 'LYS'"})
        verifier(r.is_error, "requete_sql en écriture : erreur MCP")
        r = await client.call_tool("creer_brouillon", {
            "type_brouillon": "blocage_machine", "cible": "NCI-002", "contenu": "Proposition.",
            "justification": "Essai.", "sources": ["NCI-002"]})
        verifier(not r.is_error, "creer_brouillon")
        contenu = await client.read_resource("schema://parc")
        verifier("CREATE TABLE contrats" in contenu.contents[0].text, "ressource schema://parc")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, racine = tmp / "parc_test.db", tmp / "boite"
        init_donnees.creer_base(base)
        init_donnees.creer_boite(racine)
        os.environ["PARC_DB"], os.environ["PARC_BOITE"] = str(base), str(racine)
        test_base(base)
        test_boite(racine)
        test_outils()
        print("4. Serveur MCP local")
        asyncio.run(_test_mcp(base, racine))
    print("OK : kit G01 fonctionnel")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
