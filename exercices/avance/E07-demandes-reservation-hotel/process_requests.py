"""Traitement des demandes de réservation de groupe (E07, niveau 2).

Démarre le serveur MCP du kit, puis lance une session d'agent par demande avec les outils read_email,
read_planning, read_grille, calc_devis et write_draft. Contrôle ensuite chaque résultat en code
(devis recalculé, dates alternatives revérifiées, planning inchangé) et écrit une synthèse.
L'agent ne réserve rien et n'envoie rien : il n'écrit que des fiches et des brouillons.

Usage : python process_requests.py [--reset] [--only demande_01_mariage] [--output output]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import anyio
from dotenv import load_dotenv

import init_donnees
import planning
from llm_providers import LLMError, LLMProvider, get_provider
from llm_providers.base import LLMBatchError, ToolError
from mcp_bridge import HotelTools, KitCaller, KitClient, kit_session, quote_arguments, rooms_by_type

# Réglages du modèle propres à cet exercice (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et température par défaut.
LLM_PROVIDER = "gemini"
LLM_MODEL = "gemini-3.8-flash"
# Température : None garde la valeur par défaut du modèle (recommandé pour Gemini 3).
# Plages acceptées : Gemini de 0 à 2 ; Claude de 0 à 1, mais les modèles Claude actuels (Opus 5.5)
# la refusent : elle est alors ignorée avec un avertissement.
LLM_TEMPERATURE = None

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parents[1] / ".env"
PROMPT_PATH = BASE_DIR / "prompt_sys_reservation.md"
OUTPUT_DIR = BASE_DIR / "output"
SYNTHESIS_NAME = "synthese.md"
RESULTS_NAME = "resultats.json"
TOOL_JOURNAL_NAME = "journal_outils.txt"
# Nombre maximal d'appels au modèle par demande : au-delà, LLMError plutôt qu'une boucle sans fin.
MAX_STEPS = 20
QUOTA_NOTE = "non traitée : lot arrêté (quota épuisé ou configuration refusée), relancer avec --only"
ALTERNATIVE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:→|->|au|à)\s*(\d{4}-\d{2}-\d{2})")

# (outils du kit, identifiant de la demande) -> outils de l'agent pour cette demande.
ToolsFactory = Callable[[KitCaller, str], HotelTools]

logger = logging.getLogger(__name__)


@dataclass
class RequestResult:
    """Résultat d'une demande, repris dans la synthèse."""

    demande_id: str
    statut: str
    besoins: dict[str, Any] = field(default_factory=dict)
    informations_manquantes: list[str] = field(default_factory=list)
    dates_alternatives: list[str] = field(default_factory=list)
    devis_total: float | None = None
    brouillon: str = ""
    points_a_verifier: list[str] = field(default_factory=list)


def load_system_prompt(reference_date: date) -> str:
    """Lit le prompt, retire le commentaire de tête et insère la date de référence."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = re.sub(r"^\s*<!--.*?-->\s*", "", text, flags=re.DOTALL)
    return text.replace("{date_reference}", reference_date.strftime("%d/%m/%Y"))


def planning_fingerprint() -> str:
    """Empreinte du contenu du planning et des pré-réservations : prouve que rien n'a été réservé ni déplacé."""
    digest = hashlib.sha256()
    with closing(sqlite3.connect(f"file:{init_donnees.BASE}?mode=ro", uri=True)) as connection:
        for table in ("occupation_chambres", "occupation_salles", "pre_reservations"):
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3"):
                digest.update(repr((table, row)).encode("utf-8"))
    return digest.hexdigest()


def check_quote(needs: dict[str, Any], announced_total: float) -> str | None:
    """Recalcule le devis à partir des besoins de la fiche et compare au total joint (contrôle manuel)."""
    try:
        expected = planning.calculer_devis(**quote_arguments(needs))["total_ttc"]
    except (ToolError, ValueError, KeyError, TypeError) as error:
        return f"devis non recalculable à partir de la fiche : {error}"
    if abs(expected - announced_total) > 0.005:
        return f"devis joint {announced_total:.2f} EUR ≠ recalcul {expected:.2f} EUR à partir de la fiche"
    return None


