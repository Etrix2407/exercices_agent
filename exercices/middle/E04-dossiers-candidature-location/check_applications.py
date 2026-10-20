"""Contrôle des dossiers de candidature locative (E04, niveau 1).

Pour chaque dossier de candidat, lance l'agent verification_doc avec ses outils (grille, liste, lecture,
écriture de la relance), lit son JSON final, puis écrit un tableau de synthèse et les résultats bruts.
L'agent ne classe pas les candidats et n'envoie aucun courriel : il n'écrit que des brouillons de relance.

Usage : python check_applications.py [--output output] [--only marc-dubois] [--grid grille.json]
        [--candidates fixtures/candidats]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent_tools import (
    build_tools,
    list_candidate_files,
    load_grid_pieces,
    matching_files,
    relance_name,
)
from llm_providers import LLMError, LLMProvider, get_provider
from llm_providers.base import LLMBatchError, ToolSpec

# Réglages du modèle propres à cet exercice (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et température par défaut.
LLM_PROVIDER = "gemini"
LLM_MODEL = "gemini-3.5-flash-lite"
# Température basse : résultats plus réguliers d'un lancement à l'autre. Ignorée par Claude.
LLM_TEMPERATURE = 0.2

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parents[1] / ".env"
PROMPT_PATH = BASE_DIR / "prompt_sys_verification_doc.md"
GRID_PATH = BASE_DIR / "grille.json"
CANDIDATES_DIR = BASE_DIR / "candidats"
OUTPUT_DIR = BASE_DIR / "output"
SYNTHESIS_NAME = "synthese.md"
RESULTS_NAME = "resultats.json"
TOOL_JOURNAL_NAME = "journal_outils.txt"
# Le nom du propriétaire n'est dans aucune donnée : le gestionnaire le complète avant l'envoi.
OWNER_PLACEHOLDER = "[à compléter]"
AGENCY_NAME = "L'agence Habitat Delorme"
OWNER_DRAFT_SKIPPED_NOTE = "transmission non écrite : points à vérifier"
# Longueur maximale d'une relance, fixée par le prompt.
MAX_RELANCE_WORDS = 120

# Statuts que l'agent peut renvoyer ; « non_traite » est réservé à l'orchestrateur (lot arrêté).
STATUSES = ("complet", "incomplet", "a_verifier", "hors_perimetre", "erreur")
STATUS_LABELS = {"a_verifier": "à vérifier", "hors_perimetre": "hors périmètre", "non_traite": "non traité"}
BATCH_STOP_NOTE = "non traité : lot arrêté (quota épuisé ou configuration refusée), relancer avec --only"
LIST_FIELDS = ("pieces_manquantes", "incoherences", "points_a_verifier", "sources")

# (dossier du candidat, grille, dossier de sortie) -> outils de l'agent.
ToolsFactory = Callable[[Path, Path, Path], list[ToolSpec]]

# Seuls motifs que le filet peut contredire : « manquante » (début du motif) ou un nom différent.
# Tout autre motif (périmée, expirée, trop ancienne, vide…) garde la pièce : le texte du modèle n'est pas fiable.
CORRECTABLE_REASON = re.compile(r"^\s*manquant|\bnom\b", re.IGNORECASE)

logger = logging.getLogger(__name__)


class AgentOutputError(ValueError):
    """Réponse finale de l'agent illisible ou non conforme au format attendu."""


@dataclass
class ApplicationResult:
    """Résultat du contrôle d'un dossier, repris dans la synthèse.

    Exception à la règle des identifiants en anglais : les champs reprennent les clés JSON françaises
    du prompt (statut, pieces_manquantes…), qui forment le contrat avec l'agent et le format de resultats.json.
    """

    folder: str
    statut: str
    candidat: str = ""
    pieces_manquantes: list[Any] = field(default_factory=list)
    incoherences: list[str] = field(default_factory=list)
    relance_fichier: str = ""
    points_a_verifier: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    transmission_fichier: str = ""


def transmission_name(folder: str) -> str:
    """Nom du brouillon de transmission au propriétaire pour un dossier complet."""
    return f"transmission_{folder}.txt"


