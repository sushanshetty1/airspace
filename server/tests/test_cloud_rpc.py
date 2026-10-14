import json
from dataclasses import replace

import pytest
from cloud_helpers import (  # noqa: F401 (fixtures)
    WRITE,
    app_client,
    client,
    cloud,
    github,
    make_cloud,
    new_workspace,
    sign_in,
)
from conftest import FIXTURE_REPO

from airspace import wire
from airspace.cloud.rpc import ENGINE_METHODS, RpcError, dispatch
from airspace.indexer.parse import parse_module
from airspace.indexer.writer import _python_files, index_repo
from airspace.types import ModuleFacts, SignatureChange, Verdict


def blog_facts() -> list[ModuleFacts]:
    facts = [parse_module(rel, (FIXTURE_REPO / rel).read_text()) for rel in _python_files(FIXTURE_REPO)]
    return [f for f in facts if f is not None]


class Remote:
    """A key-holding client, like the remote hooks."""

    def __init__(self, client, key):
        self.client, self.key = client, key

    def post(self, body, **kw):
        return self.client.post("/api/rpc", headers={"Authorization": f"Bearer {self.key}"}, **kw,
                                **({"json": body} if body is not None else {}))

    def call(self, method, *args, **kwargs):
        r = self.post({"method": method, "args": wire.encode(list(args)), "kwargs": wire.encode(kwargs)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        return wire.decode(body["result"])


@pytest.fixture
def workspace(client, cloud):
    sign_in(client, cloud)
    return new_workspace(client, cloud)


@pytest.fixture
def remote(client, workspace):
    return Remote(client, workspace[1])


def test_bad_key(client, workspace):
    for auth in (None, "Bearer", "Basic abc", "Bearer ask_" + "0" * 40, "Bearer not-a-key"):
        headers = {"Authorization": auth} if auth else {}
        r = client.post("/api/rpc", json={"method": "graph.known"}, headers=headers)
        assert r.status_code == 401, auth
        assert r.json()["ok"] is False
        assert "X-Airspace-Workspace" not in r.headers


def test_unknown_and_disallowed_methods(remote, workspace):
    for method in ("nope", "pause", "message", "release_collision", "seen_source", "_q", "graph.delete", "__init__"):
        r = remote.post({"method": method, "args": []})
        assert r.status_code == 400, method
        assert r.json() == {"ok": False, "error": f"Unknown method {method}."}
        assert r.headers["X-Airspace-Workspace"] == workspace[0]


def test_bad_bodies(remote):
    assert remote.post(None, content=b"{not json").status_code == 400
    assert remote.post([1, 2]).status_code == 400
    assert remote.post({"method": "agent_of", "args": "x"}).status_code == 400
    r = remote.post({"method": "agent_of", "args": [], "kwargs": {}})
    assert r.status_code == 400 and "Bad arguments for agent_of" in r.json()["error"]
    assert remote.post({"method": "agent_of", "args": ["t"], "kwargs": {"nope": 1}}).status_code == 400
    assert remote.post({"method": "agent_of", "args": [{"__t": "NotAType"}]}).status_code == 400


def test_engine_calls(remote, workspace):
    stats = remote.call("graph.index", blog_facts(), True)
    assert stats["files"] > 0 and stats["symbols"] > 0
    assert remote.call("ensure_task", "agent-a", "task-a", intent="change slugify") is None
    assert remote.call("agent_of", "task-a") == "agent-a"
    assert remote.call("claim", "task-a", ["utils.text.slugify"]) == ["utils.text.slugify"]
    verdict = remote.call("check_edit", "task-a", ["utils.text.slugify"], [])
    assert isinstance(verdict, Verdict)
    assert verdict.kind == "cleared"

    # Another agent's new call into the contract agent-a is changing is held, with the path.
    remote.call("record_changes", "task-a", [SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)",
                                                            "slugify(value, *, unicode=False)")])
    remote.call("ensure_task", "agent-b", "task-b")
    held = remote.call("check_edit", "task-b", ["blog.views.render_post"],
                       [("blog.views.render_post", "utils.text.slugify")])
    assert isinstance(held, Verdict) and held.kind == "hold"
    assert held.other_agent == "agent-a"
    assert "agent-a" in [a["id"] for a in remote.call("state")["agents"]]


def test_graph_index_known_and_write_file_round_trip(remote, workspace):
    facts = blog_facts()
    stats = remote.call("graph.index", facts, False)
    assert stats == {"files": len(facts), "symbols": sum(len(f.symbols) for f in facts),
                     "calls": stats["calls"], "unresolved": stats["unresolved"]}
    assert stats["calls"] > 0
    known = remote.call("graph.known")
    assert known == sorted({s.qualname for f in facts for s in f.symbols})

    rel = "utils/text.py"
    source = (FIXTURE_REPO / rel).read_text().replace("def slugify(value, allow_unicode=False)",
                                                      "def slugify(value, *, unicode=False)")
    changed = parse_module(rel, source)
    changes = remote.call("graph.write_file", rel, changed)
    assert changes == [SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)",
                                       "slugify(value, *, unicode=False)")]
    # Writing the same facts again changes nothing.
    assert remote.call("graph.write_file", rel, changed) == []

    # Deleted: the file's symbols leave the graph.
    assert remote.call("graph.write_file", rel, None) == []
    known = remote.call("graph.known")
    assert "utils.text.slugify" not in known and "blog.views.render_post" in known

    # A reset index brings back exactly the repo.
    remote.call("graph.index", facts, True)
    assert remote.call("graph.known") == sorted({s.qualname for f in facts for s in f.symbols})


