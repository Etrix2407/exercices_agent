"""Contrôles en code des textes écrits par le modèle (brouillons) : remises, montants, engagements, taille.

Le prompt interdit déjà remises et prix inventés ; ces contrôles le garantissent quoi que dise le modèle,
y compris sous l'effet d'un mail ou d'un document piégé. Le texte est d'abord normalisé (NFKC, caractères
invisibles retirés, lettres cyrilliques et grecques d'apparence latine remplacées) : un homoglyphe ne
suffit pas à cacher un mot interdit.
"""

from __future__ import annotations

import re
import unicodedata

# Taille maximale d'un texte écrit par le modèle (corps de mail, contenu ou justification d'un dossier).
MAX_TEXT_CHARS = 5000

# Lettres cyrilliques et grecques courantes qui imitent une lettre latine (« Rеmise » avec un е cyrillique).
CONFUSABLES = str.maketrans({
    # Cyrillique
    "а": "a", "е": "e", "ё": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "к": "k",
    "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h",
    "А": "A", "В": "B", "Е": "E", "Ё": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    # Grec
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    # Latin sans point
    "ı": "i",
})
# Caractères invisibles (trait d'union conditionnel, espaces de largeur nulle, marques de direction).
INVISIBLE = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# --- Remises ------------------------------------------------------------------------------------------------------
# Vocabulaire de remise (texte normalisé, sans accents, en minuscules).
DISCOUNT = re.compile(
    r"\b(remise|reduction|rabais|ristourne|discount|promo(tion)?|geste commercial|tarif preferentiel"
    r"|offerte?s?|gratuite?s?|gratuitement|gratis|non[\s-]+factur\w*|a notre charge|a nos frais"
    r"|a titre gracieux|gracieusement|cadeaux?|prix d['’ ]?amis?|moitie prix|demi[\s-]tarif)\b"
)
# Tout pourcentage, en symbole ou en toutes lettres.
PERCENT = re.compile(r"\d\s*%|\bpour[\s-]?cents?\b|\bp\.\s?c\.|\bpct\b|\bpercent\b")
# Négation juste avant une mention (« sans remise », « nous ne pouvons pas accorder de rabais ») :
# sans, aucun(e), ni, jamais, pas de, ou ne … pas/aucun/jamais.
NEGATION = re.compile(
    r"\b(?:sans|aucune?|ni|jamais)\b|\bpas d(?:e\b|u\b|es\b|['’])|\bn(?:e\b|['’]).*\b(?:pas|aucune?|jamais)\b"
)
NEGATION_WINDOW = 5  # mots examinés avant la mention
# Fin de proposition : une négation au-delà ne porte plus sur la mention.
CLAUSE_END = re.compile(r"[.,;:!?\n]")

# --- Engagements fermes (le devis n'est qu'une proposition : rien n'est réservé) ---------------------------------
COMMITMENT = re.compile(
    r"\b(disponibilites? (?:est |sont )?garantie?s?|garantie? disponibles?|livraisons? (?:est |sera )?"
    r"(?:ferme|garantie)s?|(?:reservee?s?|bloquee?s?) pour vous|nous (?:vous )?(?:garantissons|reservons)"
    r"|engagement ferme|commande ferme)\b"
)