def format_date(iso_date: str) -> str:
    """Convertit une date AAAA-MM-JJ en JJ/MM/AAAA (inchangée si le format est autre)."""
    try:
        return date.fromisoformat(iso_date).strftime("%d/%m/%Y")
    except ValueError:
        return iso_date


def list_documents_by_piece(grid: dict[str, Any], sources: list[str]) -> list[str]:
    """Associe les fichiers lus par l'agent aux pièces de la grille (motifs), garant compris."""
    pieces = grid.get("pieces_candidat", []) + grid.get("garant", {}).get("pieces_garant", [])
    lines = []
    for piece in pieces:
        motifs = piece.get("motifs", [])
        files = sorted(name for name in sources if any(fnmatch(name.lower(), motif) for motif in motifs))
        if files:
            lines.append(f"- {piece.get('court', piece.get('id', '?'))} : {', '.join(files)}")
    return lines


def format_owner_draft(result: ApplicationResult, grid: dict[str, Any]) -> str:
    """Brouillon du courriel de transmission d'un dossier complet au propriétaire."""
    housing = grid.get("logement", {})
    reference = housing.get("reference", "")
    address = housing.get("adresse_fictive", "")
    lines = [
        f"Objet : dossier de candidature complet – logement {reference} – {result.candidat}",
        "",
        f"Bonjour {OWNER_PLACEHOLDER},",
        "",
        f"Nous vous transmettons le dossier de candidature de {result.candidat} pour le logement {reference}"
        + (f" ({address})" if address else "")
        + ". Toutes les pièces exigées par notre grille sont présentes et à jour à la date du "
        + f"{format_date(str(grid.get('date_reference_controle', '')))}.",
        "",
        "Pièces du dossier (jointes à ce courriel) :",
        *list_documents_by_piece(grid, result.sources),
        "",
        "L'étude du dossier et la décision d'attribution vous reviennent.",
        "",
        "Bien cordialement,",
        AGENCY_NAME,
        "",
    ]
    return "\n".join(lines)


def write_owner_draft(result: ApplicationResult, grid: dict[str, Any], output_dir: Path) -> None:
    """Écrit le brouillon de transmission au propriétaire si le dossier est complet et sans point à vérifier.

    Un dossier « complet » qui garde des points à vérifier (pièce illisible, relance contraire au statut…)
    ne part pas chez le propriétaire : le point est signalé au gestionnaire à la place.
    """
    if result.statut != "complet":
        return
    if result.points_a_verifier:
        result.points_a_verifier.append(OWNER_DRAFT_SKIPPED_NOTE)
        return
    name = transmission_name(result.folder)
    (output_dir / name).write_text(format_owner_draft(result, grid), encoding="utf-8")
    result.transmission_fichier = name


def list_candidate_dirs(candidates_dir: Path, only: str | None = None) -> list[Path]:
    """Renvoie les sous-dossiers de candidats triés, ou le seul dossier demandé."""
    folders = sorted(path for path in candidates_dir.iterdir() if path.is_dir())
    if only is None:
        return folders
    selected = [path for path in folders if path.name == only]
    if not selected:
        available = ", ".join(path.name for path in folders)
        raise ValueError(f"Dossier inconnu : « {only} ». Dossiers disponibles : {available}")
    return selected


def extract_json_text(text: str) -> str:
    """Retire les balises ```json éventuelles et garde l'objet JSON le plus externe."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        raise AgentOutputError("aucun objet JSON dans la réponse")
    return cleaned[start : end + 1]


def parse_agent_output(folder: str, text: str) -> ApplicationResult:
    """Transforme la réponse finale de l'agent en résultat validé."""
    try:
        data = json.loads(extract_json_text(text))
    except json.JSONDecodeError as error:
        raise AgentOutputError(f"JSON invalide ({error.msg})") from error
    if not isinstance(data, dict):
        raise AgentOutputError("la réponse n'est pas un objet JSON")
    statut = data.get("statut")
    if statut not in STATUSES:
        raise AgentOutputError(f"statut inconnu : {statut!r}")
    for name in LIST_FIELDS:
        if not isinstance(data.get(name, []), list):
            raise AgentOutputError(f"« {name} » doit être une liste")
    return ApplicationResult(
        folder=folder,
        statut=statut,
        candidat=str(data.get("candidat", "")),
        pieces_manquantes=data.get("pieces_manquantes", []),
        incoherences=[str(item) for item in data.get("incoherences", [])],
        relance_fichier=str(data.get("relance_fichier", "")),
        points_a_verifier=[str(item) for item in data.get("points_a_verifier", [])],
        sources=[str(item) for item in data.get("sources", [])],
    )


