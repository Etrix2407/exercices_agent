"""Outils de l'agent de vérification des dossiers de candidature.

Les quatre outils sont liés à UN seul dossier candidat : lire la grille, lister le dossier,
lire un fichier du dossier, écrire un fichier de sortie. Chaque appel est journalisé.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from llm_providers.base import ToolError, ToolSpec

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024
OUTPUT_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+\.txt$")
NO_ARGS_SCHEMA: dict = {"type": "object", "properties": {}}

Handler = Callable[[dict], str]


def _get_str_arg(args: object, key: str) -> str:
    """Renvoie l'argument texte `key`, ou lève ToolError s'il est absent ou mal typé."""
    if not isinstance(args, dict):
        raise ToolError("Les arguments doivent être un objet JSON.")
    value = args.get(key)
    if value is None:
        raise ToolError(f"Argument obligatoire manquant : '{key}'.")
    if not isinstance(value, str):
        raise ToolError(f"L'argument '{key}' doit être une chaîne de caractères.")
    return value


def _summarize_args(args: object) -> str:
    """Résumé court des arguments pour le journal (jamais le contenu d'un fichier)."""
    if not isinstance(args, dict) or not args:
        return ""
    parts = []
    for key, value in args.items():
        if key == "content":
            size = len(value) if isinstance(value, str) else "?"
            parts.append(f"content=<{size} caractères>")
        else:
            parts.append(str(value)[:80])
    return " ".join(parts)


def _with_logging(candidate_name: str, tool_name: str, handler: Handler) -> Handler:
    """Enveloppe un handler pour journaliser chaque appel et chaque refus."""

    def wrapped(args: dict) -> str:
        logger.info("[%s] %s %s", candidate_name, tool_name, _summarize_args(args))
        try:
            return handler(args)
        except ToolError as exc:
            logger.warning("[%s] %s refusé : %s", candidate_name, tool_name, exc)
            raise
        except OSError as exc:
            # Une erreur du système de fichiers est renvoyée au modèle au lieu d'arrêter tout le lot.
            logger.warning("[%s] %s en échec : %s", candidate_name, tool_name, exc)
            raise ToolError(f"Erreur d'accès aux fichiers : {exc}") from exc

    return wrapped


def _list_files(candidate_dir: Path) -> list[str]:
    """Chemins relatifs POSIX de tous les fichiers visibles du dossier, triés."""
    files = []
    for path in candidate_dir.rglob("*"):
        relative = path.relative_to(candidate_dir)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_file():
            files.append(relative.as_posix())
    return sorted(files)


def _resolve_candidate_file(candidate_dir: Path, raw_path: str) -> Path:
    """Résout un chemin relatif et vérifie qu'il désigne un .txt lisible du dossier candidat."""
    if not raw_path.strip():
        raise ToolError("Le chemin est vide.")
    relative = Path(raw_path)
    if relative.is_absolute() or relative.anchor:
        raise ToolError("Chemin absolu refusé : donne un chemin relatif tel que renvoyé par list_folder.")
    root = candidate_dir.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ToolError("Accès refusé : le fichier est en dehors du dossier du candidat.")
    if target.suffix.lower() != ".txt":
        raise ToolError("Seuls les fichiers .txt peuvent être lus.")
    if not target.is_file():
        raise ToolError(f"Fichier introuvable : {raw_path}. Utilise list_folder pour voir les fichiers.")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise ToolError(f"Fichier trop volumineux (limite : {MAX_FILE_SIZE // 1024} Ko).")
    return target


def _make_read_grid(grid_path: Path) -> Handler:
    def read_grid(args: dict) -> str:
        try:
            return grid_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Impossible de lire la grille : {exc}") from exc

    return read_grid


def _make_list_folder(candidate_dir: Path) -> Handler:
    def list_folder(args: dict) -> str:
        if not candidate_dir.is_dir():
            raise ToolError("Le dossier du candidat est introuvable.")
        files = _list_files(candidate_dir)
        if not files:
            return "Le dossier du candidat est vide : aucun fichier fourni."
        return "\n".join(files)

    return list_folder


def _make_read_file(candidate_dir: Path) -> Handler:
    def read_file(args: dict) -> str:
        target = _resolve_candidate_file(candidate_dir, _get_str_arg(args, "path"))
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"Impossible de lire le fichier : {exc}") from exc

    return read_file


def _make_write_file(output_dir: Path) -> Handler:
    def write_file(args: dict) -> str:
        filename = _get_str_arg(args, "filename")
        content = _get_str_arg(args, "content")
        if not OUTPUT_NAME_PATTERN.match(filename):
            raise ToolError(
                "Nom de fichier invalide : uniquement minuscules, chiffres, '_' ou '-', suivi de .txt "
                "(exemple : relance.txt)."
            )
        if not content.strip():
            raise ToolError("Le contenu est vide : rien n'a été écrit.")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / filename).write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Impossible d'écrire le fichier : {exc}") from exc
        return f"Fichier '{filename}' écrit ({len(content)} caractères)."

    return write_file


def build_tools(candidate_dir: Path, grid_path: Path, output_dir: Path) -> list[ToolSpec]:
    """Construit les quatre outils de l'agent, liés au dossier `candidate_dir`."""
    name = candidate_dir.name
    specs = [
        (
            "read_grid",
            (
                "Lit la grille des pièces obligatoires (JSON brut) : pièces du candidat, du garant, "
                "règles de fraîcheur. À appeler en PREMIER, avant d'examiner le dossier."
            ),
            NO_ARGS_SCHEMA,
            _make_read_grid(grid_path),
        ),
        (
            "list_folder",
            (
                "Liste tous les fichiers du dossier du candidat, y compris les sous-dossiers (ex. garant/), "
                "un chemin relatif par ligne."
            ),
            NO_ARGS_SCHEMA,
            _make_list_folder(candidate_dir),
        ),
        (
            "read_file",
            (
                "Lit le contenu d'un fichier .txt du dossier du candidat. Le chemin doit être relatif, "
                "exactement tel que renvoyé par list_folder (ex. 'identite.txt' ou 'garant/identite.txt')."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Chemin relatif renvoyé par list_folder."},
                },
                "required": ["path"],
            },
            _make_read_file(candidate_dir),
        ),
        (
            "write_file",
            (
                "Écrit un fichier texte de sortie (ex. rapport ou courrier de relance). Le nom doit respecter "
                "le format minuscules/chiffres/_/- suivi de .txt (ex. 'relance.txt'). Écrase le fichier s'il existe."
            ),
            {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Nom du fichier, ex. 'relance.txt'."},
                    "content": {"type": "string", "description": "Contenu texte complet du fichier."},
                },
                "required": ["filename", "content"],
            },
            _make_write_file(output_dir),
        ),
    ]
    return [
        ToolSpec(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=_with_logging(name, tool_name, handler),
        )
        for tool_name, description, parameters, handler in specs
    ]
