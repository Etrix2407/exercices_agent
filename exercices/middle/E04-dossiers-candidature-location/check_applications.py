"""Contrôle des dossiers de candidature locative (E04, niveau 1).

Pour chaque dossier de candidat, lance l'agent verification_doc avec ses outils (grille, liste, lecture,
écriture de la relance), lit son JSON final, puis écrit un tableau de synthèse et les résultats bruts.
L'agent ne classe pas les candidats et n'envoie aucun courriel : il n'écrit que des brouillons de relance.

Usage : python check_applications.py [--output output] [--only marc-dubois] [--grid grille.json]
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from llm_providers import LLMError, LLMProvider, get_provider
from llm_providers.base import ToolSpec

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

STATUSES = ("complet", "incomplet", "a_verifier", "hors_perimetre", "erreur")
STATUS_LABELS = {"a_verifier": "à vérifier", "hors_perimetre": "hors périmètre"}
LIST_FIELDS = ("pieces_manquantes", "incoherences", "points_a_verifier", "sources")

# (dossier du candidat, grille, dossier de sortie) -> outils de l'agent.
ToolsFactory = Callable[[Path, Path, Path], list[ToolSpec]]

logger = logging.getLogger(__name__)


class AgentOutputError(ValueError):
    """Réponse finale de l'agent illisible ou non conforme au format attendu."""


@dataclass
class ApplicationResult:
    """Résultat du contrôle d'un dossier, repris dans la synthèse."""

    folder: str
    statut: str
    candidat: str = ""
    pieces_manquantes: list[Any] = field(default_factory=list)
    incoherences: list[str] = field(default_factory=list)
    relance_fichier: str = ""
    points_a_verifier: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    transmission_fichier: str = ""


def relance_name(folder: str) -> str:
    """Nom du fichier de relance attendu pour un dossier."""
    return f"relance_{folder}.txt"


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
    """Écrit le brouillon de transmission au propriétaire si le dossier est complet."""
    if result.statut != "complet":
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


def default_tools_factory() -> ToolsFactory:
    """Renvoie la fabrique d'outils réelle (import local : les tests peuvent s'en passer)."""
    from agent_tools import build_tools

    return build_tools


def check_application(
    candidate_dir: Path,
    grid_path: Path,
    output_dir: Path,
    provider: LLMProvider,
    system_prompt: str,
    tools_factory: ToolsFactory,
) -> ApplicationResult:
    """Lance l'agent sur un dossier ; une erreur de modèle ou de format donne le statut « erreur »."""
    folder = candidate_dir.name
    # Les brouillons d'une exécution précédente ne doivent pas passer pour actuels.
    (output_dir / relance_name(folder)).unlink(missing_ok=True)
    (output_dir / transmission_name(folder)).unlink(missing_ok=True)
    try:
        answer = provider.run_agent(
            system_prompt, f"Dossier : {folder}", tools_factory(candidate_dir, grid_path, output_dir)
        )
        result = parse_agent_output(folder, answer)
    except (LLMError, AgentOutputError) as error:
        logger.error("%s : %s", folder, error)
        result = ApplicationResult(folder=folder, statut="erreur", points_a_verifier=[str(error)])
    check_relance(result, output_dir)
    return result


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


def format_synthesis(results: list[ApplicationResult], model: str, reference_date: str) -> str:
    """Construit le tableau de synthèse des dossiers, au format Markdown."""
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


def check_applications(
    candidates_dir: Path,
    grid_path: Path,
    output_dir: Path,
    provider: LLMProvider,
    only: str | None = None,
    tools_factory: ToolsFactory | None = None,
) -> list[ApplicationResult]:
    """Contrôle chaque dossier, puis écrit la synthèse et les résultats bruts."""
    tools_factory = tools_factory or default_tools_factory()
    folders = list_candidate_dirs(candidates_dir, only)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    reference_date = str(grid.get("date_reference_controle", ""))
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for position, candidate_dir in enumerate(folders, start=1):
        logger.info("Dossier %d/%d : %s — en cours…", position, len(folders), candidate_dir.name)
        result = check_application(candidate_dir, grid_path, output_dir, provider, system_prompt, tools_factory)
        write_owner_draft(result, grid, output_dir)
        logger.info("→ %s : %s", result.folder, STATUS_LABELS.get(result.statut, result.statut))
        results.append(result)

    synthesis = format_synthesis(results, provider.model, reference_date)
    (output_dir / SYNTHESIS_NAME).write_text(synthesis, encoding="utf-8")
    raw = json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
    (output_dir / RESULTS_NAME).write_text(raw + "\n", encoding="utf-8")
    logger.info("\n%s", synthesis)
    logger.info("Synthèse, résultats et brouillons écrits dans %s", output_dir)
    return results


def parse_arguments() -> argparse.Namespace:
    """Lit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Contrôle des dossiers de candidature locative (E04).")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Dossier de sortie (par défaut : output).")
    parser.add_argument("--only", help="Ne traiter qu'un dossier de candidat (par exemple marc-dubois).")
    parser.add_argument("--grid", type=Path, default=GRID_PATH, help="Grille des pièces (par défaut : grille.json).")
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
        check_applications(CANDIDATES_DIR, arguments.grid, arguments.output, provider, arguments.only)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
