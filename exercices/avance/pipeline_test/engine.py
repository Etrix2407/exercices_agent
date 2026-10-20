"""Moteur générique de notation d'un agent : critères pondérés, note sur 100, statistiques sur plusieurs lancements.

Le moteur ne connaît aucun agent. Chaque agent fournit un adaptateur (voir adapters/) qui :
- relève ses sorties dans un instantané (snapshot) : {"cases": {id: {...}}, "global": {...}} ;
- déclare ses critères (fonctions qui renvoient un Score entre 0 et 1, ou None si non mesurable).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Literal

Snapshot = dict[str, Any]


@dataclass(frozen=True)
class Score:
    """Note d'un critère sur un cas : value entre 0 et 1, detail expliquant ce qui manque."""

    value: float
    detail: str = ""


@dataclass(frozen=True)
class Criterion:
    """Critère pondéré.

    scope « case » : check(actuel, attendu, snapshot) appelé pour chaque cas attendu ;
    scope « global » : check(snapshot, attendus) appelé une fois par lancement ;
    scope « runs » : check(snapshots) appelé une fois sur tous les lancements (ex. stabilité).
    Un critère éliminatoire non parfait met la note globale à 0.
    """

    key: str
    label: str
    weight: float
    check: Callable[..., Score | None]
    scope: Literal["case", "global", "runs"] = "case"
    eliminatory: bool = False


@dataclass(frozen=True)
class Adapter:
    """Ce qu'un agent doit fournir pour être noté."""

    name: str
    kit_dir: Path
    run_command: list[str]
    collect: Callable[[], Snapshot]
    criteria: list[Criterion]


@dataclass
class CriterionResult:
    key: str
    label: str
    weight: float
    eliminatory: bool
    value: float | None
    per_run: list[float | None] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    agent: str
    models: list[str]
    runs: int
    criteria: list[CriterionResult]
    total: float
    eliminated: bool
    run_totals: list[float]

    @property
    def spread(self) -> dict[str, float]:
        """Moyenne, écart-type, min et max des notes par lancement (hors critères inter-lancements)."""
        if not self.run_totals:
            return {}
        return {
            "moyenne": round(mean(self.run_totals), 1),
            "ecart_type": round(pstdev(self.run_totals), 1),
            "min": round(min(self.run_totals), 1),
            "max": round(max(self.run_totals), 1),
        }


def _weighted(values: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Moyenne pondérée sur 100 des critères mesurés ; les poids des critères non mesurés sont redistribués."""
    measured = {key: value for key, value in values.items() if value is not None}
    total_weight = sum(weights[key] for key in measured)
    if not total_weight:
        return None
    return 100 * sum(weights[key] * value for key, value in measured.items()) / total_weight


def _score_run(criterion: Criterion, snapshot: Snapshot, expected: dict, prefix: str) -> tuple[float | None, list[str]]:
    """Note un critère « case » ou « global » sur un lancement ; renvoie la moyenne et les écarts constatés."""
    if criterion.scope == "global":
        scores = {"": criterion.check(snapshot, expected)}
    else:
        scores = {}
        for case_id, wanted in expected.items():
            score = criterion.check(snapshot["cases"].get(case_id, {}), wanted or {}, snapshot)
            # Cas attendu mais non traité par l'agent : 0 sur chaque critère qui l'aurait évalué.
            if score is not None and case_id not in snapshot["cases"]:
                score = Score(0, "cas absent des sorties de l'agent")
            scores[case_id] = score
    measured = {case_id: score for case_id, score in scores.items() if score is not None}
    details = [
        f"{prefix}{case_id + ' : ' if case_id else ''}{score.detail or 'incomplet'}"
        for case_id, score in measured.items()
        if score.value < 1
    ]
    return (mean(score.value for score in measured.values()) if measured else None), details


def evaluate(adapter: Adapter, snapshots: list[Snapshot], expected: dict) -> Evaluation:
    """Applique les critères de l'adaptateur aux instantanés (un par lancement) et calcule la note."""
    expected = {key: value for key, value in expected.items() if not key.startswith("_")}
    results = []
    for criterion in adapter.criteria:
        result = CriterionResult(criterion.key, criterion.label, criterion.weight, criterion.eliminatory, None)
        if criterion.scope == "runs":
            score = criterion.check(snapshots)
            if score is not None:
                result.value = score.value
                result.details = [score.detail] if score.detail else []
        else:
            for index, snapshot in enumerate(snapshots, start=1):
                prefix = f"lancement {index} — " if len(snapshots) > 1 else ""
                value, details = _score_run(criterion, snapshot, expected, prefix)
                result.per_run.append(value)
                result.details += details
            measured = [value for value in result.per_run if value is not None]
            result.value = mean(measured) if measured else None
        results.append(result)

    weights = {result.key: result.weight for result in results}
    eliminatory = [result for result in results if result.eliminatory]
    eliminated = any(
        any(value is not None and value < 1 for value in result.per_run or [result.value]) for result in eliminatory
    )
    total = _weighted({result.key: result.value for result in results}, weights) or 0.0
    run_totals = []
    for index in range(len(snapshots)):
        run_values = {result.key: result.per_run[index] for result in results if result.per_run}
        run_total = _weighted(run_values, weights)
        if run_total is not None:
            run_eliminatory = [result.per_run[index] for result in eliminatory if result.per_run]
            run_failed = any(value is not None and value < 1 for value in run_eliminatory)
            run_totals.append(0.0 if run_failed else run_total)
    models = sorted({str(snap.get("global", {}).get("modele", "?")) for snap in snapshots})
    return Evaluation(
        agent=adapter.name,
        models=models,
        runs=len(snapshots),
        criteria=results,
        total=0.0 if eliminated else round(total, 1),
        eliminated=eliminated,
        run_totals=[round(value, 1) for value in run_totals],
    )
