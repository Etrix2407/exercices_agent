"""Pipeline de notation des agents.

Usage (depuis le dossier exercices) :
    python -m pipeline_test e07                  # note les sorties actuelles de l'agent
    python -m pipeline_test e07 --runs 5         # relance l'agent 5 fois (avec --reset) puis note
    python -m pipeline_test --all --runs 3       # tous les exercices qui ont un dossier evaluation/
    python -m pipeline_test e07 --rescore avance/E07-demandes-reservation-hotel/evaluation/lancements/20261020-150000
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pipeline_test.engine import Adapter, Snapshot, evaluate
from pipeline_test.registry import Exercise, discover
from pipeline_test.report import append_history, write_reports

HISTORY_PATH = Path(__file__).resolve().parent / "historique.csv"

logger = logging.getLogger("pipeline_test")


def save_snapshot(snapshot: Snapshot, folder: Path, index: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"lancement_{index:02d}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_snapshots(folder: Path) -> list[Snapshot]:
    paths = sorted(folder.glob("lancement_*.json"))
    if not paths:
        raise SystemExit(f"Aucun lancement enregistré dans {folder}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def run_agent(adapter: Adapter, runs: int, timeout: float, folder: Path) -> list[Snapshot]:
    """Relance l'agent runs fois ; un lancement en échec ou trop long est noté sur ce qu'il a produit."""
    snapshots = []
    for index in range(1, runs + 1):
        logger.info("[%s] lancement %d/%d…", adapter.name, index, runs)
        for command in adapter.run_commands:
            try:
                completed = subprocess.run(command, cwd=adapter.kit_dir, timeout=timeout, check=False)
                if completed.returncode:
                    logger.warning("[%s] lancement %d : code %d pour %s", adapter.name, index, completed.returncode, command)
            except subprocess.TimeoutExpired:
                logger.warning("[%s] lancement %d : %s interrompu après %.0f s", adapter.name, index, command, timeout)
        snapshot = adapter.collect()
        save_snapshot(snapshot, folder, index)
        snapshots.append(snapshot)
    return snapshots


def evaluate_exercise(exercise: Exercise, arguments: argparse.Namespace, stamp: str, date: str) -> float:
    adapter = exercise.adapter
    folder = exercise.runs_dir / stamp
    if arguments.rescore:
        snapshots = load_snapshots(arguments.rescore)
    elif arguments.runs:
        snapshots = run_agent(adapter, arguments.runs, arguments.timeout, folder)
    else:
        snapshots = [adapter.collect()]
        save_snapshot(snapshots[0], folder, 1)
    evaluation = evaluate(adapter, snapshots, exercise.expected())
    report = write_reports(evaluation, exercise.reports_dir, stamp, date)
    append_history(evaluation, HISTORY_PATH, date)
    logger.info("[%s] note : %s / 100 — rapport : %s", adapter.name, evaluation.total, report)
    for name, score in evaluation.groups.items():
        logger.info("  %s -> %s", name, score)
    return evaluation.total


def parse_arguments(exercises: dict[str, Exercise]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m pipeline_test", description="Note la performance des agents.")
    parser.add_argument("agents", nargs="*", help=f"Agents à noter (disponibles : {', '.join(exercises)}).")
    parser.add_argument("--all", action="store_true", help="Noter tous les exercices qui ont un dossier evaluation/.")
    parser.add_argument("--runs", type=int, default=0, help="Relancer l'agent N fois avant de noter (0 : sorties actuelles).")
    parser.add_argument("--timeout", type=float, default=1800, help="Durée maximale de chaque commande de lancement, en secondes.")
    parser.add_argument("--rescore", type=Path, help="Renoter un dossier de lancements enregistrés, sans relancer.")
    arguments = parser.parse_args()
    if arguments.all:
        arguments.agents = list(exercises)
    if not arguments.agents:
        parser.error("indiquer au moins un agent, ou --all")
    unknown = set(arguments.agents) - set(exercises)
    if unknown:
        parser.error(f"agent(s) sans dossier evaluation/ : {', '.join(sorted(unknown))}")
    if arguments.rescore and len(arguments.agents) > 1:
        parser.error("--rescore ne s'utilise qu'avec un seul agent")
    return arguments


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    exercises = discover()
    arguments = parse_arguments(exercises)
    now = datetime.now()
    stamp, date = now.strftime("%Y%m%d-%H%M%S"), now.strftime("%Y-%m-%d %H:%M")
    scores = {name: evaluate_exercise(exercises[name], arguments, stamp, date) for name in arguments.agents}
    if len(scores) > 1:
        ranking = sorted(scores.items(), key=lambda item: -item[1])
        logger.info("\nClassement :\n%s", "\n".join(f"  {name} : {score}" for name, score in ranking))


if __name__ == "__main__":
    main()
