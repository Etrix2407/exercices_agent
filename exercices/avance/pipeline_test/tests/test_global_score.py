"""Test global : la note de chaque agent, calculée sur ses sorties actuelles, atteint le seuil.

N'appelle aucun modèle et n'écrit aucun rapport : pour relancer l'agent, utiliser python -m pipeline_test --runs N.
"""

import pytest

from pipeline_test.__main__ import available_agents, load_adapter, load_expected
from pipeline_test.engine import evaluate

MIN_SCORE = 80


@pytest.mark.parametrize("agent", available_agents())
def test_global_score_reaches_threshold(agent: str, record_property):
    adapter = load_adapter(agent)
    snapshot = adapter.collect()
    if not snapshot["cases"]:
        pytest.skip(f"{agent} : aucune sortie à noter (lancer l'agent d'abord)")
    evaluation = evaluate(adapter, [snapshot], load_expected(agent))
    summary = "\n".join(
        f"  {result.label} : {'non mesuré' if result.value is None else f'{100 * result.value:.0f} %'}"
        for result in evaluation.criteria
    )
    verdict = "ÉLIMINÉ" if evaluation.eliminated else f"{evaluation.total} / 100"
    # Affichée en fin de pytest par conftest.py, que le test passe ou non.
    record_property("note", f"{agent} ({', '.join(evaluation.models)}) : {verdict} (seuil {MIN_SCORE})\n{summary}")
    assert not evaluation.eliminated, f"{agent} éliminé (critère éliminatoire non respecté) :\n{summary}"
    assert evaluation.total >= MIN_SCORE, f"{agent} : {evaluation.total} / 100 < {MIN_SCORE}\n{summary}"
