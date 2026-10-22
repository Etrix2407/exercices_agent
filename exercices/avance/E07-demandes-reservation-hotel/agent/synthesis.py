"""Résultats des demandes et synthèse : format Markdown, écriture atomique, fusion cumulative entre lancements."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SYNTHESIS_NAME = "synthese.md"
RESULTS_NAME = "resultats.json"
# Statuts qui ne remplacent jamais un résultat valide déjà enregistré pour la même demande.
FAILED_STATUSES = ("erreur", "non_traitee")
FAILURE_PREFIX = "dernier traitement en échec"
# Textes venant du modèle (points à vérifier, dates…) : nombre et longueur bornés dans la synthèse.
MAX_MODEL_TEXTS = 10
MAX_MODEL_TEXT_LENGTH = 300
# Caractères Markdown échappés (barre oblique inverse d'abord) : liens, images, HTML, code, tableau.
MARKDOWN_SPECIALS = re.compile(r"[\\<>\[\]()`|]")

logger = logging.getLogger(__name__)


@dataclass
class RequestResult:
    """Résultat d'une demande, repris dans la synthèse.

    Exception à la règle « identifiants en anglais » : les champs gardent les noms français de la fiche JSON
    (demande_id, statut, besoins…), qui forment le contrat avec le prompt système et le format de resultats.json.
    """

    demande_id: str
    statut: str
    besoins: dict[str, Any] = field(default_factory=dict)
    informations_manquantes: list[str] = field(default_factory=list)
    dates_alternatives: list[str] = field(default_factory=list)
    devis_total: float | None = None
    brouillon: str = ""
    points_a_verifier: list[str] = field(default_factory=list)
    traite_le: str = ""
    changements: list[str] = field(default_factory=list)


def load_previous_results(output_dir: Path) -> dict[str, RequestResult]:
    """Relit resultats.json : les demandes déjà analysées restent dans la synthèse d'un lancement à l'autre."""
    path = output_dir / RESULTS_NAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = set(RequestResult.__dataclass_fields__)
        items = [RequestResult(**{key: value for key, value in entry.items() if key in known}) for entry in raw]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        logger.warning("Résultats précédents illisibles (%s) : la synthèse repart de zéro.", error)
        return {}
    return {item.demande_id: item for item in items}


def _display(value: Any) -> str:
    """Valeur lisible pour la synthèse : chambres « 12 double, 2 suite », liste vide « aucune »…"""
    if value is None or value == []:
        return "aucune"
    if isinstance(value, float):
        return f"{value:.2f} EUR"
    if isinstance(value, list):
        return ", ".join(
            f"{item.get('nombre')} {item.get('type')}" if isinstance(item, dict) and "type" in item else str(item)
            for item in value
        )
    return str(value)


def describe_changes(previous: RequestResult | None, current: RequestResult) -> list[str]:
    """Liste ce qui a changé depuis la dernière analyse, avec la nouvelle valeur seulement (pas l'ancienne)."""
    if previous is None:
        return []
    old_needs, new_needs = previous.besoins or {}, current.besoins or {}
    compared = [
        ("statut", previous.statut, current.statut),
        ("arrivée", old_needs.get("date_arrivee"), new_needs.get("date_arrivee")),
        ("départ", old_needs.get("date_depart"), new_needs.get("date_depart")),
        ("effectif", old_needs.get("nb_personnes"), new_needs.get("nb_personnes")),
        ("chambres", old_needs.get("chambres"), new_needs.get("chambres")),
        ("devis", previous.devis_total, current.devis_total),
        ("informations manquantes", previous.informations_manquantes, current.informations_manquantes),
    ]
    return [f"{label} : {_display(new)}" for label, old, new in compared if old != new]


def merge_result(known: dict[str, RequestResult], result: RequestResult, processed_at: str) -> None:
    """Ajoute ou met à jour une demande ; un échec ne remplace pas un résultat valide déjà enregistré."""
    previous = known.get(result.demande_id)
    if result.statut in FAILED_STATUSES and previous is not None and previous.statut not in FAILED_STATUSES:
        reason = "; ".join(result.points_a_verifier) or result.statut
        previous.points_a_verifier = [
            point for point in previous.points_a_verifier if not point.startswith(FAILURE_PREFIX)
        ] + [f"{FAILURE_PREFIX} ({processed_at}), résultat précédent conservé : {reason}"]
        return
    result.traite_le = processed_at
    result.changements = describe_changes(previous, result)
    known[result.demande_id] = result


def clip_text(value: Any) -> str:
    """Texte du modèle tronqué à MAX_MODEL_TEXT_LENGTH caractères."""
    text = str(value)
    return text if len(text) <= MAX_MODEL_TEXT_LENGTH else text[: MAX_MODEL_TEXT_LENGTH - 1] + "…"


def model_texts(values: Any) -> list[str]:
    """Textes recopiés de la fiche du modèle : au plus MAX_MODEL_TEXTS, chacun tronqué à MAX_MODEL_TEXT_LENGTH."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    texts = [clip_text(value) for value in values[:MAX_MODEL_TEXTS]]
    if len(values) > MAX_MODEL_TEXTS:
        texts.append(f"{len(values) - MAX_MODEL_TEXTS} élément(s) supplémentaire(s) omis")
    return texts


def table_cell(text: str) -> str:
    """Neutralise le Markdown actif (liens, images, HTML, code) et les séparateurs de tableau."""
    return MARKDOWN_SPECIALS.sub(r"\\\g<0>", " ".join(text.split()))


def format_synthesis(
    results: list[RequestResult],
    model: str,
    planning_unchanged: bool,
    progress: tuple[int, int] | None = None,
) -> str:
    """Construit le tableau de synthèse de toutes les demandes analysées, au format Markdown.

    progress = (demandes traitées, demandes prévues) pour le lancement en cours : tant qu'il n'est pas
    fini, une ligne d'avancement l'indique.
    """
    rows = []
    for item in results:
        needs = item.besoins
        stay = (
            f"{clip_text(needs.get('date_arrivee') or '?')} → {clip_text(needs.get('date_depart') or '?')}"
            if needs
            else "—"
        )
        cells = [
            item.demande_id,
            item.statut,
            stay,
            "; ".join(item.informations_manquantes) or "—",
            "; ".join(item.dates_alternatives) or "—",
            f"{item.devis_total:.2f}" if item.devis_total is not None else "—",
            item.brouillon or "—",
            item.traite_le or "—",
            "; ".join(item.changements) or "—",
        ]
        rows.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    points = [f"- {item.demande_id} : {table_cell(point)}" for item in results for point in item.points_a_verifier]
    lines = [
        "# Synthèse des demandes de groupe",
        "",
        f"Modèle : `{model}`",
        "Planning inchangé : " + ("oui" if planning_unchanged else "**NON — vérifier immédiatement**"),
    ]
    if progress is not None and progress[0] < progress[1]:
        lines.append(f"Avancement : {progress[0]}/{progress[1]} demandes traitées (lot en cours)")
    lines += [
        "",
        (
            "| Demande | Statut | Séjour | Informations manquantes | Dates alternatives | Devis (EUR TTC) | Brouillon "
            "| Traité le | Changements |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    if points:
        lines += ["## Points à vérifier", "", *points, ""]
    lines += ["Aucun envoi : le service commercial relit chaque brouillon et décide de l'envoi.", ""]
    return "\n".join(lines)


def _write_atomic(path: Path, text: str) -> None:
    """Écrit dans un fichier temporaire du même dossier puis le renomme : jamais de fichier à moitié écrit."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(
    results: list[RequestResult],
    model: str,
    planning_unchanged: bool,
    output_dir: Path,
    progress: tuple[int, int] | None = None,
) -> str:
    """Écrit la synthèse et les résultats bruts (de façon atomique) ; renvoie la synthèse."""
    synthesis = format_synthesis(results, model, planning_unchanged, progress)
    _write_atomic(output_dir / SYNTHESIS_NAME, synthesis)
    raw = json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
    _write_atomic(output_dir / RESULTS_NAME, raw + "\n")
    return synthesis
