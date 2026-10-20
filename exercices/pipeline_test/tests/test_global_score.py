"""Test global : la note de chaque agent, calculée sur ses sorties actuelles, atteint le seuil.

Couvre chaque exercice qui a un dossier evaluation/. N'appelle aucun modèle et n'écrit aucun rapport :
pour relancer l'agent, utiliser python -m pipeline_test <agent> --runs N.
"""

import pytest

from pipeline_test.engine import evaluate
from pipeline_test.registry import discover

MIN_SCORE = 80
EXERCISES = discover()


@pytest.mark.parametrize("agent", list(EXERCISES))
def test_global_score_reaches_threshold(agent: str, record_property):
    exercise = EXERCISES[agent]
    snapshot = exercise.adapter.collect()
    if not snapshot["cases"]:
        pytest.skip(f"{agent} : aucune sortie à noter (lancer l'agent d'abord)")
    evaluation = evaluate(exercise.adapter, [snapshot], exercise.expected())
    summary = "\n".join(
        f"  {result.label} : {'non mesuré' if result.value is None else f'{100 * result.value:.0f} %'}"
        for result in evaluation.criteria
    )
    verdict = "ÉLIMINÉ" if evaluation.eliminated else f"{evaluation.total} / 100"
    # Affichée en fin de pytest par conftest.py, que le test passe ou non.
    record_property("note", f"{agent} ({', '.join(evaluation.models)}) : {verdict} (seuil {MIN_SCORE})\n{summary}")
    assert not evaluation.eliminated, f"{agent} éliminé (critère éliminatoire non respecté) :\n{summary}"
    assert evaluation.total >= MIN_SCORE, f"{agent} : {evaluation.total} / 100 < {MIN_SCORE}\n{summary}"
