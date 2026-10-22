"""Contrôles en code des résultats de l'agent : devis, dates alternatives, planning inchangé.

Chaque contrôle relit le planning ou la grille du kit (lecture seule) et renvoie des points à vérifier
pour la synthèse ; aucun ne modifie quoi que ce soit.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date
from typing import Any

import planning
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import (
    database_path,
    halls_with_dates,
    quote_arguments,
    rooms_by_type,
    same_hall,
)

ALTERNATIVE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:→|->|au|à)\s*(\d{4}-\d{2}-\d{2})")

# Homoglyphes courants (cyrilliques, grecs), apostrophes et tirets typographiques ramenés à l'ASCII,
# caractères invisibles retirés : « rеmise » écrit avec un « е » cyrillique reste une remise.
CONFUSABLES = str.maketrans(
    {
        **dict(zip("аеорсухіјѕԁһԛԝкмАВЕКМНОРСТХУІЈЅ", "aeopcyxijsdhqwkmABEKMHOPCTXYIJS", strict=True)),
        **dict(zip("αοεινρτυχκΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "aoeivrtuxkABEZHIKMNOPTYX", strict=True)),
        **dict.fromkeys("’‘ʼ`´", "'"),
        **dict.fromkeys("‐‑‒–—―−", "-"),
        **dict.fromkeys("\u00ad\u200b\u200c\u200d\u2060\ufeff"),
    }
)
# Nombre en chiffres : « 6 680 », « 6.680 », « 6,680 », « 6'680 », « 6680 », décimales éventuelles.
NUMBER = r"(\d{1,3}(?:[ .,']\d{3})+(?!\d)|\d+)(?:[.,](\d{1,2})(?!\d))?"
CURRENCY = r"(?:€|\$|eur(?:os?)?\b|usd\b|chf\b|dollars?\b|francs?\b)"
# Montant dans le texte normalisé (sans accents ni casse) : devise ou taxe après le nombre
# (« 6 680,00 eur », « 7 k€ », « 6 680 htva »), tiret comptable (« 6 680,- ») ou devise avant (« € 50 »).
AMOUNT_AFTER = re.compile(
    rf"(?<![\d.,']){NUMBER}"
    rf"(?:\s*(?P<k>k)\s*(?:€|eur(?:os?)?\b)|\s*{CURRENCY}|\s*(?:htva|ht|tvac|ttc)\b|\s*hors\s+tva\b|[.,]-)"
)
AMOUNT_BEFORE = re.compile(rf"(?:€|\$|\beur\b|\busd\b|\bchf\b)\s*{NUMBER}")
# Nombres en lettres (« cinquante », « six mille six cent quatre-vingts ») : valeur de chaque mot.
NUMBER_WORDS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
    "cent": 100, "cents": 100, "mille": 1000, "million": 1_000_000, "millions": 1_000_000,
}  # fmt: skip
NUMBER_WORD = rf"\b(?:{'|'.join(sorted(NUMBER_WORDS, key=len, reverse=True))})\b"
WORDS_SEQUENCE = rf"{NUMBER_WORD}(?:[\s-]+(?:{NUMBER_WORD}|et\b))*"
AMOUNT_IN_WORDS = re.compile(rf"({WORDS_SEQUENCE})\s*(?:d'\s*)?(?:€|eur(?:os?)?\b|dollars?\b|francs?\b)")

# Mentions cherchées dans le texte normalisé -> libellé affiché, dans l'ordre.
# Une mention déjà retenue par un motif précédent (« remise de 10 % ») n'est pas comptée deux fois.
SPELLED_PERCENT = r"(?:pour\s*cents?\b|p\.\s*c\.|pcts?\b)"
PERCENT = rf"\d+(?:[.,]\d+)?\s*(?:%|{SPELLED_PERCENT})"
DISCOUNT_WORD = r"(?:remises?|reductions?|rabais)"
# BLOQUANT : remise explicite sur le prix ; write_draft refuse le brouillon (sauf mention niée).
# « remise » seule n'est pas visée dans « remise des clés ».
DISCOUNT_PATTERNS = (
    (re.compile(rf"\b{DISCOUNT_WORD}\s+de\s+{PERCENT}"), "remise de X %"),
    (re.compile(rf"(?<![\d.,]){PERCENT}\s+de\s+{DISCOUNT_WORD}\b"), "X % de remise"),
    (re.compile(rf"(?<![\w%])-\s*{PERCENT}"), "-X %"),
    # « 10 pour cent », « 10 p.c. », « 10 pct », « dix pour cent » : formes qui contournent « % ».
    (re.compile(rf"(?:(?<![\d.,])\d+(?:[.,]\d+)?|{WORDS_SEQUENCE})\s*{SPELLED_PERCENT}"), "pour cent"),
    (re.compile(r"\bremises?\b(?!\s+(?:des|de la|de vos|de votre)\s+cle)"), "remise"),
    (re.compile(r"\breductions?\b"), "réduction"),
    (re.compile(r"\bgestes?\s+commercia(?:l|ux)\b"), "geste commercial"),
    (re.compile(r"\brabais\b"), "rabais"),
    (re.compile(r"\bristournes?\b"), "ristourne"),
    (re.compile(r"\btarifs?\s+preferentiels?\b"), "tarif préférentiel"),
    (re.compile(r"\bdiscounts?\b"), "discount"),
    (re.compile(r"\bgracieu(?:x|se|ses|sement)\b"), "à titre gracieux"),
    (re.compile(r"\bcadeaux?\b"), "cadeau"),
    (re.compile(r"\bprix\s+d'\s*amis?\b"), "prix d'ami"),
    (re.compile(r"\bnon[\s-]+factur\w*"), "non facturé"),
    (re.compile(r"\b(?:a|aux)\s+(?:notre\s+charge|nos\s+frais)\b"), "à notre charge"),
)
# SIGNALÉ seulement : formulations courantes d'hôtel (« acompte de 30 % », « parking gratuit »), à relire.
WARNING_PATTERNS = (
    (re.compile(r"\bofferte?s?\b"), "offert"),
    (re.compile(r"\bgratuit(?:e|s|es|ement)?\b"), "gratuit"),
    (re.compile(r"\bpromo(?:tion)?s?\b"), "promotion"),
    (re.compile(rf"(?<![\d.,]){PERCENT}"), "pourcentage"),
)
# Négation dans les NEGATION_WINDOW mots qui précèdent, dans la même phrase : « sans remise »,
# « aucune réduction », « pas de rabais », « ni remise », « nous ne faisons pas de remise ».
NEGATION_WORDS = frozenset({"sans", "aucun", "aucune", "pas", "ni"})
NEGATION_WINDOW = 5
SENTENCE_END = re.compile(r"[.!?;:\n]")
HORS_PERIMETRE_NOTE = (
    "statut « hors_perimetre » : confirmer à la lecture du courriel que la demande sort bien du périmètre "
    "(aucun devis n'a été préparé)"
)


def planning_fingerprint() -> str:
    """Empreinte du contenu du planning et des pré-réservations : prouve que rien n'a été réservé ni déplacé."""
    digest = hashlib.sha256()
    # Même base que le serveur MCP (KIT_BASE lue après load_dotenv), ouverte en lecture seule.
    uri = database_path().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
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