# --- Montants -----------------------------------------------------------------------------------------------------
# Nombre : milliers séparés par une espace ou un point, décimales après une virgule ou un point.
# Jamais collé à un mot, une barre ou un deux-points (références NCI-004, dates 02/11, heures 10:30).
NUMBER = re.compile(
    r"(?<![\w/.,:])(?<![\w]-)(\d{1,3}(?:[ .]\d{3})+(?!\d)|\d+)(?:[.,](\d{1,2})(?!\d))?(?![\d/]|[:-]\d)"
)
# Devise après le nombre : « 960 € », « 2 k€ », « 50 EUR », « 84 HTVA », « 84 USD », « 50,- ».
CURRENCY_AFTER = re.compile(
    r"\s*(k\s*)?(€|eur(?:os?)?\b|\$|usd\b|chf\b|£|gbp\b|dollars?\b|francs?\b|htva\b|ht\b|ttc\b|tvac\b"
    r"|hors[\s-]+tax\w*|,-)"
)
# Devise avant le nombre : « €50 », « EUR 50 », « $84 ».
CURRENCY_BEFORE = re.compile(r"(?:€|\beur(?:os?)?|\$|\busd|\bchf|£|\bgbp)\s*$")
# Devises autres que l'euro : jamais dans un brouillon.
FOREIGN_CURRENCY = re.compile(r"\$|£|\b(?:usd|chf|gbp|dollars?|francs? suisses?)\b")
# Mots de prix : un nombre de 2 chiffres ou plus près de l'un d'eux est un montant.
PRICE_WORDS = frozenset({
    "prix", "tarif", "tarifs", "total", "totaux", "montant", "montants", "cout", "couts", "somme", "forfait",
    "net", "ht", "htva", "ttc", "tvac", "euro", "euros", "eur", "facture", "factures", "facturer", "facturee",
    "payer", "paiement", "loyer", "budget", "coute", "coutera",
})
# Mot qui suit un nombre qui n'est pas un montant (durée, mesure, date, quantité).
NOT_MONEY_AFTER = frozenset({
    "jour", "jours", "j", "semaine", "semaines", "mois", "an", "ans", "annee", "annees", "h", "heure",
    "heures", "min", "minutes", "m", "m2", "m3", "metre", "metres", "cm", "mm", "km", "kg", "t", "tonne",
    "tonnes", "l", "litre", "litres", "personne", "personnes", "machine", "machines", "unite", "unites",
    "piece", "pieces", "au", "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre",
})
# Mot qui précède un nombre qui n'est pas un montant (date).
NOT_MONEY_BEFORE = frozenset({
    "du", "au", "le", "les", "entre", "depuis", "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
})
# Numéro de référence juste avant le nombre (« n° 4512 », « réf. 12 », « F- 2026 ») : jamais un montant sans devise.
REFERENCE_BEFORE = re.compile(r"(?:\bn\s*°|\bno\.?|\bnumero|\bref\w*\.?|\b(?:f|loc|cr|bl|dev)\s*-)\s*:?\s*$")
# Date complète JJ.MM.AAAA, JJ/MM/AAAA ou JJ-MM-AAAA : ses nombres ne sont pas des montants sans devise.
DATE = re.compile(r"(?<!\d)\d{1,2}([./-])\d{1,2}\1\d{2,4}(?!\d)")
PRICE_WINDOW_BEFORE, PRICE_WINDOW_AFTER = 4, 2  # mots examinés autour d'un nombre sans devise
# Montant écrit en toutes lettres suivi d'une devise : « quatre-vingt-quatre euros ».
NUMBER_WORD = (
    r"(?:zero|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize"
    r"|vingts?|trente|quarante|cinquante|soixante|septante|octante|huitante|nonante|cents?|milles?|millions?)"
)
WORD_AMOUNT = re.compile(
    rf"\b{NUMBER_WORD}(?:[\s-]+(?:et[\s-]+)?{NUMBER_WORD})*\s*(?:k\s*)?(?:€|euros?\b|eur\b|\$|dollars?\b|francs?\b)"
)
# Lettre O collée à un chiffre (« 84O € ») : lue comme un zéro.
LETTER_ZERO = re.compile(r"(?<=\d)o|o(?=\d)")
WORD = re.compile(r"\w+")
SENTENCE_END = re.compile(r"[.!?\n]")


def normalize(text: str) -> str:
    """Texte en forme NFKC, sans caractères invisibles, homoglyphes cyrilliques et grecs remplacés (casse gardée)."""
    return INVISIBLE.sub("", unicodedata.normalize("NFKC", text or "")).translate(CONFUSABLES)


def plain(text: str) -> str:
    """Texte normalisé, en minuscules, sans accents."""
    decomposed = unicodedata.normalize("NFKD", normalize(text))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def _value(whole: str, cents: str | None) -> float:
    digits = re.sub(r"\D", "", whole)
    return float(f"{digits}.{cents or 0}")


