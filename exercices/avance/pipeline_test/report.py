"""Rapports d'évaluation : Markdown lisible, JSON complet et historique CSV pour comparer les lancements."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from pipeline_test.engine import Evaluation


def _percent(value: float | None) -> str:
    return "non mesuré" if value is None else f"{100 * value:.0f} %"


def to_markdown(evaluation: Evaluation, date: str) -> str:
    """Rapport lisible : note globale, tableau des critères, puis les écarts constatés."""
    spread = evaluation.spread
    verdict = "**ÉLIMINÉ** (critère éliminatoire non respecté)" if evaluation.eliminated else f"**{evaluation.total} / 100**"
    lines = [
        f"# Évaluation de l'agent {evaluation.agent}",
        "",
        f"Date : {date} — Modèle(s) : {', '.join(evaluation.models)} — Lancements : {evaluation.runs}",
        "",
        f"Note globale : {verdict}",
    ]
    if evaluation.runs > 1 and spread:
        lines.append(
            f"Par lancement : moyenne {spread['moyenne']}, écart-type {spread['ecart_type']}, "
            f"min {spread['min']}, max {spread['max']}"
        )
    lines += ["", "| Critère | Poids | Note | Écarts |", "|---|---|---|---|"]
    for result in evaluation.criteria:
        label = result.label + (" (éliminatoire)" if result.eliminatory else "")
        lines.append(f"| {label} | {result.weight:g} | {_percent(result.value)} | {len(result.details)} |")
    lines += ["", "Les poids des critères non mesurés sont répartis sur les autres.", ""]
    for result in evaluation.criteria:
        if result.details:
            lines += [f"## {result.label}", "", *(f"- {detail}" for detail in result.details), ""]
    return "\n".join(lines)


def write_reports(evaluation: Evaluation, folder: Path, stamp: str, date: str) -> Path:
    """Écrit le rapport Markdown et le JSON ; renvoie le chemin du Markdown."""
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{evaluation.agent}_{stamp}"
    markdown_path = base.with_suffix(".md")
    markdown_path.write_text(to_markdown(evaluation, date), encoding="utf-8")
    data = {**asdict(evaluation), "date": date, "repartition": evaluation.spread}
    base.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return markdown_path


def append_history(evaluation: Evaluation, path: Path, date: str) -> None:
    """Ajoute une ligne par évaluation : permet de suivre et comparer agents et modèles dans le temps."""
    criteria = {result.key: "" if result.value is None else round(100 * result.value, 1) for result in evaluation.criteria}
    spread = evaluation.spread
    row = {
        "date": date,
        "agent": evaluation.agent,
        "modeles": " ".join(evaluation.models),
        "lancements": evaluation.runs,
        "note": evaluation.total,
        "elimine": evaluation.eliminated,
        "ecart_type": spread.get("ecart_type", ""),
        **criteria,
    }
    existing_header: list[str] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as file:
            existing_header = next(csv.reader(file), [])
    header = existing_header + [key for key in row if key not in existing_header]
    rows = []
    if existing_header and header != existing_header:
        # Nouveau critère : on réécrit le fichier avec l'en-tête élargi.
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
    mode = "a" if header == existing_header else "w"
    with path.open(mode, encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=header, restval="")
        if mode == "w":
            writer.writeheader()
            writer.writerows(rows)
        writer.writerow(row)