def parse_period(text: str) -> tuple[str, str] | None:
    """Lit une période « AAAA-MM-JJ → AAAA-MM-JJ » ; None si le texte n'en contient pas."""
    match = ALTERNATIVE_PATTERN.search(text)
    return (match.group(1), match.group(2)) if match else None


def shift_needs(needs: dict[str, Any], arrival: str, departure: str) -> dict[str, Any]:
    """Besoins décalés sur une autre période : mêmes chambres et repas, salles décalées d'autant de jours.

    Le décalage est l'écart entre l'arrivée proposée et l'arrivée demandée. Lève ValueError, TypeError
    ou ToolError si les dates ou les salles de la fiche sont illisibles.
    """
    offset = date.fromisoformat(arrival) - date.fromisoformat(needs.get("date_arrivee"))
    halls = [
        {"salle": hall, "dates": [(date.fromisoformat(day) + offset).isoformat() for day in days]}
        for hall, days in halls_with_dates(needs)
    ]
    return {**needs, "date_arrivee": arrival, "date_depart": departure, "salles": halls}


def busy_halls(needs: dict[str, Any]) -> list[str]:
    """Salles des besoins occupées dans le planning (« Cèdre le 2026-12-15 ») ; ValueError hors planning."""
    busy = []
    for hall, days in halls_with_dates(needs):
        for day in days:
            free = planning.disponibilites_salles(day, day)[0]["libres"]
            if not any(same_hall(name, hall) for name in free):
                busy.append(f"{hall} le {day}")
    return busy