def check_relance(result: ApplicationResult, output_dir: Path) -> None:
    """Contrôle que la relance existe si et seulement si le dossier est incomplet."""
    expected = relance_name(result.folder)
    written = (output_dir / expected).is_file()
    if result.statut == "incomplet" and not written:
        result.points_a_verifier.append(f"relance non écrite ({expected} absent)")
    elif result.statut != "incomplet" and written:
        # Relance contraire au statut final : on la retire pour qu'elle ne parte pas par erreur.
        (output_dir / expected).unlink()
        written = False
        result.points_a_verifier.append(
            f"relance écrite alors que le dossier n'est pas incomplet : {expected} supprimée, statut à confirmer"
        )
    # On n'affiche que la relance réellement présente, pas le nom annoncé par l'agent.
    result.relance_fichier = expected if written else ""
    if written:
        words = len((output_dir / expected).read_text(encoding="utf-8").split())
        if words > MAX_RELANCE_WORDS:
            result.points_a_verifier.append(f"relance trop longue : {words} mots (limite {MAX_RELANCE_WORDS})")


def check_sources(result: ApplicationResult, candidate_dir: Path) -> None:
    """Signale les sources citées par l'agent qui ne correspondent à aucun fichier du dossier."""
    existing = set(list_candidate_files(candidate_dir))
    unknown = [source for source in result.sources if source not in existing]
    if unknown:
        result.points_a_verifier.append(f"sources absentes du dossier : {', '.join(unknown)}")


def remove_previous_drafts(folder: str, output_dir: Path) -> None:
    """Supprime les brouillons d'une exécution précédente : ils ne doivent pas passer pour actuels."""
    (output_dir / relance_name(folder)).unlink(missing_ok=True)
    (output_dir / transmission_name(folder)).unlink(missing_ok=True)


def check_application(
    candidate_dir: Path,
    grid_path: Path,
    output_dir: Path,
    provider: LLMProvider,
    system_prompt: str,
    tools_factory: ToolsFactory,
) -> ApplicationResult:
    """Lance l'agent sur un dossier ; une erreur de modèle ou de format donne le statut « erreur ».

    Une LLMBatchError (quota épuisé, configuration refusée) est propagée : elle arrête tout le lot.
    """
    folder = candidate_dir.name
    remove_previous_drafts(folder, output_dir)
    try:
        answer = provider.run_agent(
            system_prompt, f"Dossier : {folder}", tools_factory(candidate_dir, grid_path, output_dir)
        )
        result = parse_agent_output(folder, answer)
        check_sources(result, candidate_dir)
    except LLMBatchError:
        raise
    except (LLMError, AgentOutputError) as error:
        logger.error("%s : %s", folder, error)
        result = ApplicationResult(folder=folder, statut="erreur", points_a_verifier=[str(error)])
    drop_pieces_found_by_code(result, candidate_dir, grid_path, output_dir)
    check_relance(result, output_dir)
    # Après check_relance, qui peut ajouter un point : « complet » n'est gardé que sans aucun point à vérifier.
    enforce_complete_status(result)
    return result


