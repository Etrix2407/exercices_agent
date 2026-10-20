"""Bibliothèque de critères génériques, à composer dans l'adaptateur de chaque agent.

Chaque fabrique renvoie une fonction check utilisable dans engine.Criterion :
- scope « case » : check(actuel, attendu, snapshot) -> Score | None ;
- scope « global » : check(snapshot, attendus) -> Score | None ;
- scope « runs » : check(snapshots) -> Score | None.
Un champ attendu à null (ou absent) n'est pas évalué : le critère renvoie None pour ce cas.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Hashable
from typing import Any

from pipeline_test.engine import Score, Snapshot

CaseCheck = Callable[[dict, dict, Snapshot], Score | None]


def plain(text: Any) -> str:
    """Minuscules sans accents ni espaces superflus : pour comparer des textes libres."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).lower().split())


def exact_match(field: str, extra: CaseCheck | None = None) -> CaseCheck:
    """Le champ vaut exactement la valeur attendue (ex. statut, catégorie, décision).

    extra : contrôle complémentaire appliqué seulement si la valeur est juste (ex. vérifier une proposition).
    """

    def check(actual: dict, expected: dict, snapshot: Snapshot) -> Score | None:
        wanted = expected.get(field)
        if wanted is None:
            return None
        got = actual.get(field)
        if got != wanted:
            return Score(0, f"{field} « {got} » au lieu de « {wanted} »")
        return extra(actual, expected, snapshot) if extra else Score(1)

    return check


def fields_match(field: str, normalizers: dict[str, Callable[[Any], Any]] | None = None) -> CaseCheck:
    """Part des sous-champs attendus de actual[field] qui sont justes (ex. extraction d'une demande).

    normalizers : {sous-champ: fonction} pour comparer sans tenir compte de l'ordre, de la casse…
    """
    normalizers = normalizers or {}

    def normalize(key: str, value: Any) -> Any:
        try:
            return normalizers.get(key, lambda item: item)(value)
        except (TypeError, ValueError, KeyError, AttributeError):
            return repr(value)

    def check(actual: dict, expected: dict, _snapshot: Snapshot) -> Score | None:
        wanted = {key: value for key, value in (expected.get(field) or {}).items() if value is not None}
        if not wanted:
            return None
        got = actual.get(field) or {}
        wrong = [key for key, value in wanted.items() if normalize(key, got.get(key)) != normalize(key, value)]
        detail = "faux : " + ", ".join(f"{key} = {got.get(key)!r}" for key in wrong) if wrong else ""
        return Score(1 - len(wrong) / len(wanted), detail)

    return check


def number_close(
    field: str,
    tolerance: float = 0.01,
    reference: Callable[[dict, dict, Snapshot], float | None] | None = None,
) -> CaseCheck:
    """Le nombre produit est égal à la référence, à la tolérance près (ex. montant d'un devis).

    La référence est expected[field] ; à défaut, reference(actuel, attendu, snapshot) la recalcule en code.
    """

    def check(actual: dict, expected: dict, snapshot: Snapshot) -> Score | None:
        wanted = expected.get(field)
        if wanted is None and reference is not None:
            wanted = reference(actual, expected, snapshot)
        if wanted is None:
            return None
        got = actual.get(field)
        if not isinstance(got, (int, float)):
            return Score(0, f"{field} absent (attendu {wanted})")
        if abs(got - wanted) > tolerance:
            return Score(0, f"{field} {got} au lieu de {wanted}")
        return Score(1)

    return check


def keywords_found(field: str) -> CaseCheck:
    """Chaque mot-clé attendu apparaît dans un élément de la liste produite ; les éléments en trop pénalisent.

    Attendu [] : la liste produite doit être vide (rien inventé).
    """

    def check(actual: dict, expected: dict, _snapshot: Snapshot) -> Score | None:
        keywords = expected.get(field)
        if keywords is None:
            return None
        items = [plain(item) for item in actual.get(field) or []]
        if not keywords:
            return Score(1) if not items else Score(0, f"{field} inventé(s) : {actual.get(field)}")
        missed = [word for word in keywords if not any(plain(word) in item for item in items)]
        recall = 1 - len(missed) / len(keywords)
        extra = max(0, len(items) - len(keywords))
        detail = "; ".join(
            part
            for part in (f"non détecté : {', '.join(missed)}" if missed else "", f"{extra} élément(s) en trop" if extra else "")
            if part
        )
        return Score(recall * len(keywords) / (len(keywords) + extra), detail)

    return check


