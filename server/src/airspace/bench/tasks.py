"""Benchmark task sets: one task changes a helper's interface, the other adds a caller written against the old one."""

import json
from dataclasses import dataclass
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parents[3] / "bench" / "tasks"


@dataclass(frozen=True)
class TaskSet:
    id: str
    kind: str  # signature | rename | constructor | behaviour
    a: str
    b: str
    hidden: dict[str, str]  # path -> test source; tests/test_hidden_a.py and tests/test_hidden_b.py

    @property
    def hidden_a(self) -> dict[str, str]:
        return {p: s for p, s in self.hidden.items() if p.endswith("_a.py")}

    @property
    def hidden_b(self) -> dict[str, str]:
        return {p: s for p, s in self.hidden.items() if p.endswith("_b.py")}


def load_tasks(directory: Path = TASK_DIR) -> list[TaskSet]:
    sets = []
    for path in sorted(directory.glob("*.json")):
        d = json.loads(path.read_text())
        sets.append(TaskSet(id=d["id"], kind=d["kind"], a=d["a"], b=d["b"], hidden=d["hidden"]))
    return sets
