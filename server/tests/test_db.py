from airspace.graph.db import ensure_schema, graph_name
from helpers import BLOG_SYMBOLS, seed_blog_graph


def test_graph_name_is_stable_and_prefixed(tmp_path):
    assert graph_name(tmp_path) == graph_name(str(tmp_path))
    assert graph_name(tmp_path).startswith("airspace_")
    assert len(graph_name(tmp_path)) == len("airspace_") + 12


def test_ensure_schema_is_idempotent(graph):
    ensure_schema(graph)
    ensure_schema(graph)
    rows = graph.query("CALL db.indexes() YIELD label RETURN count(label)").result_set
    assert rows[0][0] >= 5


def test_contract_changes_are_indexed_by_qualname(graph):
    # Clearance looks changes up by qualname, since a removed symbol has no node to start from.
    rows = graph.query("CALL db.indexes() YIELD label, properties RETURN label, properties").result_set
    assert any(label == "ContractChange" and "qualname" in props for label, props in rows)


def test_seed_blog_graph(graph):
    seed_blog_graph(graph)
    count = graph.query("MATCH (s:Symbol) RETURN count(s)").result_set[0][0]
    assert count == len(BLOG_SYMBOLS) == 17
    edge = graph.query(
        "MATCH (:Symbol {qualname: 'blog.models.Post.save'})-[r:CALLS]->(:Symbol {qualname: 'utils.text.slugify'}) RETURN count(r)"
    ).result_set[0][0]
    assert edge == 1


def test_graph_override_shares_graph_across_worktrees(tmp_path, monkeypatch):
    a, b = tmp_path / "wa", tmp_path / "wb"
    assert graph_name(a) != graph_name(b)
    monkeypatch.setenv("AIRSPACE_GRAPH", "bench_shared")
    assert graph_name(a) == graph_name(b) == "bench_shared"
