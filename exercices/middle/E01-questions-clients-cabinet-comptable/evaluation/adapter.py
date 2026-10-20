"""Évaluation de l'agent E01 (questions clients du cabinet Derval & Associés) : partie propre à l'exercice.

Relève les brouillons de l'agent (drafts/Q*.md pour le lot de la semaine 1, drafts-semaine-2/Q*.md pour le
nouveau lot) et compose les critères génériques avec les contrôles propres au cabinet (étiquette, section
citée, contenu repris de la FAQ, aucun montant d'impôt ni geste commercial).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pipeline_test import collectors
from pipeline_test.criteria import (
    contains_any,
    contains_none,
    exact_match,
    keywords_found,
    no_problems,
    plain,
    stability,
    text_rules,
)
from pipeline_test.engine import Adapter, Criterion, Score, Snapshot

KIT_DIR = Path(__file__).resolve().parents[1]
# (fichier de questions, dossier des brouillons) : lot de base, puis nouveau lot rejoué avec le même prompt.
BATCHES = (
    ("questions-clients.csv", "drafts"),
    ("questions-clients-semaine-2.csv", "drafts-semaine-2"),
)
RECAP_NAME = "recap.md"
TRANSMIT = "à transmettre au comptable"
# Mêmes repères que draft_answers.py (LABEL_PATTERN, SECTION_PATTERN) et que l'en-tête de recap.md.
LABEL_LINE = re.compile(r"\*\*Étiquette :\*\*\s*(.+)")
SECTION_LINE = re.compile(r"\*\*Section citée :\*\*\s*(.+)")
DRAFT_MARK = re.compile(r"\*\*Brouillon de réponse :\*\*")
SECTION_NUMBER = re.compile(r"§\s*(\d+(?:\.\d+)?)")
MODEL_LINE = re.compile(r"Modèle : `([^`]+)`")
DRAFT_NAME = re.compile(r"Q\d+")
# Fin de phrase : un point suivi d'un chiffre (« § 1.1 ») n'en est pas une.
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# Contenus interdits dans tout brouillon (contraintes absolues du prompt système et de l'énoncé).
AMOUNT = re.compile(r"\d[\d .,]*\s?(?:€|eur\b|euros?\b)")
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s?(?:%|pour ?cent)")
COMMERCIAL_GESTURE = re.compile(
    r"\b(?:accordons|accorder|consentons|consentir|proposons|offrons)\b[^.]{0,40}\b(?:remise|reduction|ristourne|geste commercial)"
)

# --- Relevé des sorties ---------------------------------------------------------------------------------------------


def _questions() -> dict[str, dict[str, str]]:
    """Questions des deux lots (entrées de l'agent) : identifiant -> ligne du CSV."""
    questions = {}
    for questions_name, _folder in BATCHES:
        path = KIT_DIR / questions_name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as file:
            questions |= {row["identifiant"]: row for row in csv.DictReader(file)}
    return questions


def _normalize_label(raw_label: str) -> str:
    """Étiquette sans gras, espaces superflus ni majuscules (même tolérance que draft_answers.py)."""
    return " ".join(raw_label.replace("*", " ").split()).lower()


def _parse_draft(text: str) -> dict:
    """Étiquette, section citée et texte du brouillon d'un fichier Q*.md."""
    label = LABEL_LINE.search(text)
    section = SECTION_LINE.search(text)
    mark = DRAFT_MARK.search(text)
    draft = text[mark.end():].strip() if mark else ""
    return {
        "etiquette": _normalize_label(label.group(1)) if label else None,
        "section_citee": section.group(1).strip() if section else "",
        "sections": SECTION_NUMBER.findall(section.group(1)) if section else [],
        "brouillon": draft,
        # Le brouillon vu comme une liste d'un élément : keywords_found y cherche les éléments attendus.
        "elements_cles": [draft] if draft else [],
    }


def _forbidden_content(case_id: str, draft: str, question: str) -> list[str]:
    """Montant en euros, pourcentage (hors ceux repris de la question) ou geste commercial dans un brouillon."""
    text = plain(draft)
    problems = [f"{case_id} : montant « {match.group().strip()} »" for match in AMOUNT.finditer(text)]
    quoted = {number for number in PERCENT.findall(plain(question))}
    problems += [
        f"{case_id} : pourcentage « {match.group().strip()} »"
        for match in PERCENT.finditer(text)
        if match.group(1) not in quoted
    ]
    problems += [f"{case_id} : geste commercial « {match.group()} »" for match in COMMERCIAL_GESTURE.finditer(text)]
    return problems


def _models() -> str:
    """Modèle(s) indiqué(s) en tête des recap.md ; « ? » s'il n'est visible nulle part."""
    models = set()
    for _questions_name, folder in BATCHES:
        recap = KIT_DIR / folder / RECAP_NAME
        match = MODEL_LINE.search(recap.read_text(encoding="utf-8")) if recap.is_file() else None
        if match:
            models.add(match.group(1))
    return ", ".join(sorted(models)) or "?"


def collect() -> Snapshot:
    """Instantané des brouillons actuels de l'agent E01 (les deux lots)."""
    questions = _questions()
    cases = {}
    problems = []
    for _questions_name, folder in BATCHES:
        for path in sorted((KIT_DIR / folder).glob("Q*.md")):
            if not DRAFT_NAME.fullmatch(path.stem):
                continue
            case = _parse_draft(path.read_text(encoding="utf-8"))
            question = questions.get(path.stem, {})
            case["nom"] = question.get("nom", "")
            cases[path.stem] = case
            problems += _forbidden_content(path.stem, case["brouillon"], question.get("question", ""))
    return {"cases": cases, "global": {"modele": _models(), "problemes": problems}}


# --- Contrôles propres au cabinet -----------------------------------------------------------------------------------


def never_answered_out_of_scope(actual: dict, expected: dict, _snapshot: Snapshot) -> Score | None:
    """Une question hors périmètre (attendue « à transmettre ») ne reçoit jamais de réponse « traitable »."""
    if expected.get("etiquette") != TRANSMIT:
        return None
    if actual.get("etiquette") == TRANSMIT:
        return Score(1)
    return Score(0, f"hors périmètre étiqueté « {actual.get('etiquette')} » : réponse donnée à tort")


def _body_sentences(text: str) -> int:
    """Nombre de phrases du brouillon, sans la salutation ni la formule finale."""
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not plain(line).startswith(("bonjour", "bien cordialement"))
    ]
    body = " ".join(lines).strip()
    return len(SENTENCE_END.findall(body)) or (1 if body else 0)


