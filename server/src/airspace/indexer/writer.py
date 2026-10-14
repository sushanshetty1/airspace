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


def index_facts(graph, facts_list: list[ModuleFacts], reset: bool = False) -> IndexStats:
    """Write parsed modules to the graph, as index_repo does after parsing. The hosted server indexes this way.

    reset clears the code layer (File and Symbol nodes) first, so files deleted since the last index disappear.
    A remote client sends a large repo in batches (symbols for every file first, then full facts), so calls and
    bases resolve against every symbol already in the graph as well as this batch's.
    """
    return _index(graph, facts_list, reset, known=None)


def _index(graph, facts_list: list[ModuleFacts], reset: bool, known: set[str] | None) -> IndexStats:
    """known=None resolves against the graph after this batch's symbols are written; a set resolves against it."""
    ensure_schema(graph)
    if reset:
        graph.query("MATCH (s:Symbol) DETACH DELETE s")
        graph.query("MATCH (f:File) DETACH DELETE f")
    # All nodes first, then edges, so every edge finds both ends.
    for facts in facts_list:
        _write_symbols(graph, facts)
        _delete_stale(graph, facts)
    if known is None:
        known = known_qualnames(graph)
    calls = unresolved = 0
    for facts in facts_list:
        c, u = _write_edges(graph, facts, known)
        calls += c
        unresolved += u
    return IndexStats(
        files=len(facts_list),
        symbols=sum(len(f.symbols) for f in facts_list),
        calls=calls,
        unresolved=unresolved,
    )


def index_repo(graph, repo_root: Path) -> IndexStats:
    """Index every Python file under repo_root. Unparseable files are skipped."""
    repo_root = Path(repo_root)
    # Parse everything before writing, so calls into files later in the walk still resolve.
    parsed: list[ModuleFacts] = []
    for rel in _python_files(repo_root):
        source = _read(repo_root / rel)
        facts = parse_module(rel, source) if source is not None else None
        if facts is not None:
            parsed.append(facts)
    # The whole repo is here, so calls resolve against it alone, not against symbols of files since deleted.
    return _index(graph, parsed, reset=False, known={s.qualname for f in parsed for s in f.symbols})


def reindex_facts(graph, rel: str, facts: ModuleFacts | None) -> list[SignatureChange]:
    """Bring one file's part of the graph up to date with its parsed facts, None when the file was deleted.

    Returns the signatures that changed. The facts may come from disk (reindex_file) or from a remote client.
    """
    rel = Path(rel).as_posix()
    if facts is None:
        graph.query("MATCH (s:Symbol {file: $file}) DETACH DELETE s", {"file": rel})
        graph.query("MATCH (f:File {path: $file}) DETACH DELETE f", {"file": rel})
        return []
    old = {
        q: (sig, h)
        for q, sig, h in graph.query(
            "MATCH (s:Symbol {file: $file}) RETURN s.qualname, s.signature, s.sig_hash", {"file": rel}
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


def reindex_file(graph, repo_root: Path, rel_path: str) -> list[SignatureChange]:
    """Bring one file's part of the graph up to date with disk. Returns the signatures that changed."""
    rel_path = Path(rel_path).as_posix()
    path = Path(repo_root) / rel_path
    if not path.exists():
        return reindex_facts(graph, rel_path, None)
    source = _read(path)
    facts = parse_module(rel_path, source) if source is not None else None
    if facts is None:
        # Half-written code: keep the last good picture of this file.
        return []
    return reindex_facts(graph, rel_path, facts)