def _near_price_word(simple: str, start: int, end: int) -> bool:
    """Vrai si un mot de prix entoure le nombre et que ni le mot suivant ni le précédent n'en font une date ou
    une mesure."""
    before = WORD.findall(SENTENCE_END.split(simple[max(0, start - 200):start])[-1])[-PRICE_WINDOW_BEFORE:]
    after = WORD.findall(simple[end:end + 100])[:PRICE_WINDOW_AFTER]
    if (after and after[0] in NOT_MONEY_AFTER) or (before and before[-1] in NOT_MONEY_BEFORE):
        return False
    return any(word in PRICE_WORDS for word in before + after)


def _amount(simple: str, match: re.Match, dates: list[tuple[int, int]]) -> float | None:
    """Montant du nombre trouvé s'il est monétaire (devise après ou avant, ou mot de prix voisin), sinon None.
    Sans devise, un numéro de référence ou un nombre pris dans une date (dates : positions) n'est pas un montant."""
    whole, cents = match.group(1), match.group(2)
    value = _value(whole, cents)
    after = CURRENCY_AFTER.match(simple, match.end())
    if after:
        return value * 1000 if after.group(1) else value
    if CURRENCY_BEFORE.search(simple[max(0, match.start() - 12):match.start()]):
        return value
    if REFERENCE_BEFORE.search(simple[max(0, match.start() - 20):match.start()]):
        return None
    if any(start <= match.start() < end for start, end in dates):
        return None
    long_enough = len(re.sub(r"\D", "", whole)) >= 2 or cents
    return value if long_enough and _near_price_word(simple, match.start(), match.end()) else None


def amounts(text: str) -> list[float]:
    """Montants cités dans un texte : devise avant ou après (€, EUR, k€, HT, HTVA, $, USD, CHF, « ,- »), ou
    nombre de 2 chiffres ou plus près d'un mot de prix."""
    simple = LETTER_ZERO.sub("0", plain(text))
    dates = [date.span() for date in DATE.finditer(simple)]
    found = (_amount(simple, match, dates) for match in NUMBER.finditer(simple))
    return [value for value in found if value is not None]


def unknown_amounts(text: str, allowed: set[float]) -> list[float]:
    """Montants du texte absents des montants autorisés (calculés par le code)."""
    return [value for value in amounts(text) if all(abs(value - known) >= 0.01 for known in allowed)]


def amount_problem(text: str, allowed: set[float]) -> str | None:
    """Raison de refuser un texte qui cite une devise étrangère, un montant en lettres ou un montant non
    autorisé ; sinon None."""
    simple = plain(text)
    foreign = FOREIGN_CURRENCY.search(simple)
    if foreign:
        return f"devise autre que l'euro « {foreign.group(0)} »"
    words = WORD_AMOUNT.search(simple)
    if words:
        return f"montant en toutes lettres « {words.group(0)} »"
    unknown = unknown_amounts(text, allowed)
    if unknown:
        return f"montants {unknown} non calculés par le code"
    return None


def negated(simple: str, position: int) -> bool:
    """Vrai si une négation précède la position dans la même proposition (NEGATION_WINDOW mots au plus)."""
    clause = CLAUSE_END.split(simple[:position])[-1]
    return bool(NEGATION.search(" ".join(clause.split()[-NEGATION_WINDOW:])))


def _first_unnegated(pattern: re.Pattern, simple: str) -> str | None:
    for match in pattern.finditer(simple):
        if not negated(simple, match.start()):
            return match.group(0)
    return None


def discount_problem(text: str) -> str | None:
    """Raison de refuser un texte qui parle de remise (hors négation) ou cite un pourcentage, sinon None."""
    simple = plain(text)
    mention = _first_unnegated(DISCOUNT, simple)
    if mention:
        return f"mention « {mention} »"
    if PERCENT.search(simple):
        return "pourcentage cité"
    return None


def commitment_problem(text: str) -> str | None:
    """Raison de refuser un texte qui prend un engagement ferme (disponibilité garantie, réservation), sinon None."""
    mention = _first_unnegated(COMMITMENT, plain(text))
    return f"engagement ferme « {mention} »" if mention else None


def length_problem(text: str, limit: int = MAX_TEXT_CHARS) -> str | None:
    """Raison de refuser un texte trop long, sinon None."""
    return f"{len(text)} caractères, {limit} au plus" if len(text) > limit else None
