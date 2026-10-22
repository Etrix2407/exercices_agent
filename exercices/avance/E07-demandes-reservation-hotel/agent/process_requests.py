"""Traitement des demandes de réservation de groupe (E07, niveau 2).

Démarre le serveur MCP du kit, puis lance une session d'agent par demande avec les outils read_email,
read_planning, read_grille, calc_devis et write_draft. Contrôle ensuite chaque résultat en code
(checks.py : devis recalculé, dates alternatives revérifiées, planning inchangé) et écrit une synthèse
(synthesis.py).
L'agent ne réserve rien et n'envoie rien : il n'écrit que des fiches et des brouillons.

Usage (depuis le dossier du kit E07) : python -m agent [--reset] [--only demande_01_mariage] [--output dossier]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import anyio
from dotenv import load_dotenv

import init_donnees
from agent import checks
from agent.llm_providers import LLMError, LLMProvider, get_provider
from agent.llm_providers.base import LLMBatchError, ToolError
from agent.mcp_bridge import HotelTools, KitCaller, KitClient, kit_session, mailbox_dir
from agent.synthesis import (
    RESULTS_NAME,
    SYNTHESIS_NAME,
    RequestResult,
    load_previous_results,
    merge_result,
    model_texts,
    write_outputs,
)

# Réglages du modèle propres à cet exercice (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et température par défaut.
LLM_PROVIDER = "anthropic"
LLM_MODEL = "claude-haiku-4-5"
# Température : None garde la valeur par défaut du modèle (recommandé pour Gemini 3).
# Plages acceptées : Gemini de 0 à 2 ; Claude de 0 à 1, mais les modèles Claude actuels (Opus 5.5)
# la refusent : elle est alors ignorée avec un avertissement.
LLM_TEMPERATURE = None

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parents[2] / ".env"
PROMPT_PATH = BASE_DIR / "prompt_sys_reservation.md"
OUTPUT_DIR = BASE_DIR / "output"
TOOL_JOURNAL_NAME = "journal_outils.txt"
# Nombre maximal d'appels au modèle (tours) par demande : au-delà, LLMError plutôt qu'une boucle sans fin.
# La même valeur est insérée dans le prompt ({max_tours}) : le modèle connaît la limite réelle.
MAX_STEPS = 20
QUOTA_NOTE = (
    "non traitée : lot arrêté (quota épuisé, configuration refusée ou serveur MCP arrêté), relancer avec --only"
)
UNREADABLE_NOTE = "courriel illisible, non traité par le modèle : {} (vérifier l'en-tête Date et le charset du .eml)"

# (outils du kit, identifiant de la demande) -> outils de l'agent pour cette demande.
ToolsFactory = Callable[[KitCaller, str], HotelTools]

logger = logging.getLogger(__name__)


class BatchStoppedError(LLMBatchError):
    """Erreur de lot relancée par process_request, avec le résultat de la demande en cours.

    result vaut None si aucun write_draft n'avait réussi avant l'erreur.
    """

    def __init__(self, cause: LLMBatchError, result: RequestResult | None) -> None:
        super().__init__(str(cause))
        self.result = result


def load_system_prompt(reference_date: date) -> str:
    """Lit le prompt, retire le commentaire de tête et insère la date de référence et la limite de tours."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = re.sub(r"^\s*<!--.*?-->\s*", "", text, flags=re.DOTALL)
    text = text.replace("{max_tours}", str(MAX_STEPS))
    return text.replace("{date_reference}", reference_date.strftime("%d/%m/%Y"))


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extrait l'objet JSON le plus externe d'une réponse (tolère texte autour et balises ```json)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def save_draft_from_answer(tools: HotelTools, final_text: str) -> str:
    """Filet de sécurité : le modèle a donné le JSON final sans appeler write_draft, le script l'enregistre.

    Les contrôles de write_draft s'appliquent (statut, brouillon non vide, devis issu de calc_devis).
    Renvoie une note pour les points à vérifier, ou la raison de l'échec.
    """
    sheet = extract_json_object(final_text)
    if sheet is None:
        return "write_draft non appelé et aucun JSON exploitable dans la réponse du modèle"
    # Même handler que celui du modèle : l'appel est journalisé dans journal_outils.txt.
    write_draft = {spec.name: spec.handler for spec in tools.specs()}["write_draft"]
    try:
        write_draft({"fiche_json": sheet})
    except ToolError as error:
        return f"write_draft non appelé ; JSON de la réponse refusé : {error}"
    return "write_draft non appelé par le modèle : fiche et brouillon enregistrés par le script à partir de sa réponse"


def build_result(request_id: str, tools: HotelTools, final_text: str) -> RequestResult:
    """Construit le résultat à partir de la fiche écrite par write_draft, puis le contrôle en code."""
    fallback_note = None
    if tools.draft is None:
        fallback_note = save_draft_from_answer(tools, final_text)
        if tools.draft is None:
            return RequestResult(
                demande_id=request_id,
                statut="erreur",
                points_a_verifier=[f"aucune fiche ni brouillon écrit : {fallback_note}", final_text[:200]],
            )
    sheet = tools.draft["fiche"]
    quote = tools.draft["devis"]
    needs = sheet.get("besoins") if isinstance(sheet.get("besoins"), dict) else {}
    result = RequestResult(
        demande_id=request_id,
        statut=sheet["statut"],
        besoins=needs,
        informations_manquantes=model_texts(sheet.get("informations_manquantes")),
        dates_alternatives=model_texts(sheet.get("dates_alternatives")),
        devis_total=quote["total_ttc"] if quote else None,
        brouillon=str(tools.draft["brouillon"].get("brouillon", "")),
        points_a_verifier=model_texts(sheet.get("points_a_verifier")),
    )
    # Notes du code (fiche non enregistrée…) : ajoutées après la troncature des textes du modèle.
    result.points_a_verifier += tools.draft.get("notes", [])
    if fallback_note:
        result.points_a_verifier.append(fallback_note)
    result.points_a_verifier += checks.review_sheet(
        result.statut,
        needs,
        quote,
        result.dates_alternatives,
        result.informations_manquantes,
        str(sheet.get("brouillon_reponse") or ""),
    )
    return result


def process_request(
    kit: KitCaller, request_id: str, provider: LLMProvider, system_prompt: str, tools_factory: ToolsFactory
) -> RequestResult:
    """Lance l'agent sur une demande ; une erreur de modèle donne le statut « erreur » sans bloquer le lot."""
    tools = tools_factory(kit, request_id)
    try:
        # Courriel relu par le code avant tout appel au modèle : un .eml illisible (en-tête Date ou charset
        # invalide) met cette seule demande en erreur, avec la raison, sans consommer d'appel au modèle.
        kit.call("lire_demande", {"identifiant": request_id})
    except ToolError as error:
        logger.error("%s : courriel illisible (%s)", request_id, error)
        return RequestResult(demande_id=request_id, statut="erreur", points_a_verifier=[UNREADABLE_NOTE.format(error)])
    except LLMBatchError as error:
        raise BatchStoppedError(error, None) from error
    try:
        final_text = provider.run_agent(system_prompt, f"Demande : {request_id}", tools.specs(), max_steps=MAX_STEPS)
    except LLMBatchError as error:
        # Quota épuisé, configuration refusée ou serveur arrêté : le lot entier s'arrête (voir process_all).
        # Un write_draft déjà réussi est tout de même pris en compte, et son brouillon remplace l'ancien.
        result = finish_request(kit, request_id, tools, "") if tools.draft is not None else None
        if result is not None:
            result.points_a_verifier.append(f"lot arrêté après write_draft : {error}")
        raise BatchStoppedError(error, result) from error
    except LLMError as error:
        logger.error("%s : %s", request_id, error)
        if tools.draft is None:
            return RequestResult(demande_id=request_id, statut="erreur", points_a_verifier=[str(error)])
        final_text = ""
    try:
        return finish_request(kit, request_id, tools, final_text)
    except LLMBatchError as error:
        # Serveur MCP perdu pendant le filet write_draft : rien n'a été enregistré, le lot s'arrête.
        raise BatchStoppedError(error, None) from error


def finish_request(kit: KitCaller, request_id: str, tools: HotelTools, final_text: str) -> RequestResult:
    """Construit et contrôle le résultat, puis met le nouveau brouillon à la place de l'ancien."""
    result = build_result(request_id, tools, final_text)
    if result.brouillon:
        try:
            result.brouillon = replace_previous_draft(kit, request_id, result.brouillon)
        except (LLMError, ToolError, OSError) as error:
            result.points_a_verifier.append(f"ancien brouillon non remplacé ({error}) : écarter le doublon à la main")
    return result


def replace_previous_draft(kit: KitCaller, request_id: str, new_id: str, drafts_dir: Path | None = None) -> str:
    """Remplace l'ancien brouillon de la demande par le nouveau, sous le même identifiant.

    Le kit numérote les brouillons en comptant les fichiers : supprimer un ancien brouillon ferait réutiliser
    un numéro existant. Le nouveau fichier prend donc la place de l'ancien (os.replace), ce qui garde
    un numéro stable par demande et un nombre de fichiers cohérent.
    """
    drafts_dir = drafts_dir or mailbox_dir() / "brouillons"
    drafts = kit.call("lister_brouillons", {})["brouillons"]
    owner = next((draft.get("pour") for draft in drafts if draft.get("id") == new_id), None)
    if owner != request_id:
        # Le nouveau brouillon ne porte pas sur cette demande (ou n'est pas listé) : rien n'est remplacé.
        logger.warning(
            "Brouillon %s attendu pour %s mais rattaché à %s : aucun ancien brouillon remplacé.",
            new_id,
            request_id,
            owner or "aucune demande",
        )
        return new_id
    previous = sorted(draft["id"] for draft in drafts if draft.get("pour") == request_id and draft["id"] != new_id)
    if not previous:
        return new_id
    target, *duplicates = previous
    os.replace(drafts_dir / f"{new_id}.eml", drafts_dir / f"{target}.eml")
    logger.info("Brouillon %s de %s remplacé par la nouvelle version.", target, request_id)
    if duplicates:
        logger.warning("Anciens brouillons en double pour %s : %s (à écarter à la main).", request_id, duplicates)
    return target


def list_requests(kit: KitCaller) -> list[str]:
    """Identifiants des demandes de la boîte, dans l'ordre du kit.

    Si le kit ne sait pas lister la boîte (un seul .eml à l'en-tête Date illisible suffit), les demandes
    sont lues dans le dossier inbox, par nom de fichier : le lot continue et le courriel fautif passe
    en erreur (voir process_request).
    """
    try:
        return [item["id"] for item in kit.call("lister_demandes", {})["demandes"]]
    except ToolError as error:
        inbox = mailbox_dir() / "inbox"
        logger.warning("Liste des demandes refusée par le kit (%s) : demandes lues dans %s.", error, inbox)
        return sorted(path.stem for path in inbox.glob("*.eml"))


def process_all(
    kit: KitCaller,
    provider: LLMProvider,
    output_dir: Path,
    only: str | None = None,
    tools_factory: ToolsFactory = HotelTools,
) -> list[RequestResult]:
    """Traite chaque demande de la boîte (ou la seule demandée) en réécrivant la synthèse après chacune.

    La synthèse est cumulative : les demandes analysées lors des lancements précédents restent,
    et une demande traitée à nouveau voit sa ligne mise à jour (avec la liste des changements).
    Renvoie les résultats du lancement en cours uniquement.
    """
    request_ids = list_requests(kit)
    if only is not None:
        if only not in request_ids:
            raise ValueError(f"Demande inconnue : « {only} ». Demandes disponibles : {', '.join(request_ids)}")
        request_ids = [only]
    system_prompt = load_system_prompt(date.today())
    before = checks.planning_fingerprint()
    known = load_previous_results(output_dir)
    results: list[RequestResult] = []
    saved: list[RequestResult] = []

    def save() -> str:
        """Seul point d'écriture : recalcule l'empreinte du planning et réécrit synthèse et résultats."""
        for result in results[len(saved) :]:
            merge_result(known, result, datetime.now().strftime("%Y-%m-%d %H:%M"))
        saved.extend(results[len(saved) :])
        unchanged = checks.planning_fingerprint() == before
        ordered = [known[key] for key in sorted(known)]
        return write_outputs(ordered, provider.model, unchanged, output_dir, (len(results), len(request_ids)))

    synthesis = save()
    for position, request_id in enumerate(request_ids, start=1):
        logger.info("Demande %d/%d : %s — en cours…", position, len(request_ids), request_id)
        try:
            result = process_request(kit, request_id, provider, system_prompt, tools_factory)
        except BatchStoppedError as error:
            logger.error("Arrêt du lot : %s", error)
            results.append(
                error.result or RequestResult(demande_id=request_id, statut="erreur", points_a_verifier=[str(error)])
            )
            results += [
                RequestResult(demande_id=pending, statut="non_traitee", points_a_verifier=[QUOTA_NOTE])
                for pending in request_ids[position:]
            ]
        else:
            logger.info("→ %s : %s", request_id, result.statut)
            results.append(result)
        synthesis = save()
        # Lot arrêté : les demandes restantes sont déjà marquées « non_traitee ».
        if len(results) == len(request_ids):
            break
    logger.info("\n%s", synthesis)
    logger.info("Synthèse, résultats et journal écrits dans %s", output_dir)
    return results


async def run(provider: LLMProvider, output_dir: Path, only: str | None) -> None:
    """Ouvre le serveur MCP du kit et traite les demandes dans un thread de travail."""
    async with kit_session() as client:
        kit = KitClient(client)
        await anyio.to_thread.run_sync(process_all, kit, provider, output_dir, only)


def configure_logging(output_dir: Path) -> Path:
    """Progression dans le terminal, appels d'outils dans un fichier texte."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for library_logger in ("httpx", "google_genai", "anthropic", "mcp"):
        logging.getLogger(library_logger).setLevel(logging.WARNING)
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / TOOL_JOURNAL_NAME
    handler = logging.FileHandler(journal_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    tools_logger = logging.getLogger("agent_tools")
    tools_logger.addHandler(handler)
    tools_logger.propagate = False
    return journal_path


def parse_arguments() -> argparse.Namespace:
    """Lit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        prog="python -m agent", description="Traitement des demandes de réservation de groupe (E07)."
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_DIR, help="Dossier de sortie (par défaut : agent/output)."
    )
    parser.add_argument("--only", help="Ne traiter qu'une demande (par exemple demande_01_mariage).")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Réinitialise la boîte et le planning du kit, et repart d'une synthèse vide.",
    )
    return parser.parse_args()


def check_only(only: str | None, inbox_dir: Path) -> None:
    """Vérifie --only avant de démarrer le serveur MCP : un message clair plutôt qu'une trace d'erreur."""
    if only is None:
        return
    available = sorted(path.stem for path in inbox_dir.glob("*.eml"))
    if only not in available:
        listed = ", ".join(available) or "aucune (lancer avec --reset)"
        raise SystemExit(f"Demande inconnue : « {only} ». Demandes disponibles : {listed}")


def leaf_errors(group: BaseExceptionGroup) -> list[BaseException]:
    """Erreurs d'un groupe d'exceptions (anyio les regroupe), groupes imbriqués compris."""
    return [
        leaf
        for error in group.exceptions
        for leaf in (leaf_errors(error) if isinstance(error, BaseExceptionGroup) else [error])
    ]


def run_batch(provider: LLMProvider, output_dir: Path, only: str | None) -> None:
    """Lance le traitement ; une erreur attendue (même regroupée par anyio) arrête le script avec son message."""
    failure = None
    try:
        anyio.run(run, provider, output_dir, only)
    except* (ValueError, OSError, sqlite3.Error, LLMError, ToolError) as group:
        failure = "; ".join(str(error) or type(error).__name__ for error in leaf_errors(group))
    if failure is not None:
        raise SystemExit(f"Traitement interrompu : {failure}")


def main() -> None:
    """Point d'entrée du script."""
    arguments = parse_arguments()
    journal_path = configure_logging(arguments.output)
    logger.info("Journal des appels d'outils : %s", journal_path)
    load_dotenv(ENV_PATH)
    if arguments.reset:
        # init_donnees réinitialise toujours hotel.db et boite/ du kit, sans lire KIT_BASE ni KIT_BOITE.
        if os.environ.get("KIT_BASE") or os.environ.get("KIT_BOITE"):
            raise SystemExit("--reset ne réinitialise que hotel.db et boite/ du kit : retirer KIT_BASE et KIT_BOITE.")
        init_donnees.initialiser()
        # Boîte et brouillons réinitialisés : les résultats cumulés ne correspondent plus à rien.
        for name in (SYNTHESIS_NAME, RESULTS_NAME):
            (arguments.output / name).unlink(missing_ok=True)
    check_only(arguments.only, mailbox_dir() / "inbox")
    try:
        provider = get_provider(provider=LLM_PROVIDER, model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    except LLMError as error:
        raise SystemExit(str(error)) from error
    logger.info("Modèle utilisé : %s", provider.model)
    run_batch(provider, arguments.output, arguments.only)


if __name__ == "__main__":
    main()
