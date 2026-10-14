"""The grader, and proof that each task set really interferes when the caller is written against the old interface."""

import shutil
import subprocess
from pathlib import Path

import pytest

from airspace.bench.grade import classify, git, grade
from airspace.bench.tasks import load_tasks
from bench_refs import REFS

FIXTURE = Path(__file__).parent / "fixtures" / "blog"
TASKS = {t.id: t for t in load_tasks()}


def test_classify():
    assert classify(True, True, False, True) == "clean"
    assert classify(True, True, False, False) == "interference"
    assert classify(True, True, True, None) == "conflict"
    assert classify(False, True, False, True) == "task_failed"
    assert classify(True, True, False, True, error=True) == "error"


def test_six_task_sets_with_hidden_tests():
    assert len(TASKS) == 6
    for t in TASKS.values():
        assert set(t.hidden) == {"tests/test_hidden_a.py", "tests/test_hidden_b.py"}


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", "base")
    return repo


def _norm(edits):
    out: dict[str, list] = {}
    for key, change in edits.items():
        out.setdefault(key.split("#")[0], []).append(change)
    return out


def _apply_branch(repo, name, edits):
    git(repo, "checkout", "-q", "-b", name, "main")
    for rel, changes in _norm(edits).items():
        p = repo / rel
        for change in changes:
            if isinstance(change, str):
                p.write_text(change)
            else:
                old, new = change
                text = p.read_text()
                assert old in text, (rel, old)
                p.write_text(text.replace(old, new, 1))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", name)
    git(repo, "checkout", "-q", "main")


@pytest.mark.parametrize("set_id", sorted(REFS))
def test_reference_solutions_interfere(tmp_path, set_id):
    """Each set is well formed: both reference patches pass alone, and their merge fails."""
    t = TASKS[set_id]
    repo = _repo(tmp_path)
    ref_a, ref_b = REFS[set_id]
    _apply_branch(repo, "a", ref_a)
    _apply_branch(repo, "b", ref_b)
    g = grade(repo, "a", "b", t.hidden_a, t.hidden_b)
    assert g.outcome == "interference", g
