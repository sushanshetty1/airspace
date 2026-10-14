"""ModuleFacts to the graph. Whole-repo indexing and the single-file re-index the post hook runs after each edit.

Every write is a MERGE keyed on File.path or Symbol.qualname, so running twice gives the same graph.
Symbols are matched by qualname, which is why edges from other files survive a re-index of this one.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from airspace.graph.db import ensure_schema
from airspace.indexer.parse import parse_module
from airspace.indexer.resolve import resolve_calls, resolve_shapes, resolve_target
from airspace.types import ModuleFacts, SignatureChange

SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", "build", "dist"}


@dataclass
class IndexStats:
    files: int
    symbols: int
    calls: int
    unresolved: int


def _python_files(repo_root: Path) -> list[str]:
    """Repo-relative POSIX paths of every .py file, skipping hidden, virtualenv and build directories."""
    found = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                found.append(Path(dirpath, name).relative_to(repo_root).as_posix())
    return found


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _write_symbols(graph, facts: ModuleFacts) -> None:
    rows = [
        {"q": s.qualname, "name": s.name, "kind": s.kind, "lineno": s.lineno, "end": s.end_lineno,
         "sig": s.signature, "hash": s.sig_hash, "is_test": s.is_test}
        for s in facts.symbols
    ]
    graph.query("MERGE (:File {path: $file})", {"file": facts.file})
    if rows:
        graph.query(
            """MATCH (f:File {path: $file})
            UNWIND $rows AS r
            MERGE (s:Symbol {qualname: r.q})
            SET s.name = r.name, s.kind = r.kind, s.file = $file, s.lineno = r.lineno, s.end_lineno = r.end,
                s.signature = r.sig, s.sig_hash = r.hash, s.is_test = r.is_test
            MERGE (f)-[:DEFINES]->(s)""",
            {"file": facts.file, "rows": rows},
        )


def _write_edges(graph, facts: ModuleFacts, known: set[str]) -> tuple[int, int]:
    """Replace this file's outgoing CALLS, COVERS and INHERITS. Returns (resolved pairs, unresolved calls)."""
    graph.query(
        "MATCH (s:Symbol {file: $file})-[r:CALLS|COVERS|INHERITS]->() DELETE r",
        {"file": facts.file},
    )
    tests = {s.qualname for s in facts.symbols if s.is_test}
    pairs = resolve_calls(facts, known)
    shapes = resolve_shapes(facts, known)
    unresolved = sum(1 for c in facts.calls if resolve_target(c.target, facts, c.caller, known) is None)
    # A test calling code is coverage, not a dependency the code has. Each call edge carries its call shapes.
    calls = {
        "CALLS": [[a, b, sorted(shapes[(a, b)])] for a, b in pairs if a not in tests],
        "COVERS": [[a, b, sorted(shapes[(a, b)])] for a, b in pairs if a in tests],
    }
    for rel, rows in calls.items():
        if rows:
            graph.query(
                f"""UNWIND $rows AS p
                MATCH (a:Symbol {{qualname: p[0]}}), (b:Symbol {{qualname: p[1]}})
                MERGE (a)-[r:{rel}]->(b)
                SET r.shapes = p[2]""",
                {"rows": rows},
            )
    inherits = []
    for cls, base in facts.bases:
        target = resolve_target(base, facts, cls, known)
        if target is not None:
            inherits.append([cls, target])
    if inherits:
        graph.query(
            """UNWIND $rows AS p
            MATCH (a:Symbol {qualname: p[0]}), (b:Symbol {qualname: p[1]})
            MERGE (a)-[:INHERITS]->(b)""",
            {"rows": inherits},
        )
    return len(pairs), unresolved


def _delete_stale(graph, facts: ModuleFacts) -> None:
    graph.query(
        "MATCH (s:Symbol {file: $file}) WHERE NOT s.qualname IN $keep DETACH DELETE s",
        {"file": facts.file, "keep": [s.qualname for s in facts.symbols]},
    )


def known_qualnames(graph) -> set[str]:
    return {row[0] for row in graph.query("MATCH (s:Symbol) RETURN s.qualname").result_set}


def index_repo(graph, repo_root: Path) -> IndexStats:
    """Index every Python file under repo_root. Unparseable files are skipped."""
    repo_root = Path(repo_root)
    ensure_schema(graph)
    # Pass 1: parse everything so calls into files later in the walk still resolve.
    parsed: list[ModuleFacts] = []
    for rel in _python_files(repo_root):
        source = _read(repo_root / rel)
        facts = parse_module(rel, source) if source is not None else None
        if facts is not None:
            parsed.append(facts)
    known = {s.qualname for f in parsed for s in f.symbols}
    # Pass 2: all nodes first, then edges, so every edge finds both ends.
    for facts in parsed:
        _write_symbols(graph, facts)
        _delete_stale(graph, facts)
    calls = unresolved = 0
    for facts in parsed:
        c, u = _write_edges(graph, facts, known)
        calls += c
        unresolved += u
    return IndexStats(
        files=len(parsed),
        symbols=sum(len(f.symbols) for f in parsed),
        calls=calls,
        unresolved=unresolved,
    )


def reindex_file(graph, repo_root: Path, rel_path: str) -> list[SignatureChange]:
    """Bring one file's part of the graph up to date with disk. Returns the signatures that changed."""
    rel_path = Path(rel_path).as_posix()
    path = Path(repo_root) / rel_path
    if not path.exists():
        graph.query("MATCH (s:Symbol {file: $file}) DETACH DELETE s", {"file": rel_path})
        graph.query("MATCH (f:File {path: $file}) DETACH DELETE f", {"file": rel_path})
        return []
    source = _read(path)
    facts = parse_module(rel_path, source) if source is not None else None
    if facts is None:
        # Half-written code: keep the last good picture of this file.
        return []

    old = {
        q: (sig, h)
        for q, sig, h in graph.query(
            "MATCH (s:Symbol {file: $file}) RETURN s.qualname, s.signature, s.sig_hash", {"file": rel_path}
        ).result_set
    }
    changes = [
        SignatureChange(s.qualname, old[s.qualname][0], s.signature)
        for s in facts.symbols
        if s.qualname in old and old[s.qualname][1] != s.sig_hash
    ]
    known = known_qualnames(graph) | {s.qualname for s in facts.symbols}
    _write_symbols(graph, facts)
    _delete_stale(graph, facts)
    _write_edges(graph, facts, known)
    return changes