def check_alternative(needs: dict[str, Any], alternative: str) -> str | None:
    """Revérifie une période alternative : assez de chambres libres et salles libres aux dates décalées."""
    period = parse_period(alternative)
    if period is None:
        return f"date alternative illisible : « {alternative} »"
    try:
        shifted = shift_needs(needs, *period)
        free = planning.disponibilites_chambres(*period)["libres_sur_toute_la_periode"]
        short = {room: count for room, count in rooms_by_type(shifted).items() if count > free.get(room, 0)}
        busy = busy_halls(shifted)
    except ToolError as error:
        return f"besoins de la fiche illisibles : {error}"
    except (ValueError, TypeError) as error:
        return f"date alternative « {alternative} » non vérifiable dans le planning ({error})"
    problems = []
    if short:
        problems.append(f"chambres libres insuffisantes : {short}")
    if busy:
        problems.append(f"salle occupée : {', '.join(busy)}")
    return f"date alternative « {alternative} » indisponible : {' ; '.join(problems)}" if problems else None


def check_alternatives(needs: dict[str, Any], alternatives: list[str]) -> list[str]:
    """Revérifie dans le planning chaque période alternative proposée (chambres et salles)."""
    return [problem for alternative in alternatives if (problem := check_alternative(needs, alternative))]


def check_alternative_quote(needs: dict[str, Any], quote: dict[str, Any] | None, alternatives: list[str]) -> list[str]:
    """Contrôle le devis d'une proposition de dates alternatives.

    Le devis doit exister, porter sur la première période proposée et correspondre au recalcul à partir
    des besoins décalés sur cette période (mêmes chambres, salles décalées, repas inchangés).
    """
    if quote is None:
        return ["statut « dates_alternatives » sans devis joint : calc_devis non appelé"]
    period = parse_period(alternatives[0]) if alternatives else None
    if period is None:
        return []
    if (quote.get("arrivee"), quote.get("depart")) != period:
        return [f"devis joint ({quote.get('arrivee')} → {quote.get('depart')}) ≠ première date alternative proposée"]
    try:
        expected = planning.calculer_devis(**quote_arguments(shift_needs(needs, *period)))["total_ttc"]
    except (ToolError, ValueError, KeyError, TypeError) as error:
        return [f"devis non recalculable sur la première date alternative : {error}"]
    if abs(expected - quote["total_ttc"]) > 0.005:
        gap = f"devis joint {quote['total_ttc']:.2f} EUR ≠ recalcul {expected:.2f} EUR"
        return [f"{gap} à partir des besoins décalés sur la première date alternative"]
    return []


def normalize_text(text: str) -> str:
    """Texte comparé aux motifs : NFKC (espaces insécables, chiffres pleine chasse…), homoglyphes ramenés
    à l'ASCII, puis sans accents ni casse."""
    return planning._sans_accent(unicodedata.normalize("NFKC", text).translate(CONFUSABLES))


def words_value(words: str) -> int:
    """Valeur d'un nombre en lettres (« six mille six cent quatre-vingts » -> 6680)."""
    total = current = previous = 0
    for word in re.split(r"[\s-]+", words):
        value = NUMBER_WORDS.get(word)
        if value is None:  # « et »
            continue
        if value == 20 and previous == 4:  # quatre-vingt(s)
            current += 80 - 4
        elif value == 100:
            current = max(current, 1) * 100
        elif value >= 1000:
            total += max(current, 1) * value
            current = 0
        else:
            current += value
        previous = value
    return total + current


