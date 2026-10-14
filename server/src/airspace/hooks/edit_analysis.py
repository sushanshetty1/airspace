"""What a Claude Code Edit, Write or MultiEdit would do to a Python file, before it is written.

The pre hook needs three facts: which symbols the edit touches, which calls it adds (with their argument
shapes), and which signatures it changes or removes. All come from diffing the file on disk against the content
the tool call would produce, so nothing is written to find out.
"""

import difflib
from collections.abc import Iterator
from pathlib import Path

from airspace.indexer.parse import parse_module
from airspace.indexer.resolve import is_bound, resolve_target
from airspace.types import CallFact, CallSite, EditAnalysis, ModuleFacts, SignatureChange, SymbolFact


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


Site = tuple[int, tuple[str, ...], bool, bool]  # (nargs, sorted kwargs, star, bound)


def _clearance_calls(facts: ModuleFacts, universe: set[str]) -> Iterator[tuple[str, str, CallFact, bool]]:
    """(caller, callee, call, bound) for each call site, resolved more widely than the stored graph.

    The stored graph never guesses. Clearance is stricter, because a missed call lets a collision through:
    - an agent often writes a call before its import, so a bare name with a single possible target means it;
    - x.name(...) means the method `name` when exactly one method in the repo has that name (bound);
    - a call to a class is also a call to its __init__ (bound), which is what the arguments bind to.
    """
    by_name: dict[str, list[str]] = {}
    methods: dict[str, list[str]] = {}
    for q in universe:
        parent, _, name = q.rpartition(".")
        by_name.setdefault(name, []).append(q)
        if parent in universe:
            methods.setdefault(name, []).append(q)

    def pairs(caller: str, callee: str, call: CallFact, bound: bool):
        yield caller, callee, call, bound
        init = f"{callee}.__init__"
        if init in universe and init != caller:
            yield caller, init, call, True

    for c in facts.calls:
        callee = resolve_target(c.target, facts, c.caller, universe)
        if callee is not None:
            yield from pairs(c.caller, callee, c, is_bound(c))
            continue
        if "." in c.target:
            matches = methods.get(c.target.rsplit(".", 1)[1], [])
            bound = True
        else:
            matches = by_name.get(c.target, [])
            bound = False
        if len(matches) == 1 and matches[0] != c.caller:
            yield from pairs(c.caller, matches[0], c, bound)


def _clearance_sites(facts: ModuleFacts, universe: set[str]) -> dict[tuple[str, str], set[Site]]:
    """(caller, callee) -> the shapes of its call sites."""
    sites: dict[tuple[str, str], set[Site]] = {}
    for caller, callee, call, bound in _clearance_calls(facts, universe):
        sites.setdefault((caller, callee), set()).add((call.nargs, tuple(sorted(call.kwargs)), call.star, bound))
    return sites


def calls_in_file(repo_root: Path, rel: str, known: set[str]) -> list[tuple[str, str, CallSite]]:
    """(caller, callee, site) for every call in the file as it is on disk now, resolved as clearance resolves an
    edit. Empty when the file is gone or does not parse."""
    path = Path(repo_root) / rel
    if not path.is_file():
        return []
    facts = parse_module(rel, path.read_text(encoding="utf-8"))
    if facts is None:
        return []
    universe = known | {s.qualname for s in facts.symbols}
    return [
        (caller, callee, CallSite(caller, call.nargs, tuple(sorted(call.kwargs)), call.star, bound, text=call.text))
        for caller, callee, call, bound in _clearance_calls(facts, universe)
    ]


def _signature_changes(old: ModuleFacts, new: ModuleFacts) -> list[SignatureChange]:
    """Symbols whose signature differs between the two sources, and symbols the edit removes (signature "")."""
    after = {s.qualname: s.signature for s in new.symbols}
    before = {s.qualname for s in old.symbols}
    added = [s for s in new.symbols if s.qualname not in before]
    changes = []
    for s in old.symbols:
        if s.qualname not in after:
            # A rename: exactly one new symbol of the same kind, beside it, with the same parameters.
            params = s.signature[s.signature.index("("):] if "(" in s.signature else ""
            twins = [
                a for a in added
                if a.kind == s.kind and a.qualname.rsplit(".", 1)[0] == s.qualname.rsplit(".", 1)[0]
                and a.signature[a.signature.index("("):] == params
            ]
            if len(twins) == 1:
                changes.append(SignatureChange(s.qualname, s.signature, "", twins[0].qualname, twins[0].signature))
            else:
                changes.append(SignatureChange(s.qualname, s.signature, ""))
        elif after[s.qualname] != s.signature:
            changes.append(SignatureChange(s.qualname, s.signature, after[s.qualname]))
    return changes


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
    return analyze_sources(rel, current, new_source, known)


def analyze_sources(rel: str, old_source: str | None, new_source: str, known: set[str]) -> EditAnalysis:
    """What changing `rel` from `old_source` (None when the file is new) to `new_source` touches, adds and changes."""
    new = parse_module(rel, new_source)
    if new is None:
        return EditAnalysis(rel, [], [], parse_ok=False)
    # A new file, or one already broken, counts as empty: everything in it is new.
    old = parse_module(rel, old_source) if old_source is not None else None
    old_source = old_source if old is not None else ""
    old = old or _empty(rel)

    changed, deleted = _changed_lines(old_source, new_source)
    new_names = {s.qualname for s in new.symbols}
    hit = _hit(new.symbols, changed)
    # Deleted lines have no new-side line, so map them through the old spans to symbols that still exist.
    hit |= _hit(old.symbols, deleted) & new_names
    touched = [s.qualname for s in new.symbols if s.qualname in hit]

    universe = known | new_names | {s.qualname for s in old.symbols}
    # A call that exists after the edit and not before is new, wherever it sits in the file: adding an import
    # can turn an existing call into a real dependency. So is one whose shapes change: its arguments are new.
    before = _clearance_sites(old, universe)
    after = _clearance_sites(new, universe)
    new_calls = sorted(pair for pair, shapes in after.items() if before.get(pair) != shapes)
    call_shapes: dict[str, list[CallSite]] = {}
    for caller, callee in new_calls:
        for nargs, kwargs, star, bound in sorted(after[(caller, callee)]):
            call_shapes.setdefault(callee, []).append(CallSite(caller, nargs, kwargs, star, bound))
    return EditAnalysis(
        rel, touched, new_calls, parse_ok=True, call_shapes=call_shapes,
        signature_changes=_signature_changes(old, new),
    )
