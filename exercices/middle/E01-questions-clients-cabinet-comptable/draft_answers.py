"""Brouillons de réponse aux questions clients du cabinet Derval (E01, niveau 1).

Lit un lot de questions au format CSV, envoie chaque question au modèle avec le prompt
système et la FAQ, puis écrit un brouillon Markdown par question et un récapitulatif.

Usage : python draft_answers.py questions-clients.csv [--output drafts] [--limit 3]
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from llm_providers import LLMError, LLMProvider, get_provider

# Réglages du modèle propres à cet exercice (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et température par défaut.
LLM_PROVIDER = "gemini"
LLM_MODEL = "gemini-3.5-flash-lite"
# Température basse : étiquetage plus régulier d'un lot à l'autre. Ignorée par Claude.
LLM_TEMPERATURE = 0.2

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parents[1] / ".env"
SYSTEM_PROMPT_PATH = BASE_DIR / "prompt-systeme.md"
FAQ_PATH = BASE_DIR / "faq-cabinet-derval.md"
REQUIRED_COLUMNS = ("identifiant", "nom", "numero_dossier", "question")
# Identifiant utilisé comme nom de fichier : on refuse tout ce qui pourrait sortir du dossier.
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
LABEL_PATTERN = re.compile(r"\*\*Étiquette :\*\*\s*(.+)")
SECTION_PATTERN = re.compile(r"\*\*Section citée :\*\*\s*(.+)")
UNKNOWN = "non détectée"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DraftSummary:
    """Résultat d'une question, repris dans le récapitulatif."""

    question_id: str
    label: str
    section: str


def build_system_prompt() -> str:
    """Assemble le prompt système et la FAQ, qui sert de seule source."""
    prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    faq = FAQ_PATH.read_text(encoding="utf-8")
    return f"{prompt}\n\n# Document de référence : faq-cabinet-derval.md\n\n{faq}"


def load_questions(csv_path: Path) -> pd.DataFrame:
    """Charge le CSV et vérifie ses colonnes et ses identifiants."""
    questions = pd.read_csv(csv_path, dtype=str, encoding="utf-8", keep_default_na=False)
    missing = [column for column in REQUIRED_COLUMNS if column not in questions.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans {csv_path.name} : {', '.join(missing)}")

    invalid_ids = [value for value in questions["identifiant"] if not SAFE_ID_PATTERN.match(value)]
    if invalid_ids:
        raise ValueError(f"Identifiants invalides dans {csv_path.name} : {', '.join(map(repr, invalid_ids))}")
    duplicates = questions["identifiant"][questions["identifiant"].duplicated()].tolist()
    if duplicates:
        raise ValueError(f"Identifiants en double dans {csv_path.name} : {', '.join(duplicates)}")
    return questions


def format_question(record: dict[str, str]) -> str:
    """Met une ligne du CSV sous la forme attendue par le prompt système."""
    return f"{record['identifiant']} · {record['nom']} · {record['numero_dossier']}\n{record['question']}"


def summarize_draft(question_id: str, draft: str) -> DraftSummary:
    """Extrait l'étiquette et la section citée du brouillon produit par le modèle."""
    label = LABEL_PATTERN.search(draft)
    section = SECTION_PATTERN.search(draft)
    return DraftSummary(
        question_id=question_id,
        label=label.group(1).strip() if label else UNKNOWN,
        section=section.group(1).strip() if section else UNKNOWN,
    )


def table_cell(text: str) -> str:
    """Neutralise les caractères qui casseraient une ligne de tableau Markdown."""
    return " ".join(text.split()).replace("|", "\\|")


def format_recap(summaries: list[DraftSummary], model: str) -> str:
    """Construit le tableau récapitulatif des étiquettes, au format Markdown."""
    lines = [
        "# Récapitulatif des brouillons",
        "",
        f"Modèle : `{model}`",
        "",
        "| Identifiant | Étiquette | Section |",
        "|---|---|---|",
        *(f"| {item.question_id} | {table_cell(item.label)} | {table_cell(item.section)} |" for item in summaries),
        "",
    ]
    return "\n".join(lines)


def draft_answers(
    csv_path: Path, output_dir: Path, provider: LLMProvider, limit: int | None = None
) -> list[DraftSummary]:
    """Produit un brouillon par question et renvoie le résumé de chacun."""
    questions = load_questions(csv_path)
    if limit is not None:
        questions = questions.head(limit)
    system_prompt = build_system_prompt()
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    total = len(questions)
    for position, record in enumerate(questions.to_dict("records"), start=1):
        question_id = record["identifiant"]
        draft_path = output_dir / f"{question_id}.md"
        logger.info("Question %d/%d : %s", position, total, question_id)
        try:
            draft = provider.generate(system_prompt, format_question(record))
        except LLMError as error:
            # Une question en échec ne bloque pas le lot : elle apparaît en erreur dans le récapitulatif.
            # On retire le brouillon d'une exécution précédente pour ne pas le faire passer pour actuel.
            logger.error("%s : %s", question_id, error)
            draft_path.unlink(missing_ok=True)
            summaries.append(DraftSummary(question_id, "erreur", str(error)))
            continue
        draft_path.write_text(draft + "\n", encoding="utf-8")
        summaries.append(summarize_draft(question_id, draft))
        logger.info("\n%s\n", draft)

    recap = format_recap(summaries, provider.model)
    recap_path = output_dir / "recap.md"
    recap_path.write_text(recap, encoding="utf-8")
    logger.info("\n%s", recap)
    logger.info("Brouillons et récapitulatif écrits dans %s", output_dir)
    return summaries


def positive_int(value: str) -> int:
    """Convertit l'argument en entier strictement positif."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("doit être un entier supérieur ou égal à 1")
    return number


def parse_arguments() -> argparse.Namespace:
    """Lit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Brouillons de réponse aux questions clients (E01).")
    parser.add_argument(
        "csv_path",
        type=Path,
        nargs="?",
        default=BASE_DIR / "questions-clients.csv",
        help="Fichier CSV des questions (par défaut : questions-clients.csv).",
    )
    parser.add_argument("--output", type=Path, default=BASE_DIR / "drafts", help="Dossier des brouillons.")
    parser.add_argument("--limit", type=positive_int, help="Ne traiter que les N premières questions (pour tester).")
    return parser.parse_args()


def main() -> None:
    """Point d'entrée du script."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Les SDK journalisent chaque requête HTTP : on ne garde que leurs avertissements et erreurs.
    for library_logger in ("httpx", "google_genai", "anthropic"):
        logging.getLogger(library_logger).setLevel(logging.WARNING)
    arguments = parse_arguments()
    load_dotenv(ENV_PATH)
    try:
        provider = get_provider(provider=LLM_PROVIDER, model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    except LLMError as error:
        raise SystemExit(str(error)) from error
    logger.info("Modèle utilisé : %s", provider.model)
    draft_answers(arguments.csv_path, arguments.output, provider, arguments.limit)


if __name__ == "__main__":
    main()