def test_graph_write_file_checks_its_input(remote):
    facts = blog_facts()[0]
    bad = [
        [facts.file],
        ["", None],
        ["other.py", facts],
        [facts.file, {"not": "facts"}],
    ]
    for args in bad:
        r = remote.post({"method": "graph.write_file", "args": wire.encode(args)})
        assert r.status_code == 400, args
    r = remote.post({"method": "graph.index", "args": [["x"], False]})
    assert r.status_code == 400


def test_known_includes_removed_symbols(remote):
    remote.call("graph.index", blog_facts(), True)
    remote.call("ensure_task", "agent-a", "task-a")
    remote.call("record_changes", "task-a", [SignatureChange("utils.text.gone", "gone()", "")])
    assert "utils.text.gone" in remote.call("graph.known")


def test_workspace_header_on_success(remote, workspace):
    r = remote.post({"method": "graph.known"})
    assert r.status_code == 200
    assert r.headers["X-Airspace-Workspace"] == workspace[0]


def test_workspaces_are_isolated(client, cloud, remote):
    remote.call("ensure_task", "agent-a", "task-a")
    _, other_key = new_workspace(client, cloud, "second")
    other = Remote(client, other_key)
    assert other.call("agent_of", "task-a") is None
    assert other.call("state")["agents"] == []


def test_rate_limit(make_cloud):
    cloud = make_cloud(rpc_per_minute=3)
    c = app_client(cloud)
    sign_in(c, cloud)
    wid, key = new_workspace(c, cloud)
    remote = Remote(c, key)
    for _ in range(3):
        assert remote.post({"method": "graph.known"}).status_code == 200
    r = remote.post({"method": "graph.known"})
    assert r.status_code == 429
    assert r.json()["ok"] is False
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-Airspace-Workspace"] == wid


def test_body_too_large(make_cloud):
    cloud = make_cloud(rpc_max_bytes=1000)
    c = app_client(cloud)
    sign_in(c, cloud)
    wid, key = new_workspace(c, cloud)
    remote = Remote(c, key)
    big = {"method": "graph.known", "args": [], "kwargs": {}, "pad": "x" * 2000}
    r = remote.post(big)
    assert r.status_code == 413
    assert r.json()["ok"] is False
    # Without a Content-Length the limit holds while reading.
    chunks = iter([json.dumps(big).encode()[:900], json.dumps(big).encode()[900:]])
    r = remote.post(None, content=chunks)
    assert r.status_code == 413
    assert r.headers["X-Airspace-Workspace"] == wid
    assert remote.post({"method": "graph.known"}).status_code == 200


def test_default_body_limit_is_2_mb(cloud):
    assert cloud.rpc_max_bytes == 2 * 1024 * 1024
    assert cloud.rpc_per_minute == 1200


def test_dispatch_directly(cloud, client, workspace):
    air = cloud.engine(workspace[0])
    assert dispatch(air, air.graph, "graph.known", [], {}) == []
    assert dispatch(air, air.graph, "ensure_task", ["a", "t"], {}) is None
    assert dispatch(air, air.graph, "agent_of", ["t"], {}) == "a"
    with pytest.raises(RpcError):
        dispatch(air, air.graph, "pause", ["a"], {})
    assert "check_edit" in ENGINE_METHODS and "pause" not in ENGINE_METHODS


# Batched indexing, as the remote client sends a large repo


def _edges(graph) -> list:
    return sorted(graph.query(
        "MATCH (a:Symbol)-[r:CALLS|COVERS|INHERITS]->(b:Symbol) RETURN type(r), a.qualname, b.qualname, r.shapes"
    ).result_set, key=repr)


def test_batched_index_resolves_across_batches(cloud, remote, workspace, graph):
    """Symbols for every file in batches (reset on the first), then the full facts in batches."""
    facts = blog_facts()
    callee_file = "utils/text.py"
    # Batch 1 holds the file that defines slugify; batch 2 holds its callers.
    first = [f for f in facts if f.file == callee_file]
    second = [f for f in facts if f.file != callee_file]
    assert any(c.target.endswith("slugify") for f in second for c in f.calls)

    symbols_only = [replace(f, calls=[], bases=[]) for f in facts]
    remote.call("graph.index", [f for f in symbols_only if f.file == callee_file], True)
    remote.call("graph.index", [f for f in symbols_only if f.file != callee_file], False)
    remote.call("graph.index", first, False)
    stats = remote.call("graph.index", second, False)
    assert stats["calls"] > 0

    ws_graph = cloud.engine(workspace[0]).graph
    assert ["CALLS", "blog.models.Post.save", "utils.text.slugify"] in [e[:3] for e in _edges(ws_graph)]
    index_repo(graph, FIXTURE_REPO)
    assert _edges(ws_graph) == _edges(graph)

    # Sending the full facts again leaves the edges as they are.
    remote.call("graph.index", second, False)
    assert _edges(ws_graph) == _edges(graph)


def test_two_call_index_where_batch_two_calls_into_batch_one(remote):
    facts = blog_facts()
    defines = [f for f in facts if f.file == "utils/text.py"]
    callers = [f for f in facts if f.file == "blog/models.py"]
    remote.call("graph.index", defines, True)
    stats = remote.call("graph.index", callers, False)
    assert stats["files"] == 1 and stats["calls"] >= 1
    assert remote.call("explain", "blog.models.Post.save", "utils.text.slugify") == [
        "blog.models.Post.save", "utils.text.slugify"]


def test_empty_repo_index(remote):
    remote.call("graph.index", blog_facts(), True)
    assert remote.call("graph.index", [], True) == {"files": 0, "symbols": 0, "calls": 0, "unresolved": 0}
    assert remote.call("graph.known") == []
