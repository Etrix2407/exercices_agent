"""Pipeline de notation des agents.

Usage (depuis exercices/avance) :
    python -m pipeline_test e07                  # note les sorties actuelles de l'agent
    python -m pipeline_test e07 --runs 5         # relance l'agent 5 fois (avec --reset) puis note
    python -m pipeline_test --all --runs 3       # tous les agents qui ont un adaptateur
    python -m pipeline_test e07 --rescore pipeline_test/lancements/e07_20261020-1500
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pipeline_test.engine import Adapter, Snapshot, evaluate
from pipeline_test.report import append_history, write_reports

HERE = Path(__file__).resolve().parent
ADAPTERS_DIR = HERE / "adapters"
EXPECTED_DIR = HERE / "attendus"
RUNS_DIR = HERE / "lancements"
REPORTS_DIR = HERE / "rapports"
HISTORY_PATH = REPORTS_DIR / "historique.csv"

logger = logging.getLogger("pipeline_test")


def available_agents() -> list[str]:
    return sorted(path.stem for path in ADAPTERS_DIR.glob("*.py") if not path.stem.startswith("_"))


def load_adapter(name: str) -> Adapter:
    return importlib.import_module(f"pipeline_test.adapters.{name}").ADAPTER


def load_expected(name: str) -> dict:
    path = EXPECTED_DIR / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"Réponses attendues absentes : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


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
        try:
            completed = subprocess.run(adapter.run_command, cwd=adapter.kit_dir, timeout=timeout, check=False)
            if completed.returncode:
                logger.warning("[%s] lancement %d terminé avec le code %d", adapter.name, index, completed.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("[%s] lancement %d interrompu après %.0f s", adapter.name, index, timeout)
        snapshot = adapter.collect()
        save_snapshot(snapshot, folder, index)
        snapshots.append(snapshot)
    return snapshots


def evaluate_agent(name: str, arguments: argparse.Namespace, stamp: str, date: str) -> float:
    adapter = load_adapter(name)
    expected = load_expected(name)
    folder = RUNS_DIR / f"{name}_{stamp}"
    if arguments.rescore:
        snapshots = load_snapshots(arguments.rescore)
    elif arguments.runs:
        snapshots = run_agent(adapter, arguments.runs, arguments.timeout, folder)
    else:
        snapshots = [adapter.collect()]
        save_snapshot(snapshots[0], folder, 1)
    evaluation = evaluate(adapter, snapshots, expected)
    report = write_reports(evaluation, REPORTS_DIR, stamp, date)
    append_history(evaluation, HISTORY_PATH, date)
    logger.info("[%s] note : %s / 100 — rapport : %s", name, evaluation.total, report)
    return evaluation.total


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m pipeline_test", description="Note la performance des agents.")
    parser.add_argument("agents", nargs="*", help=f"Agents à noter (disponibles : {', '.join(available_agents())}).")
    parser.add_argument("--all", action="store_true", help="Noter tous les agents qui ont un adaptateur.")
    parser.add_argument("--runs", type=int, default=0, help="Relancer l'agent N fois avant de noter (0 : sorties actuelles).")
    parser.add_argument("--timeout", type=float, default=1800, help="Durée maximale d'un lancement, en secondes.")
    parser.add_argument("--rescore", type=Path, help="Renoter un dossier de lancements enregistrés, sans relancer.")
    arguments = parser.parse_args()
    if arguments.all:
        arguments.agents = available_agents()
    if not arguments.agents:
        parser.error("indiquer au moins un agent, ou --all")
    unknown = set(arguments.agents) - set(available_agents())
    if unknown:
        parser.error(f"agent(s) sans adaptateur : {', '.join(sorted(unknown))}")
    if arguments.rescore and len(arguments.agents) > 1:
        parser.error("--rescore ne s'utilise qu'avec un seul agent")
    return arguments


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    arguments = parse_arguments()
    now = datetime.now()
    stamp, date = now.strftime("%Y%m%d-%H%M%S"), now.strftime("%Y-%m-%d %H:%M")
    scores = {name: evaluate_agent(name, arguments, stamp, date) for name in arguments.agents}
    if len(scores) > 1:
        logger.info("\nClassement :\n%s", "\n".join(f"  {name} : {score}" for name, score in sorted(scores.items(), key=lambda item: -item[1])))


if __name__ == "__main__":
    main()
