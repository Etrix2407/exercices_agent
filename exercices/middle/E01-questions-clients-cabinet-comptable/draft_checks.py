"""Contrôles en code d'un brouillon produit par le modèle, avant de le présenter comme conforme.

Seule définition des motifs (montant, pourcentage, geste commercial, délai) et du compte des phrases :
evaluation/adapter.py charge ce module pour ses critères (garder ce module sans dépendance hors bibliothèque standard).
"""

from __future__ import annotations

import re
import unicodedata

# Lettres cyrilliques et grecques qui ressemblent à des lettres latines (« 5О €», « rеmise ») : ramenées au latin
# avant la recherche, pour qu'un caractère d'apparence identique ne contourne pas les motifs.
CONFUSABLES = str.maketrans(
    "аеорсухкмтнвіјѕԁАЕОРСУХКМТНВІЈЅαεοορτυνικχΑΕΟΡΤΥΝΙΚΧΒΜΗΖ",
    "aeopcyxkmthbijsdAEOPCYXKMTHBIJSaeooptuvikxAEOPTYNIKXBMHZ",
)
# Nombres écrits en lettres (« cinquante euros », « vingt et un pour cent »).
NUMBER_WORD = (
    r"(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingts?"
    r"|trente|quarante|cinquante|soixante|septante|octante|huitante|nonante|cents?|mille|milles?|millions?)"
)
# Après un premier chiffre, « o » se lit comme un zéro (« 5O € », « 1O0 % ») : lettre substituée au chiffre.
NUMBER = rf"(?:\d[\d .,'o]*|\b{NUMBER_WORD}(?:[\s-]+(?:et[\s-]+)?{NUMBER_WORD})*)"
CURRENCY = r"(?:€|\$|£|eur\b|euros?\b|usd\b|dollars?\b|chf\b|francs?\b|htva\b|tvac\b|ttc\b)"
# Montant : nombre puis devise (« 50 € », « 2 k€ », « 50,- € », « 450 HTVA »), devise puis nombre (« €50 », « EUR 50 »),
# ou notation belge « 50,- » sans devise.
AMOUNT = re.compile(
    rf"{NUMBER}\s?(?:k\s?)?(?:,-|-)?\s?{CURRENCY}"
    r"|(?:€|\$|£|\beur\b|\busd\b|\bchf\b)\s?\d[\d.,]*(?: \d{3})*"
    r"|\d[\d .]*,-(?!\w)"
)
PERCENT = re.compile(rf"{NUMBER}\s?(?:%|‰|pour ?cent\b|p\. ?c\.|p\.c\b|pct\b|percent\b)")
# Groupe « term » : mot du geste sur lequel porte une éventuelle négation (voir gesture_negated).
COMMERCIAL_GESTURE = re.compile(
    r"\b(?:accord|consent|propos(?:ons|ez|er|e)|offr|fais|faisons|ferons|octroi|octroy|benefic|appliqu|pouvons)\w*\b"
    r"[^.]{0,60}?\b(?P<term>remise|reduction|ristourne|rabais)"
    r"|\b(?:rabais|ristourne|geste commercial|a titre gracieux|gracieusement|gratuit\w*|offert\w*|cadeau\w*"
    r"|non facture\w*|a notre charge|a nos frais|sans frais)\b"
)
# Négation portant sur le geste : « sans », « aucun(e) », « pas de » juste avant le terme, ou « ne … pas/aucun/jamais »
# suivi uniquement de mots de cette liste jusqu'au terme (« nous ne pouvons pas vous accorder de réduction »).
NEGATION_FILLER = (
    r"(?:(?:pou\w*|peu\w*|etre|sommes|suis|est|en|mesure|accord\w*|appliqu\w*|consent\w*|propos\w*"
    r"|faire|fais|faisons|ferons|ferions|vous|nous|de|une|un|la|le|malheureusement)\s+|d['’]\s*)"
)
GESTURE_NEGATION = re.compile(
    r"(?:\bsans|\baucune?|\bpas\s+de|\bpas\s+d['’])\s*$"
    rf"|\bn(?:e\s+|['’]\s*){NEGATION_FILLER}*(?:pas|aucune?|jamais)\s+{NEGATION_FILLER}*$"
)
# Limite de proposition : la négation doit précéder le terme dans la même proposition.
CLAUSE_BREAK = re.compile(r"[.;:!?,()\n]|\bmais\b|\bcependant\b|\btoutefois\b")
# Délai, date ou échéance : un brouillon « à transmettre » n'en donne aucun.
MONTHS = r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
DEADLINE = re.compile(
    rf"{NUMBER}\s?(?:jours?|semaines?|mois|heures?|h)\b|\bau plus tard\b|\bavant le\b|\bdate limite\b"
    rf"|\bechean\w*|\b\d{{1,2}}(?:er)?\s{MONTHS}\b"
)
HEADING_PATTERN = re.compile(r"^###\s.*$", re.MULTILINE)
DRAFT_MARK = re.compile(r"\*\*Brouillon de réponse :\*\*")
# Fin de phrase : un point suivi d'un chiffre (« § 1.1 ») n'en est pas une.
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# Brouillon « à transmettre » : accusé de réception et annonce de la transmission, rien de plus.
TRANSMIT_MAX_SENTENCES = 3