def check_alternatives(needs: dict[str, Any], alternatives: list[str]) -> list[str]:
    """Revérifie dans le planning que chaque période alternative a assez de chambres libres."""
    problems = []
    try:
        rooms = rooms_by_type(needs)
    except ToolError as error:
        return [f"chambres de la fiche illisibles : {error}"]
    for alternative in alternatives:
        match = ALTERNATIVE_PATTERN.search(alternative)
        if not match:
            problems.append(f"date alternative illisible : « {alternative} »")
            continue
        try:
            free = planning.disponibilites_chambres(*match.groups())["libres_sur_toute_la_periode"]
        except ValueError as error:
            problems.append(f"date alternative hors planning : « {alternative} » ({error})")
            continue
        short = {room: count for room, count in rooms.items() if count > free.get(room, 0)}
        if short:
            problems.append(f"date alternative « {alternative} » sans assez de chambres libres : {short}")
    return problems


def check_alternative_quote(quote: dict[str, Any], alternatives: list[str]) -> str | None:
    """Vérifie que le devis joint porte bien sur la première période alternative proposée."""
    match = ALTERNATIVE_PATTERN.search(alternatives[0]) if alternatives else None
    if match and (quote.get("arrivee"), quote.get("depart")) == match.groups():
        return None
    return f"devis joint ({quote.get('arrivee')} → {quote.get('depart')}) ≠ première date alternative proposée"


def build_result(request_id: str, tools: HotelTools, final_text: str) -> RequestResult:
    """Construit le résultat à partir de la fiche écrite par write_draft, puis le contrôle en code."""
    if tools.draft is None:
        return RequestResult(
            demande_id=request_id,
            statut="erreur",
            points_a_verifier=["aucune fiche ni brouillon écrit (write_draft non appelé)", final_text[:200]],
        )
    sheet = tools.draft["fiche"]
    quote = tools.draft["devis"]
    needs = sheet.get("besoins") if isinstance(sheet.get("besoins"), dict) else {}
    result = RequestResult(
        demande_id=request_id,
        statut=sheet["statut"],
        besoins=needs,
        informations_manquantes=[str(item) for item in sheet.get("informations_manquantes") or []],
        dates_alternatives=[str(item) for item in sheet.get("dates_alternatives") or []],
        devis_total=quote["total_ttc"] if quote else None,
        brouillon=str(tools.draft["brouillon"].get("brouillon", "")),
        points_a_verifier=[str(item) for item in sheet.get("points_a_verifier") or []],
    )
    if result.statut == "proposition" and quote:
        problem = check_quote(needs, quote["total_ttc"])
        if problem:
            result.points_a_verifier.append(problem)
    if result.statut == "dates_alternatives":
        if not result.dates_alternatives:
            result.points_a_verifier.append("statut « dates_alternatives » sans aucune date proposée")
        result.points_a_verifier += check_alternatives(needs, result.dates_alternatives)
        if quote:
            problem = check_alternative_quote(quote, result.dates_alternatives)
            if problem:
                result.points_a_verifier.append(problem)
    return result


def process_request(
    kit: KitCaller, request_id: str, provider: LLMProvider, system_prompt: str, tools_factory: ToolsFactory
) -> RequestResult:
    """Lance l'agent sur une demande ; une erreur de modèle donne le statut « erreur » sans bloquer le lot."""
    tools = tools_factory(kit, request_id)
    try:
        final_text = provider.run_agent(system_prompt, f"Demande : {request_id}", tools.specs(), max_steps=MAX_STEPS)
    except LLMBatchError:
        # Quota épuisé ou configuration refusée : le lot entier s'arrête (voir process_all).
        raise
    except LLMError as error:
        logger.error("%s : %s", request_id, error)
        if tools.draft is None:
            return RequestResult(demande_id=request_id, statut="erreur", points_a_verifier=[str(error)])
        final_text = ""
    return build_result(request_id, tools, final_text)


def table_cell(text: str) -> str:
    """Neutralise les caractères qui casseraient une ligne de tableau Markdown."""
    return " ".join(text.split()).replace("|", "\\|")