def drop_pieces_found_by_code(
    result: ApplicationResult, candidate_dir: Path, grid_path: Path, output_dir: Path
) -> None:
    """Filet de sécurité : retire une pièce déclarée manquante alors que le dossier a assez de fichiers pour elle.

    Une pièce n'est retirée que si son motif dit « manquante » ou parle d'un nom différent (une incohérence,
    pas une pièce manquante) ; tout autre motif la garde. S'il ne reste aucune pièce manquante, le statut est
    recalculé selon les règles de la grille et la relance, écrite à cause de l'erreur corrigée, est supprimée.
    """
    if result.statut != "incomplet":
        return
    files = list_candidate_files(candidate_dir)
    present = {
        piece.label.casefold()
        for piece in load_grid_pieces(grid_path)
        if len(matching_files(piece, files)) >= piece.minimum
    }
    kept, dropped = [], []
    for piece in result.pieces_manquantes:
        name = str(piece.get("piece", "")) if isinstance(piece, dict) else str(piece)
        reason = str(piece.get("motif", "")) if isinstance(piece, dict) else ""
        if name.strip().casefold() in present and CORRECTABLE_REASON.search(reason):
            dropped.append(name)
        else:
            kept.append(piece)
    if not dropped:
        return
    result.pieces_manquantes = kept
    previous = result.statut
    if not kept:
        result.statut = "a_verifier" if result.incoherences or result.points_a_verifier else "complet"
        (output_dir / relance_name(result.folder)).unlink(missing_ok=True)
    logger.warning(
        "%s : pièce(s) déclarée(s) manquante(s) mais présente(s) dans le dossier, retirée(s) : %s (statut %s → %s)",
        result.folder,
        ", ".join(dropped),
        previous,
        result.statut,
    )


def enforce_complete_status(result: ApplicationResult) -> None:
    """« complet » exige l'absence de point à vérifier (pièce illisible…) : sinon le dossier passe à vérifier."""
    if result.statut == "complet" and result.points_a_verifier:
        result.statut = "a_verifier"
        result.points_a_verifier.append("statut « complet » ramené à « à vérifier » : des points restent à vérifier")


def table_cell(text: str) -> str:
    """Neutralise les caractères qui casseraient une ligne de tableau Markdown."""
    return " ".join(text.split()).replace("|", "\\|")


def format_missing(pieces: list[Any]) -> str:
    """Met la liste des pièces manquantes sur une ligne : « pièce (motif) »."""
    labels = []
    for piece in pieces:
        if isinstance(piece, dict):
            name, reason = piece.get("piece", "?"), piece.get("motif", "")
            labels.append(f"{name} ({reason})" if reason else str(name))
        else:
            labels.append(str(piece))
    return "; ".join(labels)