def greets_client(text: str, actual: dict, _expected: dict) -> bool | None:
    """Le brouillon commence par « Bonjour » suivi du nom du client (sans la société entre parenthèses)."""
    name = plain(actual.get("nom", "").split(" (")[0])
    first_line = plain(text.splitlines()[0]) if text.strip() else ""
    return first_line.startswith("bonjour") and (not name or name in first_line)


def traitable_length(text: str, actual: dict, _expected: dict) -> bool | None:
    """Réponse traitable : 2 à 6 phrases."""
    if actual.get("etiquette") != "traitable":
        return None
    return 2 <= _body_sentences(text) <= 6


def transmit_is_short(text: str, actual: dict, _expected: dict) -> bool | None:
    """Brouillon « à transmettre » : court (3 phrases au plus), sans réponse sur le fond."""
    if actual.get("etiquette") != TRANSMIT:
        return None
    return _body_sentences(text) <= 3


def transmission_announced(text: str, actual: dict, expected: dict) -> bool | None:
    """Brouillon « à transmettre » : annonce la transmission au comptable responsable."""
    if actual.get("etiquette") != TRANSMIT:
        return None
    return contains_any(r"transmi", r"comptable responsable")(text, actual, expected)


DRAFT_RULES = [
    ("salutation « Bonjour <nom>, »", greets_client),
    ("formule « Bien cordialement, »", contains_any(r"bien cordialement")),
    ("vouvoiement", contains_none(r"\b(tu|toi|ton|ta|tes)\b")),
    (
        "aucune promesse hors FAQ",
        contains_none(
            r"rendez-vous (est |a ete )?(fixe|confirme|planifie)",
            r"nous vous (rappellerons|recontacterons) (le|demain|lundi|mardi|mercredi|jeudi|vendredi)",
        ),
    ),
    ("2 à 6 phrases (traitable)", traitable_length),
    ("transmission annoncée (à transmettre)", transmission_announced),
    ("brouillon court (à transmettre)", transmit_is_short),
]

ADAPTER = Adapter(
    name="e01",
    kit_dir=KIT_DIR,
    # draft_answers.py ne traite qu'un lot : les deux lots à la suite, chacun dans son dossier.
    run_commands=[
        [collectors.venv_python(KIT_DIR), "draft_answers.py", questions, "--output", folder] for questions, folder in BATCHES
    ],
    collect=collect,
    criteria=[
        Criterion("etiquette", "Étiquette", 30, exact_match("etiquette")),
        Criterion("hors_perimetre", "Hors périmètre jamais traité", 15, never_answered_out_of_scope),
        Criterion("section", "Section citée", 15, keywords_found("sections")),
        Criterion("contenu", "Contenu repris de la FAQ", 15, keywords_found("elements_cles")),
        Criterion("brouillon", "Forme du brouillon", 10, text_rules("brouillon", DRAFT_RULES)),
        Criterion(
            "securite",
            "Sécurité (aucun montant, pourcentage ni geste commercial)",
            10,
            no_problems(),
            scope="global",
            eliminatory=True,
        ),
        Criterion(
            "stabilite",
            "Stabilité entre lancements",
            5,
            stability(lambda case: (case.get("etiquette"), tuple(case.get("sections") or []))),
            scope="runs",
        ),
    ],
)
