"""Tests du moteur et des critères génériques (sans agent ni modèle)."""

from pathlib import Path

from pipeline_test.criteria import exact_match, keywords_found, no_problems, stability
from pipeline_test.engine import Adapter, Criterion, Group, evaluate


def make_adapter(*criteria: Criterion) -> Adapter:
    return Adapter(name="test", kit_dir=Path("."), run_commands=[], collect=dict, criteria=list(criteria))


def snapshot(statuses: dict[str, str], problems: list[str] | None = None) -> dict:
    return {"cases": {key: {"statut": value} for key, value in statuses.items()}, "global": {"problemes": problems or []}}


EXPECTED = {"_aide": "ignoré", "a": {"statut": "ok"}, "b": {"statut": "ok"}}


def test_weights_of_unmeasured_criteria_are_redistributed():
    adapter = make_adapter(
        Criterion("statut", "Statut", 50, exact_match("statut")),
        Criterion("stabilite", "Stabilité", 50, stability(lambda case: case.get("statut")), scope="runs"),
    )
    evaluation = evaluate(adapter, [snapshot({"a": "ok", "b": "ko"})], EXPECTED)
    assert evaluation.criteria[1].value is None
    assert evaluation.total == 50.0


def test_failed_eliminatory_criterion_gives_zero():
    adapter = make_adapter(
        Criterion("statut", "Statut", 90, exact_match("statut")),
        Criterion("securite", "Sécurité", 10, no_problems(), scope="global", eliminatory=True),
    )
    evaluation = evaluate(adapter, [snapshot({"a": "ok", "b": "ok"}, ["courriel envoyé"])], EXPECTED)
    assert evaluation.eliminated
    assert evaluation.total == 0.0


def test_several_runs_give_mean_and_stability():
    adapter = make_adapter(
        Criterion("statut", "Statut", 50, exact_match("statut")),
        Criterion("stabilite", "Stabilité", 50, stability(lambda case: case.get("statut")), scope="runs"),
    )
    runs = [snapshot({"a": "ok", "b": "ok"}), snapshot({"a": "ok", "b": "ko"})]
    evaluation = evaluate(adapter, runs, EXPECTED)
    assert evaluation.run_totals == [100.0, 50.0]
    assert evaluation.criteria[1].value == 0.5
    assert evaluation.total == 62.5


def test_groups_give_one_score_per_agent_and_their_mean():
    adapter = make_adapter(
        Criterion("statut", "Statut", 50, exact_match("statut")),
        Criterion("securite", "Sécurité", 10, no_problems(), scope="global", eliminatory=True),
    )
    adapter = Adapter(**{**adapter.__dict__, "groups": [
        Group("agent_a", ("statut",), lambda wanted: wanted.get("agent") == "a"),
        Group("agent_b", ("statut", "securite"), lambda wanted: wanted.get("agent") == "b"),
    ]})
    expected = {"a1": {"statut": "ok", "agent": "a"}, "a2": {"statut": "ok", "agent": "a"}, "b1": {"statut": "ok", "agent": "b"}}
    evaluation = evaluate(adapter, [snapshot({"a1": "ok", "a2": "ko", "b1": "ok"})], expected)
    assert evaluation.groups == {"agent_a": 50.0, "agent_b": 100.0}
    assert evaluation.total == 75.0
    assert evaluation.run_totals == [75.0]

    eliminated = evaluate(adapter, [snapshot({"a1": "ok", "a2": "ok", "b1": "ok"}, ["courriel envoyé"])], expected)
    assert eliminated.total == 0.0 and eliminated.groups["agent_b"] == 0.0


def test_keywords_penalize_missing_and_extra_items():
    check = keywords_found("infos")
    assert check({"infos": ["Date d'arrivée"]}, {"infos": ["arrivee"]}, {}).value == 1
    assert check({"infos": ["date d'arrivée", "budget"]}, {"infos": ["arrivee"]}, {}).value == 0.5
    assert check({"infos": ["budget"]}, {"infos": []}, {}).value == 0