def format_synthesis(
    results: list[ApplicationResult], model: str, reference_date: str, total: int | None = None
) -> str:
    """Construit le tableau de synthèse des dossiers, au format Markdown (avancement si le lot est en cours)."""
    rows = []
    for item in results:
        cells = [
            item.folder,
            item.candidat or "—",
            STATUS_LABELS.get(item.statut, item.statut),
            format_missing(item.pieces_manquantes) or "—",
            "; ".join(item.incoherences) or "—",
            item.relance_fichier or item.transmission_fichier or "—",
        ]
        rows.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    points = [f"- {item.folder} : {table_cell(point)}" for item in results for point in item.points_a_verifier]
    lines = [
        "# Synthèse des dossiers de candidature",
        "",
        f"Modèle : `{model}`",
        f"Date de référence (grille) : {reference_date or 'non précisée'}",
        *([f"Lot en cours : {len(results)}/{total} dossiers traités."] if total and len(results) < total else []),
        "",
        "| Dossier | Candidat | Statut | Pièces manquantes | Incohérences | Brouillon |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    if points:
        lines += ["## Points à vérifier", "", *points, ""]
    lines += ["Aucun classement des candidats : l'étude des dossiers reste du ressort du gestionnaire.", ""]
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> None:
    """Écrit dans un fichier temporaire du même dossier puis le renomme : jamais de fichier à moitié écrit."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(
    results: list[ApplicationResult], model: str, reference_date: str, output_dir: Path, total: int
) -> str:
    """Écrit la synthèse et les résultats bruts (de façon atomique) ; renvoie la synthèse."""
    synthesis = format_synthesis(results, model, reference_date, total)
    write_atomic(output_dir / SYNTHESIS_NAME, synthesis)
    raw = json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
    write_atomic(output_dir / RESULTS_NAME, raw + "\n")
    return synthesis


def stop_batch(error: LLMBatchError, current: str, pending: list[Path], output_dir: Path) -> list[ApplicationResult]:
    """Lot arrêté : dossier en cours en « erreur », dossiers suivants « non_traite » sans ancien brouillon."""
    logger.error("Arrêt du lot : %s", error)
    # Un brouillon écrit avant l'arrêt n'a pas de statut fiable : il est retiré.
    remove_previous_drafts(current, output_dir)
    failed = ApplicationResult(folder=current, statut="erreur", points_a_verifier=[str(error)])
    skipped = []
    for candidate_dir in pending:
        remove_previous_drafts(candidate_dir.name, output_dir)
        skipped.append(
            ApplicationResult(folder=candidate_dir.name, statut="non_traite", points_a_verifier=[BATCH_STOP_NOTE])
        )
    return [failed, *skipped]


def check_applications(
    candidates_dir: Path,
    grid_path: Path,
    output_dir: Path,
    provider: LLMProvider,
    only: str | None = None,
    tools_factory: ToolsFactory | None = None,
) -> list[ApplicationResult]:
    """Contrôle chaque dossier et réécrit la synthèse et les résultats bruts après chacun.

    Quota épuisé ou configuration refusée (LLMBatchError) : le lot s'arrête, la synthèse est quand même écrite.
    Toute autre erreur inattendue ne touche que le dossier en cours (statut « erreur »).
    """
    tools_factory = tools_factory or build_tools
    folders = list_candidate_dirs(candidates_dir, only)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    reference_date = str(grid.get("date_reference_controle", ""))
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[ApplicationResult] = []
    synthesis = write_outputs(results, provider.model, reference_date, output_dir, len(folders))
    for position, candidate_dir in enumerate(folders, start=1):
        folder = candidate_dir.name
        logger.info("Dossier %d/%d : %s — en cours…", position, len(folders), folder)
        try:
            result = check_application(candidate_dir, grid_path, output_dir, provider, system_prompt, tools_factory)
            write_owner_draft(result, grid, output_dir)
        except LLMBatchError as error:
            results += stop_batch(error, folder, folders[position:], output_dir)
            synthesis = write_outputs(results, provider.model, reference_date, output_dir, len(folders))
            break
        except Exception as error:  # un dossier en échec ne doit pas faire perdre le lot
            logger.exception("%s : erreur inattendue", folder)
            remove_previous_drafts(folder, output_dir)
            message = f"erreur inattendue ({type(error).__name__} : {error}), voir le terminal"
            result = ApplicationResult(folder=folder, statut="erreur", points_a_verifier=[message])
        logger.info("→ %s : %s", result.folder, STATUS_LABELS.get(result.statut, result.statut))
        results.append(result)
        synthesis = write_outputs(results, provider.model, reference_date, output_dir, len(folders))

    logger.info("\n%s", synthesis)
    logger.info("Synthèse, résultats et brouillons écrits dans %s", output_dir)
    return results


def parse_arguments() -> argparse.Namespace:
    """Lit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Contrôle des dossiers de candidature locative (E04).")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Dossier de sortie (par défaut : output).")
    parser.add_argument("--only", help="Ne traiter qu'un dossier de candidat (par exemple marc-dubois).")
    parser.add_argument("--grid", type=Path, default=GRID_PATH, help="Grille des pièces (par défaut : grille.json).")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=CANDIDATES_DIR,
        help="Dossier des candidats (par défaut : candidats ; dossiers de test : fixtures/candidats).",
    )
    return parser.parse_args()


def configure_tool_journal(output_dir: Path) -> Path:
    """Envoie les appels d'outils dans un fichier texte plutôt que dans le terminal."""
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / TOOL_JOURNAL_NAME
    handler = logging.FileHandler(journal_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    tools_logger = logging.getLogger("agent_tools")
    tools_logger.addHandler(handler)
    tools_logger.propagate = False
    return journal_path


def main() -> None:
    """Point d'entrée du script."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Les SDK journalisent chaque requête HTTP : on ne garde que leurs avertissements et erreurs.
    for library_logger in ("httpx", "google_genai", "anthropic"):
        logging.getLogger(library_logger).setLevel(logging.WARNING)
    arguments = parse_arguments()
    journal_path = configure_tool_journal(arguments.output)
    logger.info("Journal des appels d'outils : %s", journal_path)
    load_dotenv(ENV_PATH)
    try:
        provider = get_provider(provider=LLM_PROVIDER, model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    except LLMError as error:
        raise SystemExit(str(error)) from error
    logger.info("Modèle utilisé : %s", provider.model)
    try:
        check_applications(arguments.candidates, arguments.grid, arguments.output, provider, arguments.only)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