def amounts_in(text: str) -> list[float]:
    """Montants écrits dans un texte, dans l'ordre : chiffres avec devise avant ou après, k€, HTVA, « ,- »,
    ou nombre en lettres suivi d'une devise. Un même passage n'est compté qu'une fois."""
    plain = normalize_text(text)
    found: list[tuple[int, int, float]] = []
    for pattern in (AMOUNT_AFTER, AMOUNT_BEFORE):
        for match in pattern.finditer(plain):
            units = re.sub(r"[ .,']", "", match.group(1))
            value = float(f"{units}.{match.group(2) or 0}")
            found.append((*match.span(), value * 1000 if match.groupdict().get("k") else value))
    found += [(*match.span(), float(words_value(match.group(1)))) for match in AMOUNT_IN_WORDS.finditer(plain)]
    amounts: list[float] = []
    taken: list[tuple[int, int]] = []
    for start, end, value in sorted(found):
        if not any(start < other_end and other_start < end for other_start, other_end in taken):
            taken.append((start, end))
            amounts.append(value)
    return amounts


def is_negated(plain: str, start: int) -> bool:
    """Vrai si une négation figure parmi les NEGATION_WINDOW mots qui précèdent, dans la même phrase."""
    sentence = SENTENCE_END.split(plain[:start])[-1]
    return not NEGATION_WORDS.isdisjoint(re.findall(r"[a-z]+", sentence)[-NEGATION_WINDOW:])


def find_mentions(
    plain: str, patterns: tuple, taken: list[tuple[int, int]], skip_negated: bool
) -> list[str]:
    """Libellés des motifs trouvés ; chaque passage retenu (même nié) est ajouté à taken et compté une fois."""
    labels = []
    for pattern, label in patterns:
        for match in pattern.finditer(plain):
            if any(start < match.end() and match.start() < end for start, end in taken):
                continue
            taken.append(match.span())
            if not (skip_negated and is_negated(plain, match.start())) and label not in labels:
                labels.append(label)
    return labels


def draft_body_problems(body: str, quote_total: float | None) -> tuple[list[str], list[str]]:
    """Contrôle du brouillon en deux niveaux : (bloquants, signalés).

    Bloquants : montant différent du total du devis joint, remise explicite sur le prix (sauf mention niée).
    Signalés : autre pourcentage, « gratuit », « offert », « promotion » (formulations courantes à relire).
    """
    blocking = []
    for amount in amounts_in(body):
        if quote_total is None:
            blocking.append(f"montant {amount:.2f} EUR écrit dans le brouillon alors qu'aucun devis n'est joint")
        elif abs(amount - quote_total) > 0.005:
            blocking.append(
                f"montant {amount:.2f} EUR écrit dans le brouillon ≠ total du devis joint {quote_total:.2f} EUR"
            )
    plain = normalize_text(body)
    taken: list[tuple[int, int]] = []
    blocking += [
        f"le brouillon mentionne « {label} » : aucune remise n'est permise, le prix est celui du devis"
        for label in find_mentions(plain, DISCOUNT_PATTERNS, taken, skip_negated=True)
    ]
    warnings = [
        f"le brouillon mentionne « {label} » : vérifier qu'aucune remise n'est promise"
        for label in find_mentions(plain, WARNING_PATTERNS, taken, skip_negated=False)
    ]
    return blocking, warnings


def check_draft_body(body: str, quote_total: float | None) -> list[str]:
    """Tous les points du brouillon à vérifier (bloquants puis signalés), repris dans la synthèse."""
    blocking, warnings = draft_body_problems(body, quote_total)
    return blocking + warnings


def review_sheet(
    status: str,
    needs: dict[str, Any],
    quote: dict[str, Any] | None,
    alternatives: list[str],
    missing: list[str],
    body: str,
) -> list[str]:
    """Contrôles d'une fiche enregistrée selon son statut ; renvoie les points à vérifier."""
    problems = []
    if status == "proposition" and quote:
        problems += [problem for problem in [check_quote(needs, quote["total_ttc"])] if problem]
    if status == "dates_alternatives":
        if not alternatives:
            problems.append("statut « dates_alternatives » sans aucune date proposée")
        problems += check_alternatives(needs, alternatives)
        problems += check_alternative_quote(needs, quote, alternatives)
    if status == "precisions_requises" and not missing:
        problems.append("statut « precisions_requises » sans aucune information manquante listée")
    if status == "hors_perimetre":
        # Une consigne glissée dans le courriel peut faire écarter une vraie demande : l'humain tranche.
        problems.append(HORS_PERIMETRE_NOTE)
    return problems + check_draft_body(body, quote["total_ttc"] if quote else None)