def format_synthesis(
    results: list[RequestResult], model: str, planning_unchanged: bool, total: int | None = None
) -> str:
    """Construit le tableau de synthèse des demandes, au format Markdown.

    Si total est fourni et que toutes les demandes ne sont pas encore traitées, ajoute une ligne
    d'avancement : la synthèse est alors un état intermédiaire du lot.
    """
    rows = []
    for item in results:
        needs = item.besoins
        stay = f"{needs.get('date_arrivee') or '?'} → {needs.get('date_depart') or '?'}" if needs else "—"
        cells = [
            item.demande_id,
            item.statut,
            stay,
            "; ".join(item.informations_manquantes) or "—",
            "; ".join(item.dates_alternatives) or "—",
            f"{item.devis_total:.2f}" if item.devis_total is not None else "—",
            item.brouillon or "—",
        ]
        rows.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    points = [f"- {item.demande_id} : {table_cell(point)}" for item in results for point in item.points_a_verifier]
    lines = [
        "# Synthèse des demandes de groupe",
        "",
        f"Modèle : `{model}`",
        "Planning inchangé : " + ("oui" if planning_unchanged else "**NON — vérifier immédiatement**"),
    ]
    if total is not None and len(results) < total:
        lines.append(f"Avancement : {len(results)}/{total} demandes traitées (lot en cours)")
    lines += [
        "",
        "| Demande | Statut | Séjour | Informations manquantes | Dates alternatives | Devis (EUR TTC) | Brouillon |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    if points:
        lines += ["## Points à vérifier", "", *points, ""]
    lines += ["Aucun envoi : le service commercial relit chaque brouillon et décide de l'envoi.", ""]
    return "\n".join(lines)


def _write_atomic(path: Path, text: str) -> None:
    """Écrit dans un fichier temporaire du même dossier puis le renomme : jamais de fichier à moitié écrit."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(
    results: list[RequestResult],
    model: str,
    planning_unchanged: bool,
    output_dir: Path,
    total: int | None = None,
) -> str:
    """Écrit la synthèse et les résultats bruts (de façon atomique) ; renvoie la synthèse."""
    synthesis = format_synthesis(results, model, planning_unchanged, total)
    _write_atomic(output_dir / SYNTHESIS_NAME, synthesis)
    raw = json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
    _write_atomic(output_dir / RESULTS_NAME, raw + "\n")
    return synthesis


def process_all(
    kit: KitCaller,
    provider: LLMProvider,
    output_dir: Path,
    only: str | None = None,
    tools_factory: ToolsFactory = HotelTools,
) -> list[RequestResult]:
    """Traite chaque demande de la boîte (ou la seule demandée) en réécrivant la synthèse après chacune.

    Les fichiers d'un lancement précédent sont écrasés dès le départ (synthèse « 0/N ») : après un
    Ctrl+C, output/ reflète donc le lot interrompu et non un ancien lot complet.
    """
    request_ids = [item["id"] for item in kit.call("lister_demandes", {})["demandes"]]
    if only is not None:
        if only not in request_ids:
            raise ValueError(f"Demande inconnue : « {only} ». Demandes disponibles : {', '.join(request_ids)}")
        request_ids = [only]
    system_prompt = load_system_prompt(date.today())
    before = planning_fingerprint()
    results: list[RequestResult] = []

    def save() -> str:
        """Seul point d'écriture : recalcule l'empreinte du planning et réécrit synthèse et résultats."""
        unchanged = planning_fingerprint() == before
        return write_outputs(results, provider.model, unchanged, output_dir, total=len(request_ids))

    synthesis = save()
    for position, request_id in enumerate(request_ids, start=1):
        logger.info("Demande %d/%d : %s — en cours…", position, len(request_ids), request_id)
        try:
            result = process_request(kit, request_id, provider, system_prompt, tools_factory)
        except LLMBatchError as error:
            logger.error("Arrêt du lot : %s", error)
            results.append(RequestResult(demande_id=request_id, statut="erreur", points_a_verifier=[str(error)]))
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
    parser = argparse.ArgumentParser(description="Traitement des demandes de réservation de groupe (E07).")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Dossier de sortie (par défaut : output).")
    parser.add_argument("--only", help="Ne traiter qu'une demande (par exemple demande_01_mariage).")
    parser.add_argument("--reset", action="store_true", help="Réinitialise la boîte et le planning du kit avant.")
    return parser.parse_args()


def main() -> None:
    """Point d'entrée du script."""
    arguments = parse_arguments()
    journal_path = configure_logging(arguments.output)
    logger.info("Journal des appels d'outils : %s", journal_path)
    load_dotenv(ENV_PATH)
    if arguments.reset:
        init_donnees.initialiser()
    try:
        provider = get_provider(provider=LLM_PROVIDER, model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    except LLMError as error:
        raise SystemExit(str(error)) from error
    logger.info("Modèle utilisé : %s", provider.model)
    try:
        anyio.run(run, provider, arguments.output, arguments.only)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
