"""What a Claude Code Edit, Write or MultiEdit would do to a Python file, before it is written.

The pre hook needs two facts: which symbols the edit touches, and which calls it adds. Both come from
diffing the file on disk against the content the tool call would produce, so nothing is written to find out.
"""

import difflib
from pathlib import Path

from airspace.indexer.parse import parse_module
from airspace.indexer.resolve import resolve_calls
from airspace.types import EditAnalysis, ModuleFacts, SymbolFact


def _replace(current: str, edit: dict) -> str | None:
    old, new = edit.get("old_string"), edit.get("new_string")
    if old is None or new is None or old not in current:
        return None
    return current.replace(old, new) if edit.get("replace_all") else current.replace(old, new, 1)


def apply_tool_input(tool_name: str, tool_input: dict, current: str | None) -> str | None:
    """The file content after the tool call, or None when the call does not apply to `current`."""
    if tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if current is None:
        return None
    if tool_name == "Edit":
        return _replace(current, tool_input)
    if tool_name == "MultiEdit":
        for edit in tool_input.get("edits") or []:
            current = _replace(current, edit)
            if current is None:
                return None
        return current
    return None


def _repo_relative(repo_root: Path, file_path: str) -> str | None:
    path = Path(file_path)
    if not path.is_absolute():
        path = repo_root / path
    # resolve() on both sides so /var and /private/var (macOS) compare equal.
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    return rel.as_posix()


def _changed_lines(old: str, new: str) -> tuple[set[int], set[int]]:
    """(1-based new-file lines that differ, 1-based old-file lines deleted outright)."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    changed: set[int] = set()
    deleted: set[int] = set()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            changed.update(range(j1 + 1, j2 + 1))
        elif tag == "delete":
            deleted.update(range(i1 + 1, i2 + 1))
    return changed, deleted


def _hit(symbols: list[SymbolFact], lines: set[int]) -> set[str]:
    """Symbols whose span holds one of `lines`. A line inside a method counts for the method, not its class."""
    methods = [s for s in symbols if s.kind == "method"]
    hit: set[str] = set()
    for s in symbols:
        own = {n for n in lines if s.lineno <= n <= s.end_lineno}
        if s.kind == "class":
            for m in methods:
                if m.qualname.rsplit(".", 1)[0] == s.qualname:
                    own -= set(range(m.lineno, m.end_lineno + 1))
        if own:
            hit.add(s.qualname)
    return hit


def _empty(rel: str) -> ModuleFacts:
    return ModuleFacts(module="", file=rel, symbols=[], calls=[], imports={}, bases=[])


def analyze_edit(repo_root: Path, tool_name: str, tool_input: dict, known: set[str]) -> EditAnalysis | None:
    repo_root = Path(repo_root)
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return None
    rel = _repo_relative(repo_root, file_path)
    if rel is None:
        return None
    path = repo_root / rel
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    new_source = apply_tool_input(tool_name, tool_input, current)
    if new_source is None:
        return None

    new = parse_module(rel, new_source)
    if new is None:
        return EditAnalysis(rel, [], [], parse_ok=False)
    # A new file, or one already broken on disk, counts as empty: everything in it is new.
    old = parse_module(rel, current) if current is not None else None
    old_source = current if old is not None else ""
    old = old or _empty(rel)

    changed, deleted = _changed_lines(old_source, new_source)
    new_names = {s.qualname for s in new.symbols}
    hit = _hit(new.symbols, changed)
    # Deleted lines have no new-side line, so map them through the old spans to symbols that still exist.
    hit |= _hit(old.symbols, deleted) & new_names
    touched = [s.qualname for s in new.symbols if s.qualname in hit]

    universe = known | new_names | {s.qualname for s in old.symbols}
    before = set(resolve_calls(old, universe))
    in_touched = set(touched)
    new_calls = [p for p in resolve_calls(new, universe) if p[0] in in_touched and p not in before]
    return EditAnalysis(rel, touched, new_calls, parse_ok=True)