def text_rules(field: str, rules: list[tuple[str, Callable[[str, dict, dict], bool | None]]]) -> CaseCheck:
    """Part des règles respectées par un texte produit (ex. brouillon de réponse).

    rules : [(libellé, règle(texte, actuel, attendu) -> True / False / None si non applicable)].
    Le cas n'est pas évalué si l'agent n'a rien produit pour ce cas.
    """

    def check(actual: dict, expected: dict, _snapshot: Snapshot) -> Score | None:
        text = str(actual.get(field) or "")
        if not text.strip():
            return Score(0, f"{field} vide")
        verdicts = [(label, rule(text, actual, expected)) for label, rule in rules]
        applicable = [(label, ok) for label, ok in verdicts if ok is not None]
        if not applicable:
            return None
        failed = [label for label, ok in applicable if not ok]
        return Score(1 - len(failed) / len(applicable), "règle(s) non respectée(s) : " + ", ".join(failed) if failed else "")

    return check


def contains_any(*patterns: str) -> Callable[[str, dict, dict], bool]:
    """Règle : le texte contient au moins un des motifs (regex écrites sans accents ; casse et accents ignorés)."""
    return lambda text, _actual, _expected: any(re.search(pattern, plain(text), re.IGNORECASE) for pattern in patterns)


def contains_none(*patterns: str) -> Callable[[str, dict, dict], bool]:
    """Règle : le texte ne contient aucun des motifs interdits (regex écrites sans accents ; casse et accents ignorés)."""
    return lambda text, _actual, _expected: not any(re.search(pattern, plain(text), re.IGNORECASE) for pattern in patterns)


def call_budget(field: str = "appels_outils", budget: int = 6, failed_status: tuple[str, ...] = ("erreur",)) -> CaseCheck:
    """Efficacité : 1 si l'agent reste dans son budget d'appels, puis décroît ; moitié moins si un outil a été refusé."""

    def check(actual: dict, _expected: dict, _snapshot: Snapshot) -> Score | None:
        if actual.get("statut") in failed_status:
            return Score(0, f"statut « {actual.get('statut')} »")
        calls = actual.get(field)
        if calls is None:
            return None if actual else Score(0, "cas absent")
        value = 1.0 if calls <= budget else max(0.0, 1 - (calls - budget) / budget)
        details = [f"{calls} appels (budget {budget})"] if calls > budget else []
        if actual.get("refus_outils"):
            value /= 2
            details.append(f"{actual['refus_outils']} appel(s) refusé(s)")
        return Score(value, "; ".join(details))

    return check


def no_problems(field: str = "problemes") -> Callable[[Snapshot, dict], Score]:
    """Critère global : la liste snapshot["global"][field] des problèmes constatés doit être vide (ex. sécurité)."""

    def check(snapshot: Snapshot, _expected: dict) -> Score:
        problems = snapshot.get("global", {}).get(field) or []
        return Score(0, "; ".join(problems)) if problems else Score(1)

    return check


def stability(signature: Callable[[dict], Hashable]) -> Callable[[list[Snapshot]], Score | None]:
    """Critère inter-lancements : part des cas dont la signature est identique sur tous les lancements."""

    def check(snapshots: list[Snapshot]) -> Score | None:
        if len(snapshots) < 2:
            return None
        case_ids = sorted({case_id for snap in snapshots for case_id in snap["cases"]})
        if not case_ids:
            return None
        unstable = [
            case_id
            for case_id in case_ids
            if len({repr(signature(snap["cases"].get(case_id, {}))) for snap in snapshots}) > 1
        ]
        detail = "résultat différent d'un lancement à l'autre : " + ", ".join(unstable) if unstable else ""
        return Score(1 - len(unstable) / len(case_ids), detail)

    return check
