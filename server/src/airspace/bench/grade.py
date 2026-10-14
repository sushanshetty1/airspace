"""Grading, after the method in Passes Alone, Fails Together (arXiv 2609.25396).

Each patch is tested alone with its own hidden test, then the merge is tested with both. Only failures the
merge itself causes count as interference.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OUTCOMES = ("clean", "interference", "conflict", "task_failed", "error")


@dataclass
class Grade:
    outcome: str
    a_alone: bool | None
    b_alone: bool | None
    merged: bool | None
    detail: str = ""


def classify(a_alone: bool | None, b_alone: bool | None, conflict: bool, merged: bool | None, error: bool = False) -> str:
    if error:
        return "error"
    if not a_alone or not b_alone:
        return "task_failed"
    if conflict:
        return "conflict"
    return "clean" if merged else "interference"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def run_tests(repo: Path, hidden: dict[str, str], python: str = sys.executable, timeout: int = 120) -> tuple[bool, str]:
    """Write the hidden tests into `repo`, run the whole suite, then remove them again."""
    written = []
    for rel, src in hidden.items():
        p = repo / rel
        p.write_text(src)
        written.append(p)
    try:
        r = subprocess.run(
            [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(repo), "tests"],
            cwd=repo, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return False, "tests timed out"
    finally:
        for p in written:
            p.unlink(missing_ok=True)


def grade(repo: Path, branch_a: str, branch_b: str, hidden_a: dict[str, str], hidden_b: dict[str, str], python: str = sys.executable) -> Grade:
    """Grade two branches of `repo` (a git repository whose worktree is free to check out)."""
    git(repo, "checkout", "-q", branch_a)
    a_ok, a_log = run_tests(repo, hidden_a, python)
    git(repo, "checkout", "-q", branch_b)
    b_ok, b_log = run_tests(repo, hidden_b, python)

    git(repo, "checkout", "-q", "-B", "merged", branch_a)
    merge = git(repo, "merge", "--no-edit", "-q", branch_b, check=False)
    if merge.returncode != 0:
        git(repo, "merge", "--abort", check=False)
        return Grade(classify(a_ok, b_ok, True, None), a_ok, b_ok, None, merge.stdout + merge.stderr)
    m_ok, m_log = run_tests(repo, {**hidden_a, **hidden_b}, python)
    detail = m_log if not m_ok else ""
    if not (a_ok and b_ok):
        detail = (a_log if not a_ok else "") + (b_log if not b_ok else "")
    return Grade(classify(a_ok, b_ok, False, m_ok), a_ok, b_ok, m_ok, detail)
