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
from datetime import date, datetime
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
    traite_le: str = ""
    changements: list[str] = field(default_factory=list)


# Statuts qui ne remplacent jamais un résultat valide déjà enregistré pour la même demande.
FAILED_STATUSES = ("erreur", "non_traitee")
FAILURE_PREFIX = "dernier traitement en échec"


def load_previous_results(output_dir: Path) -> dict[str, RequestResult]:
    """Relit resultats.json : les demandes déjà analysées restent dans la synthèse d'un lancement à l'autre."""
    path = output_dir / RESULTS_NAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = set(RequestResult.__dataclass_fields__)
        items = [RequestResult(**{key: value for key, value in entry.items() if key in known}) for entry in raw]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        logger.warning("Résultats précédents illisibles (%s) : la synthèse repart de zéro.", error)
        return {}
    return {item.demande_id: item for item in items}


def describe_changes(previous: RequestResult | None, current: RequestResult) -> list[str]:
    """Liste ce qui a changé depuis la dernière analyse de la même demande (statut, dates, effectif…)."""
    if previous is None:
        return []
    old_needs, new_needs = previous.besoins or {}, current.besoins or {}
    compared = [
        ("statut", previous.statut, current.statut),
        ("arrivée", old_needs.get("date_arrivee"), new_needs.get("date_arrivee")),
        ("départ", old_needs.get("date_depart"), new_needs.get("date_depart")),
        ("effectif", old_needs.get("nb_personnes"), new_needs.get("nb_personnes")),
        ("chambres", old_needs.get("chambres"), new_needs.get("chambres")),
        ("devis", previous.devis_total, current.devis_total),
        ("informations manquantes", previous.informations_manquantes, current.informations_manquantes),
    ]
    return [
        f"{label} : {json.dumps(old, ensure_ascii=False)} → {json.dumps(new, ensure_ascii=False)}"
        for label, old, new in compared
        if old != new
    ]


def merge_result(known: dict[str, RequestResult], result: RequestResult, processed_at: str) -> None:
    """Ajoute ou met à jour une demande ; un échec ne remplace pas un résultat valide déjà enregistré."""
    previous = known.get(result.demande_id)
    if result.statut in FAILED_STATUSES and previous is not None and previous.statut not in FAILED_STATUSES:
        reason = "; ".join(result.points_a_verifier) or result.statut
        previous.points_a_verifier = [
            point for point in previous.points_a_verifier if not point.startswith(FAILURE_PREFIX)
        ] + [f"{FAILURE_PREFIX} ({processed_at}), résultat précédent conservé : {reason}"]
        return
    result.traite_le = processed_at
    result.changements = describe_changes(previous, result)
    known[result.demande_id] = result


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
    result = build_result(request_id, tools, final_text)
    if result.brouillon:
        result.brouillon = replace_previous_draft(kit, request_id, result.brouillon)
    return result


def replace_previous_draft(kit: KitCaller, request_id: str, new_id: str, drafts_dir: Path | None = None) -> str:
    """Remplace l'ancien brouillon de la demande par le nouveau, sous le même identifiant.

    Le kit numérote les brouillons en comptant les fichiers : supprimer un ancien brouillon ferait réutiliser
    un numéro existant. Le nouveau fichier prend donc la place de l'ancien (os.replace), ce qui garde
    un numéro stable par demande et un nombre de fichiers cohérent.
    """
    drafts_dir = drafts_dir or init_donnees.BOITE / "brouillons"
    previous = sorted(
        draft["id"]
        for draft in kit.call("lister_brouillons", {})["brouillons"]
        if draft.get("pour") == request_id and draft["id"] != new_id
    )
    if not previous:
        return new_id
    target, *duplicates = previous
    os.replace(drafts_dir / f"{new_id}.eml", drafts_dir / f"{target}.eml")
    logger.info("Brouillon %s de %s remplacé par la nouvelle version.", target, request_id)
    if duplicates:
        logger.warning("Anciens brouillons en double pour %s : %s (à écarter à la main).", request_id, duplicates)
    return target


def table_cell(text: str) -> str:
    """Neutralise les caractères qui casseraient une ligne de tableau Markdown."""
    return " ".join(text.split()).replace("|", "\\|")


def format_synthesis(
    results: list[RequestResult],
    model: str,
    planning_unchanged: bool,
    progress: tuple[int, int] | None = None,
) -> str:
    """Construit le tableau de synthèse de toutes les demandes analysées, au format Markdown.

    progress = (demandes traitées, demandes prévues) pour le lancement en cours : tant qu'il n'est pas
    fini, une ligne d'avancement l'indique.
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
            item.traite_le or "—",
            "; ".join(item.changements) or "—",
        ]
        rows.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    points = [f"- {item.demande_id} : {table_cell(point)}" for item in results for point in item.points_a_verifier]
    lines = [
        "# Synthèse des demandes de groupe",
        "",
        f"Modèle : `{model}`",
        "Planning inchangé : " + ("oui" if planning_unchanged else "**NON — vérifier immédiatement**"),
    ]
    if progress is not None and progress[0] < progress[1]:
        lines.append(f"Avancement : {progress[0]}/{progress[1]} demandes traitées (lot en cours)")
    lines += [
        "",
        (
            "| Demande | Statut | Séjour | Informations manquantes | Dates alternatives | Devis (EUR TTC) | Brouillon "
            "| Traité le | Changements |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
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
    progress: tuple[int, int] | None = None,
) -> str:
    """Écrit la synthèse et les résultats bruts (de façon atomique) ; renvoie la synthèse."""
    synthesis = format_synthesis(results, model, planning_unchanged, progress)
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

    La synthèse est cumulative : les demandes analysées lors des lancements précédents restent,
    et une demande traitée à nouveau voit sa ligne mise à jour (avec la liste des changements).
    Renvoie les résultats du lancement en cours uniquement.
    """
    request_ids = [item["id"] for item in kit.call("lister_demandes", {})["demandes"]]
    if only is not None:
        if only not in request_ids:
            raise ValueError(f"Demande inconnue : « {only} ». Demandes disponibles : {', '.join(request_ids)}")
        request_ids = [only]
    system_prompt = load_system_prompt(date.today())
    before = planning_fingerprint()
    known = load_previous_results(output_dir)
    results: list[RequestResult] = []
    saved: list[RequestResult] = []

    def save() -> str:
        """Seul point d'écriture : recalcule l'empreinte du planning et réécrit synthèse et résultats."""
        for result in results[len(saved) :]:
            merge_result(known, result, datetime.now().strftime("%Y-%m-%d %H:%M"))
        saved.extend(results[len(saved) :])
        unchanged = planning_fingerprint() == before
        ordered = [known[key] for key in sorted(known)]
        return write_outputs(ordered, provider.model, unchanged, output_dir, (len(results), len(request_ids)))

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
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Réinitialise la boîte et le planning du kit, et repart d'une synthèse vide.",
    )
    return parser.parse_args()


def main() -> None:
    """Point d'entrée du script."""
    arguments = parse_arguments()
    journal_path = configure_logging(arguments.output)
    logger.info("Journal des appels d'outils : %s", journal_path)
    load_dotenv(ENV_PATH)
    if arguments.reset:
        init_donnees.initialiser()
        # Boîte et brouillons réinitialisés : les résultats cumulés ne correspondent plus à rien.
        for name in (SYNTHESIS_NAME, RESULTS_NAME):
            (arguments.output / name).unlink(missing_ok=True)
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
