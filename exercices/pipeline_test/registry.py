"""Découverte des exercices notables : chaque exercice qui a un dossier evaluation/ avec adapter.py.

Partie propre à un exercice (dans <exercice>/evaluation/) :
    adapter.py      expose ADAPTER (voir engine.Adapter)
    attendus.json   réponses attendues
    rapports/       rapports de cet exercice
    lancements/     instantanés de chaque lancement (ignorés par git)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pipeline_test.collectors import load_module
from pipeline_test.engine import Adapter

EXERCISES_DIR = Path(__file__).resolve().parents[1]
# Profondeurs possibles : exercices/<exercice>/ ou exercices/<niveau>/<exercice>/.
ADAPTER_PATTERNS = ("*/evaluation/adapter.py", "*/*/evaluation/adapter.py")


@dataclass(frozen=True)
class Exercise:
    adapter: Adapter
    folder: Path

    @property
    def reports_dir(self) -> Path:
        return self.folder / "rapports"

    @property
    def runs_dir(self) -> Path:
        return self.folder / "lancements"

    def expected(self) -> dict:
        path = self.folder / "attendus.json"
        if not path.is_file():
            raise FileNotFoundError(f"Réponses attendues absentes : {path}")
        return json.loads(path.read_text(encoding="utf-8"))


def discover() -> dict[str, Exercise]:
    """{nom de l'agent: exercice} pour chaque evaluation/adapter.py trouvé sous exercices/."""
    found: dict[str, Exercise] = {}
    for pattern in ADAPTER_PATTERNS:
        for path in sorted(EXERCISES_DIR.glob(pattern)):
            relative = path.parent.parent.relative_to(EXERCISES_DIR).as_posix()
            module = load_module(path, "evaluation_" + re.sub(r"\W", "_", relative))
            adapter: Adapter = module.ADAPTER
            if adapter.name in found:
                raise ValueError(f"Deux adaptateurs portent le nom « {adapter.name} » : {found[adapter.name].folder} et {path.parent}")
            found[adapter.name] = Exercise(adapter, path.parent)
    return dict(sorted(found.items()))
