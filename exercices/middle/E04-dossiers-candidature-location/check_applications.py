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
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent_tools import (
    OUTDATED_VERDICT,
    TO_CHECK_VERDICT,
    GridPiece,
    ReadLog,
    build_tools,
    list_candidate_files,
    load_freshness_rules,
    load_grid,
    load_grid_pieces,
    load_guarantor_threshold,
    matches_pattern,
    matching_files,
    name_key,
    relance_name,
    relance_problems,
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
# Statuts que seul le code peut fixer : venant du modèle, ils sont ramenés à « a_verifier » avec ce point.
# Tout dossier de candidats/ est une candidature ; « erreur » n'est fiable que constatée par le code.
AGENT_STATUS_NOTES = {
    "hors_perimetre": (
        "statut « hors périmètre » proposé par l'agent, ramené à « à vérifier » : "
        "tout dossier de candidats/ est une candidature"
    ),
    "erreur": "statut « erreur » proposé par l'agent, ramené à « à vérifier » : échecs d'outils à contrôler",
}
# Nom du candidat repris dans l'objet de la transmission : une seule ligne, longueur bornée.
MAX_CANDIDATE_NAME_CHARS = 80
STATUS_LABELS = {"a_verifier": "à vérifier", "hors_perimetre": "hors périmètre", "non_traite": "non traité"}
BATCH_STOP_NOTE = "non traité : lot arrêté (quota épuisé ou configuration refusée), relancer avec --only"
LIST_FIELDS = ("pieces_manquantes", "incoherences", "points_a_verifier", "sources")
# Pièce de la grille dont le dernier justificatif fixe le revenu comparé au seuil du garant.
INCOME_PIECE_ID = "revenus"
GUARANTOR_UNCHECKED_NOTE = "garant : seuil de revenus non vérifié par le code"
# Pièces d'identité de la grille (candidat, garant) : nom de référence et date d'expiration contrôlés par le code.
IDENTITY_PIECE_IDS = {"identite", "garant_identite"}

# (dossier du candidat, grille, dossier de sortie, état des lectures) -> outils de l'agent.
ToolsFactory = Callable[[Path, Path, Path, ReadLog], list[ToolSpec]]

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
        files = sorted(name for name in sources if any(matches_pattern(name, motif) for motif in motifs))
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
    result = ApplicationResult(
        folder=folder,
        statut=statut,
        candidat=str(data.get("candidat", "")),
        pieces_manquantes=data.get("pieces_manquantes", []),
        incoherences=[str(item) for item in data.get("incoherences", [])],
        relance_fichier=str(data.get("relance_fichier", "")),
        points_a_verifier=[str(item) for item in data.get("points_a_verifier", [])],
        sources=[str(item) for item in data.get("sources", [])],
    )
    if statut in AGENT_STATUS_NOTES:
        result.statut = "a_verifier"
        result.points_a_verifier.append(AGENT_STATUS_NOTES[statut])
    check_candidate_name(result)
    return result


def check_candidate_name(result: ApplicationResult) -> None:
    """Le nom du candidat (texte du modèle) va dans la transmission : une ligne imprimable, longueur bornée.

    Sinon il est vidé et signalé, ce qui empêche aussi la transmission (point à vérifier).
    """
    name = result.candidat.strip()
    if name.isprintable() and len(name) <= MAX_CANDIDATE_NAME_CHARS:
        result.candidat = name
        return
    result.candidat = ""
    result.points_a_verifier.append(
        f"nom du candidat renvoyé par l'agent refusé (plusieurs lignes, caractères de contrôle "
        f"ou plus de {MAX_CANDIDATE_NAME_CHARS} caractères) : à reprendre sur la pièce d'identité"
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
    if written:
        text = (output_dir / expected).read_text(encoding="utf-8", errors="replace")
        problems = relance_problems(text)
        if problems:
            # Relance qui n'aurait pas dû être écrite (URL, adresse e-mail, long numéro…) : retirée.
            (output_dir / expected).unlink()
            written = False
            result.points_a_verifier.append(f"relance refusée et supprimée ({' ; '.join(problems)}) : à réécrire")
        else:
            words = len(text.split())
            if words > MAX_RELANCE_WORDS:
                result.points_a_verifier.append(f"relance trop longue : {words} mots (limite {MAX_RELANCE_WORDS})")
    # On n'affiche que la relance réellement présente, pas le nom annoncé par l'agent.
    result.relance_fichier = expected if written else ""


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
    # Rempli par read_file : seule preuve, côté code, des pièces réellement lues et de leur fraîcheur.
    read_log = ReadLog()
    try:
        answer = provider.run_agent(
            system_prompt, f"Dossier : {folder}", tools_factory(candidate_dir, grid_path, output_dir, read_log)
        )
        result = parse_agent_output(folder, answer)
        check_sources(result, candidate_dir)
    except LLMBatchError:
        raise
    except (LLMError, AgentOutputError) as error:
        logger.error("%s : %s", folder, error)
        result = ApplicationResult(folder=folder, statut="erreur", points_a_verifier=[str(error)])
    flag_suspicious_reads(result, read_log)
    drop_pieces_found_by_code(result, candidate_dir, grid_path, output_dir, read_log)
    check_relance(result, output_dir)
    # « complet » n'est gardé que si le code le confirme (pièces lues, à jour)…
    confirm_complete_status(result, candidate_dir, grid_path, read_log)
    # … et, après check_relance qui peut ajouter un point, sans aucun point à vérifier.
    enforce_complete_status(result)
    return result


def flag_suspicious_reads(result: ApplicationResult, read_log: ReadLog) -> None:
    """Signale les pièces lues qui imitent une ligne du code : le gestionnaire doit les examiner."""
    result.points_a_verifier += [
        f"{name} : pièce suspecte, {reason}" for name, reason in sorted(read_log.suspicious.items())
    ]


def read_files(piece: GridPiece, files: list[str], read_log: ReadLog) -> list[str]:
    """Fichiers de la pièce lus sans erreur par read_file (casse ignorée)."""
    read = {name.casefold() for name in read_log.read}
    return [name for name in matching_files(piece, files) if name.casefold() in read]


def distinct_read_files(piece: GridPiece, files: list[str], read_log: ReadLog) -> list[str]:
    """Fichiers de la pièce lus sans erreur, un seul par contenu (une copie sous un autre nom ne compte pas)."""
    return read_log.distinct(read_files(piece, files, read_log))[0]


def _logged(mapping: dict, name: str, default: object = None) -> object:
    """Valeur notée par read_file pour ce fichier, casse ignorée."""
    return {key.casefold(): value for key, value in mapping.items()}.get(name.casefold(), default)


def identity_reasons(
    pieces: list[GridPiece], files: list[str], read_log: ReadLog, reference: date | None, guarantor: bool
) -> list[str]:
    """Contrôles en code de la pièce d'identité d'une personne (candidat ou garant) ; [] si tout est confirmé.

    Le nom de la pièce d'identité doit être lisible et unique, et chaque autre pièce de la même personne qui porte
    un nom lisible doit porter le même (mots comparés sans casse ni ordre). La pièce ne doit pas être expirée à la
    date de référence ; une date d'expiration absente n'est pas contrôlée, une date invalide ou multiple bloque.
    """
    who = "garant" if guarantor else "candidat"
    own = [piece for piece in pieces if piece.guarantor == guarantor]
    identity = next((piece for piece in own if piece.piece_id in IDENTITY_PIECE_IDS), None)
    identity_files = read_files(identity, files, read_log) if identity else []
    if not identity_files:
        return []  # pièce absente ou non lue : déjà signalé par unconfirmed_reasons
    reasons = []
    names = {name for path in identity_files for name in _logged(read_log.names, path, ())}
    if len({name_key(name) for name in names}) != 1:
        listed = ", ".join(sorted(names)) or "aucun"
        reasons.append(f"{who} : nom de la pièce d'identité illisible ou multiple pour le code ({listed})")
    else:
        reference_name = next(iter(names))
        for piece in own:
            if piece is identity:
                continue
            for path in read_files(piece, files, read_log):
                logged = _logged(read_log.names, path, ())
                other = [name for name in logged if name_key(name) != name_key(reference_name)]
                if other:
                    reasons.append(
                        f"{path} : nom « {', '.join(other)} » différent de la pièce d'identité « {reference_name} »"
                    )
    for path in identity_files:
        expiries = _logged(read_log.expiries, path, ())
        if expiries is None:
            reasons.append(f"{path} : date d'expiration invalide")
        elif len(expiries) > 1:
            listed = ", ".join(f"{day:%d/%m/%Y}" for day in expiries)
            reasons.append(f"{path} : plusieurs dates d'expiration ({listed})")
        elif expiries and reference is None:
            reasons.append(f"{path} : expiration non vérifiable (date de référence absente)")
        elif expiries and expiries[0] < reference:
            reasons.append(f"{path} : pièce d'identité expirée le {expiries[0]:%d/%m/%Y}")
    return reasons


def format_amount(amount: Decimal) -> str:
    """Montant au format des pièces : « 2 150,00 »."""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def latest_net_income(pieces: list[GridPiece], files: list[str], read_log: ReadLog) -> Decimal | None:
    """Revenu net du dernier justificatif de revenus lu (date d'émission la plus récente), ou None.

    None dès que le code ne peut pas le dire de façon fiable : pièce absente de la grille, aucun justificatif lu,
    date d'émission illisible sur l'un d'eux, montant introuvable ou différent sur les derniers.
    """
    piece = next((piece for piece in pieces if piece.piece_id == INCOME_PIECE_ID), None)
    if piece is None:
        return None
    incomes = {name.casefold(): income for name, income in read_log.incomes.items()}
    entries = [incomes.get(name.casefold(), (None, None)) for name in read_files(piece, files, read_log)]
    if not entries or any(issued is None for issued, _ in entries):
        return None
    latest = max(issued for issued, _ in entries)
    amounts = {amount for issued, amount in entries if issued == latest}
    return amounts.pop() if len(amounts) == 1 and None not in amounts else None


def guarantor_shortfall(
    pieces: list[GridPiece], files: list[str], grid_path: Path, read_log: ReadLog
) -> tuple[Decimal, Decimal] | None:
    """(revenu, seuil) si le garant est exigé selon la grille ; None s'il ne l'est pas ou si le code ne sait pas."""
    threshold = load_guarantor_threshold(grid_path)
    income = latest_net_income(pieces, files, read_log)
    if threshold is None or income is None or income >= threshold:
        return None
    return income, threshold


def guarantor_unchecked(candidate_dir: Path, grid_path: Path, read_log: ReadLog) -> bool:
    """Vrai si la grille fixe un seuil de garant, sans pièce de garant au dossier, et que le code ne peut pas
    lire le revenu à comparer (format de montant non reconnu, date illisible…)."""
    pieces = load_grid_pieces(grid_path)
    files = list_candidate_files(candidate_dir)
    if any(matching_files(piece, files) for piece in pieces if piece.guarantor):
        return False
    return load_guarantor_threshold(grid_path) is not None and latest_net_income(pieces, files, read_log) is None


def unconfirmed_reasons(
    result: ApplicationResult, candidate_dir: Path, grid_path: Path, read_log: ReadLog
) -> list[str]:
    """Ce que le code ne peut pas confirmer pour un dossier « complet » ; [] si tout est confirmé.

    Une pièce est confirmée si elle a au moins « nombre_min » fichiers lus sans erreur et recevables (ou sans
    contrôle de fraîcheur) : un fichier périmé en surplus ne bloque pas, une date future ou illisible bloque.
    Les pièces du garant sont exigées si le dossier en contient au moins une ; sans aucune, le garant est
    réclamé si le dernier revenu net lu par le code est sous le seuil de la grille.
    """
    reasons = []
    if result.pieces_manquantes:
        reasons.append(f"pièces manquantes déclarées ({format_missing(result.pieces_manquantes)})")
    if result.incoherences:
        reasons.append("incohérences relevées")
    pieces = load_grid_pieces(grid_path)
    if not pieces:
        reasons.append("grille illisible : pièces exigées inconnues")
    files = list_candidate_files(candidate_dir)
    has_guarantor = any(matching_files(piece, files) for piece in pieces if piece.guarantor)
    failed = {name.casefold(): reason for name, reason in read_log.failed.items()}
    outdated = {name.casefold() for name in read_log.reads_with_verdict(OUTDATED_VERDICT)}
    for piece in pieces:
        if piece.guarantor and not has_guarantor:
            continue
        found = matching_files(piece, files)
        # Un même contenu copié sous plusieurs noms ne compte qu'une fois.
        read, duplicates = read_log.distinct(read_files(piece, files, read_log))
        accepted = [name for name in read if read_log.is_accepted(name)]
        duplicate_note = f" ; doublon(s) de contenu non compté(s) : {', '.join(duplicates)}" if duplicates else ""
        if len(found) < piece.minimum:
            reasons.append(f"{piece.label} : {len(found)} fichier(s) dans le dossier pour {piece.minimum} exigé(s)")
        elif len(read) < piece.minimum:
            reasons.append(
                f"{piece.label} : {len(read)} fichier(s) lu(s) sans erreur pour {piece.minimum} "
                f"exigé(s){duplicate_note}"
            )
        elif len(accepted) < piece.minimum:
            reasons.append(
                f"{piece.label} : {len(accepted)} fichier(s) recevable(s) pour {piece.minimum} exigé(s){duplicate_note}"
            )
            reasons += [
                f"{name} : fraîcheur {OUTDATED_VERDICT}" for name in read if name.casefold() in outdated
            ]
        reasons += [f"{name} : lecture en échec" for name in found if name.casefold() in failed]
    reasons += [f"{name} : fraîcheur {TO_CHECK_VERDICT}" for name in read_log.reads_with_verdict(TO_CHECK_VERDICT)]
    reference, _ = load_freshness_rules(grid_path)
    reasons += identity_reasons(pieces, files, read_log, reference, guarantor=False)
    if has_guarantor:
        reasons += identity_reasons(pieces, files, read_log, reference, guarantor=True)
    shortfall = None if has_guarantor else guarantor_shortfall(pieces, files, grid_path, read_log)
    if shortfall:
        income, threshold = shortfall
        reasons.append(
            f"garant exigé (dernier revenu net {format_amount(income)} EUR, sous le seuil de "
            f"{format_amount(threshold)} EUR) mais aucune pièce de garant dans le dossier"
        )
    return reasons


def confirm_complete_status(
    result: ApplicationResult, candidate_dir: Path, grid_path: Path, read_log: ReadLog
) -> None:
    """« complet » n'est gardé que si le code le confirme ; sinon le dossier passe à vérifier, avec la raison.

    Sans pièce de garant et sans revenu lisible par le code, le seuil du garant reste un point à vérifier.
    """
    if result.statut != "complet":
        return
    reasons = unconfirmed_reasons(result, candidate_dir, grid_path, read_log)
    if reasons:
        result.statut = "a_verifier"
        result.points_a_verifier.append(
            "statut « complet » ramené à « à vérifier » : le code n'a pas pu le confirmer (" + "; ".join(reasons) + ")"
        )
    # Appelée aussi par le filet de sécurité : le point n'est ajouté qu'une fois.
    elif GUARANTOR_UNCHECKED_NOTE not in result.points_a_verifier and guarantor_unchecked(
        candidate_dir, grid_path, read_log
    ):
        result.points_a_verifier.append(GUARANTOR_UNCHECKED_NOTE)


def drop_pieces_found_by_code(
    result: ApplicationResult, candidate_dir: Path, grid_path: Path, output_dir: Path, read_log: ReadLog
) -> None:
    """Filet de sécurité : retire une pièce déclarée manquante alors que le dossier a assez de fichiers lus pour elle.

    Seuls les fichiers lus sans erreur par read_file comptent. Une pièce n'est retirée que si son motif dit
    « manquante » ou parle d'un nom différent (une incohérence, pas une pièce manquante) ; tout autre motif
    la garde. S'il ne reste aucune pièce manquante, le statut est recalculé selon les règles de la grille,
    « complet » devant encore être confirmé par le code, et la relance, écrite à cause de l'erreur corrigée,
    est supprimée.
    """
    if result.statut != "incomplet":
        return
    files = list_candidate_files(candidate_dir)
    present = {
        piece.label.casefold()
        for piece in load_grid_pieces(grid_path)
        if len(distinct_read_files(piece, files, read_log)) >= piece.minimum
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
        # Le filet n'aboutit jamais seul à « complet » : chaque pièce exigée doit avoir été lue et être à jour.
        confirm_complete_status(result, candidate_dir, grid_path, read_log)
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
    # Grille validée avant tout appel au modèle : une grille cassée arrête le lot avec un message clair.
    grid = load_grid(grid_path)
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
