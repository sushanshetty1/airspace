"""Writes made outside the edit tools: a shell redirect, `sed -i`, a script, a formatter.

The edit hooks see every Edit, Write and MultiEdit before it lands. A file written any other way reaches the graph
here instead. After each shell command, and before landing, every Python file git reports as changed is compared
with the version Airspace last saw in this working copy (git HEAD when it has seen none). A difference is analysed
like an edit: the file is reindexed, the changed symbols are claimed by the task whose command ran, and contract
changes are recorded. The write has already happened, so a conflict cannot be held back; it is reported instead.
"""

import os
import subprocess
from pathlib import Path

from airspace.types import EditAnalysis

# A file changed this long before a task with no start time still counts as its own.
UNSTARTED_WINDOW_SECONDS = 900.0
# A clock skew allowance between the file system and the graph's clock.
_SLACK_SECONDS = 2.0


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)


def changed_python_files(root: Path) -> list[str]:
    """Repo-relative paths of Python files that differ from HEAD, untracked ones included. Empty outside git."""
    try:
        out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    entries = out.stdout.decode("utf-8", "replace").split("\0")
    files: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            i += 1  # the original path follows a rename or copy
        if path.endswith(".py"):
            files.append(path)
    return sorted(set(files))


def head_source(root: Path, rel: str) -> str | None:
    """The file as committed at HEAD, or None when it is new."""
    try:
        out = _git(root, "show", f"HEAD:{rel}")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


def scope_of(root: Path) -> str:
    return os.path.realpath(root)


def _current(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""  # deleted: everything it defined is gone
    except (OSError, UnicodeDecodeError):
        return None


def _since(airspace, task: str, now: float) -> float:
    started = airspace.started_at(task)
    return (started if started is not None else now - UNSTARTED_WINDOW_SECONDS) - _SLACK_SECONDS


def reconcile(root: Path, agent: str, task: str, airspace, deps, now: float) -> list[str]:
    """Bring files written outside the edit tools into the graph as edits by `task`. Returns hold reasons."""
    root = Path(root)
    scope = scope_of(root)
    since = None
    known = None
    reasons: list[str] = []
    for rel in changed_python_files(root):
        path = root / rel
        current = _current(path)
        if current is None:
            continue
        base = airspace.seen_source(scope, rel)
        if base is None:
            # Changes from before this task started are someone else's (the developer's own work in progress).
            if since is None:
                since = _since(airspace, task, now)
            if path.exists() and path.stat().st_mtime < since:
                continue
            base = head_source(root, rel)
        if base == current or (base is None and current == ""):
            continue
        if known is None:
            known = deps.known(root)
        from airspace.hooks.edit_analysis import analyze_sources

        analysis: EditAnalysis = analyze_sources(rel, base, current, known)
        if not analysis.parse_ok:
            continue  # half-written: keep the last good picture and look again next time
        airspace.note_seen(scope, rel, current)
        changes = analysis.signature_changes
        if not analysis.touched and not analysis.new_calls and not changes:
            continue
        removed = [c.qualname for c in changes if not c.new_signature and c.qualname not in analysis.touched]
        airspace.ensure_task(agent, task)
        verdict = airspace.check_edit(task, analysis.touched + removed, analysis.new_calls, analysis.call_shapes)
        deps.reindex(root, rel)
        airspace.claim_pending(task)
        if changes:
            airspace.record_changes(task, changes)
        airspace.record_edited_file(task, rel)
        if verdict.kind == "hold":
            # Held code is still on disk, so it is the task's own for the landing check.
            airspace.note_touched(task, analysis.touched)
            reasons.append(f"{rel} was written outside the edit tools. {verdict.reason}")
    return reasons