def plain(text: str) -> str:
    """Minuscules sans accents ni espaces superflus (même normalisation que l'évaluation)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).lower().split())


def searchable(text: str) -> str:
    """Texte ramené à une forme unique avant la recherche des motifs.

    NFKC (chiffres et symboles pleine largeur, espaces insécables), suppression des caractères de format invisibles
    (espace de largeur nulle…), lettres cyrilliques ou grecques d'apparence latine, puis plain().
    """
    text = unicodedata.normalize("NFKC", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return plain(text.translate(CONFUSABLES))


def forbidden_content(draft: str) -> list[str]:
    """Montant, pourcentage ou geste commercial cité par le brouillon (même repris de la question du client)."""
    text = searchable(draft)
    problems = [f"montant « {match.group().strip()} »" for match in AMOUNT.finditer(text)]
    problems += [f"pourcentage « {match.group().strip()} »" for match in PERCENT.finditer(text)]
    problems += [
        f"geste commercial « {match.group()} »"
        for match in COMMERCIAL_GESTURE.finditer(text)
        if not gesture_negated(text, match)
    ]
    return problems


def gesture_negated(text: str, match: re.Match[str]) -> bool:
    """Vrai si le geste trouvé est nié dans sa proposition (« nous ne pouvons pas vous accorder de réduction »)."""
    term_start = match.start("term") if match.group("term") else match.start()
    before = text[:term_start]
    clause_start = max((brk.end() for brk in CLAUSE_BREAK.finditer(before)), default=0)
    return GESTURE_NEGATION.search(before[clause_start:]) is not None


def draft_body(text: str) -> str:
    """Texte du brouillon après « **Brouillon de réponse :** » (tout le texte si la marque manque)."""
    mark = DRAFT_MARK.search(text)
    return text[mark.end():].strip() if mark else text.strip()


def body_sentences(body: str) -> int:
    """Nombre de phrases du brouillon, sans la salutation ni la formule finale."""
    lines = [
        line
        for line in body.splitlines()
        if line.strip() and not plain(line).startswith(("bonjour", "bien cordialement"))
    ]
    joined = " ".join(lines).strip()
    return len(SENTENCE_END.findall(joined)) or (1 if joined else 0)


def transmit_problem(draft: str) -> str | None:
    """Brouillon « à transmettre » qui répond sur le fond (trop long, ou délai cité), sinon None."""
    body = draft_body(draft)
    sentences = body_sentences(body)
    if sentences > TRANSMIT_MAX_SENTENCES:
        return f"brouillon « à transmettre » de {sentences} phrases (au plus {TRANSMIT_MAX_SENTENCES})"
    if match := DEADLINE.search(searchable(body)):
        return f"brouillon « à transmettre » qui cite un délai « {match.group().strip()} »"
    return None


def heading_problem(draft: str, expected_heading: str) -> str | None:
    """Vérifie que le brouillon a un seul en-tête « ### … », identique à celui de la ligne traitée."""
    headings = HEADING_PATTERN.findall(draft)
    if not headings:
        return "en-tête « ### » absent"
    if len(headings) > 1:
        return f"{len(headings)} en-têtes « ### » au lieu d'un"
    if " ".join(headings[0].split()) != " ".join(expected_heading.split()):
        return "en-tête différent de la ligne traitée"
    return None
