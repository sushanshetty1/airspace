"""FalkorDB access. One graph per repository."""

import hashlib
import os
from pathlib import Path

from falkordb import FalkorDB, Graph

from airspace.config import settings

# Range indexes on every property we look nodes up by.
_INDEXES = [
    ("Symbol", "qualname"),
    ("Symbol", "file"),
    ("File", "path"),
    ("Agent", "id"),
    ("Task", "id"),
    ("ContractChange", "id"),
    ("ContractChange", "qualname"),
    ("Collision", "id"),
    ("Event", "at"),
    ("Message", "id"),
    ("Sequence", "id"),
    ("Seen", "key"),
]


def connect(host: str | None = None, port: int | None = None) -> FalkorDB:
    s = settings()
    return FalkorDB(host=host or s.falkordb_host, port=port or s.falkordb_port)


def graph_name(repo_root: str | Path) -> str:
    """The repo's graph. AIRSPACE_GRAPH overrides it so agents in separate worktrees of one repo share a graph."""
    override = os.environ.get("AIRSPACE_GRAPH")
    if override:
        return override
    real = os.path.realpath(str(repo_root))
    return "airspace_" + hashlib.sha1(real.encode()).hexdigest()[:12]


def repo_graph(db: FalkorDB, repo_root: str | Path) -> Graph:
    return db.select_graph(graph_name(repo_root))


def ensure_schema(graph: Graph) -> None:
    """Create range indexes. Safe to call repeatedly."""
    existing = set()
    try:
        for row in graph.query("CALL db.indexes() YIELD label, properties RETURN label, properties").result_set:
            for prop in row[1]:
                existing.add((row[0], prop))
    except Exception:
        # A brand-new graph has no key yet; creating the first index creates it.
        pass
    for label, prop in _INDEXES:
        if (label, prop) not in existing:
            try:
                graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception as e:  # another process created it first
                if "already indexed" not in str(e).lower():
                    raise
