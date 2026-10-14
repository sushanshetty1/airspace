"""Remote mode: the hooks, `airspace connect`, `index` and `status` against a hosted server, end to end.

The server here is a small stand-in for /api/rpc that follows the RPC contract in the accounts and workspaces plan:
a Bearer key per workspace, the method allowlist, wire values both ways, the graph methods written with the
indexer's own writer, and the X-Airspace-Workspace header. It runs the real engine on a real FalkorDB graph, behind
a real HTTP socket, so the hooks reach it exactly as they would reach the hosted one.
"""

import json
import os
import re
import socket
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from airspace import cli
from airspace.admission.engine import Airspace, removed_qualnames
from airspace.graph.db import ensure_schema, graph_name
from airspace.hooks.handlers import default_deps, handle_any, handle_post, handle_pre, handle_stop
from airspace.indexer import writer
from airspace.indexer.writer import index_repo, known_qualnames
from airspace.remote import (
    Remote,
    RemoteAirspace,
    RemoteError,
    RpcClient,
    load_remotes,
    remote_for,
    remote_index,
    remote_reindex,
    remotes_path,
    remove_remote,
    seen_dir,
    set_remote,
)
from airspace.wire import decode, encode
from bench_refs import REFS, Agent, FakeTime, never

ENGINE_METHODS = {
    "ensure_task", "agent_of", "check_edit", "record_changes", "renamed", "claim_pending", "claim", "file_plan",
    "release", "pending_briefings", "record_edited_file", "edited_files", "note_touched", "started_at", "stop_check",
    "holding", "land", "block_landing", "last_block", "note_reading", "note_interest_from_text", "pending_messages",
    "state", "explain", "insights",
}
SLUG_A, SLUG_B = REFS["slugify-keyword-only"]
TRUNCATE_A = REFS["truncate-words-limit"][0]
# A shell write. The comment never reaches the facts, so finding it in a request would mean the file was sent.
MARKER = "# written by a shell redirect, kept on this machine"
B_VIEWS = f'''{MARKER}
from tags.models import Tag
from utils.text import truncate_words


def create_tag(name):
    return Tag(name).save()


def tag_label(name):
    return truncate_words(name, 3)
'''


# The stand-in server


def _write_file(graph, rel, facts):
    """graph.write_file: reindex_file's effect for one file, from facts parsed on the client."""
    if facts is None:
        graph.query("MATCH (s:Symbol {file: $file}) DETACH DELETE s", {"file": rel})
        graph.query("MATCH (f:File {path: $file}) DETACH DELETE f", {"file": rel})
        return []
    rows = graph.query(
        "MATCH (s:Symbol {file: $file}) RETURN s.qualname, s.signature, s.sig_hash", {"file": rel}
    ).result_set
    old = {q: (sig, h) for q, sig, h in rows}
    from airspace.types import SignatureChange

    changes = [SignatureChange(s.qualname, old[s.qualname][0], s.signature)
               for s in facts.symbols if s.qualname in old and old[s.qualname][1] != s.sig_hash]
    known = known_qualnames(graph) | {s.qualname for s in facts.symbols}
    writer._write_symbols(graph, facts)
    writer._delete_stale(graph, facts)
    writer._write_edges(graph, facts, known)
    return changes


def _index(graph, facts_list, reset):
    """graph.index: index_repo's two passes over facts parsed on the client."""
    ensure_schema(graph)
    if reset:
        graph.query("MATCH (n) WHERE n:Symbol OR n:File DETACH DELETE n")
    known = known_qualnames(graph) | {s.qualname for f in facts_list for s in f.symbols}
    for facts in facts_list:
        writer._write_symbols(graph, facts)
        writer._delete_stale(graph, facts)
    calls = unresolved = 0
    for facts in facts_list:
        c, u = writer._write_edges(graph, facts, known)
        calls += c
        unresolved += u
    return {"files": len(facts_list), "symbols": sum(len(f.symbols) for f in facts_list), "calls": calls,
            "unresolved": unresolved}


class RpcServer:
    def __init__(self):
        self.workspaces: dict[str, tuple[str, object]] = {}  # key -> (workspace id, graph)
        self.requests: list[dict] = []  # {"method", "body"}, the raw body as received
        self.url = ""

    def dispatch(self, graph, method, args, kwargs):
        if method == "graph.known":
            return sorted(known_qualnames(graph) | removed_qualnames(graph))
        if method == "graph.write_file":
            return _write_file(graph, *args)
        if method == "graph.index":
            return _index(graph, *args)
        return getattr(Airspace(graph), method)(*args, **kwargs)

    def app(self):
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI()

        @app.post("/api/rpc")
        async def rpc(request: Request):
            raw = (await request.body()).decode()
            auth = request.headers.get("authorization", "")
            found = self.workspaces.get(auth.removeprefix("Bearer ")) if auth.startswith("Bearer ") else None
            if found is None:
                return JSONResponse({"ok": False, "error": "Unknown key."}, status_code=401)
            workspace, graph = found
            body = json.loads(raw)
            method = body.get("method")
            self.requests.append({"method": method, "body": raw})
            if method not in ENGINE_METHODS and method not in {"graph.known", "graph.write_file", "graph.index"}:
                return JSONResponse({"ok": False, "error": f"Unknown method {method}."}, status_code=400)
            result = self.dispatch(graph, method, decode(body.get("args") or []), decode(body.get("kwargs") or {}))
            return JSONResponse({"ok": True, "result": encode(result)}, headers={"X-Airspace-Workspace": workspace})

        return app

    def methods(self) -> list[str]:
        return [r["method"] for r in self.requests]


@pytest.fixture(scope="module")
def server():
    import uvicorn

    rpc = RpcServer()
    uv = uvicorn.Server(uvicorn.Config(rpc.app(), host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        assert time.monotonic() < deadline, "the RPC server did not start"
        time.sleep(0.01)
    port = uv.servers[0].sockets[0].getsockname()[1]
    rpc.url = f"http://127.0.0.1:{port}"
    yield rpc
    uv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def workspace(db, server):
    """A fresh workspace: its own graph and key on the stand-in server. Yields (key, workspace id, graph)."""
    graph = db.select_graph(f"test_{uuid.uuid4().hex[:12]}")
    ensure_schema(graph)
    key, ws = "ask_" + uuid.uuid4().hex + uuid.uuid4().hex[:8], uuid.uuid4().hex[:12]
    server.workspaces[key] = (ws, graph)
    server.requests.clear()
    yield key, ws, graph
    server.workspaces.pop(key, None)
    try:
        graph.delete()
    except Exception:
        pass


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=airspace", "-c", "user.email=airspace@example.invalid",
                    *args], check=True, capture_output=True)


@pytest.fixture
def repo(blog_repo):
    _git(blog_repo, "init", "-q", "-b", "main")
    _git(blog_repo, "add", "-A")
    _git(blog_repo, "commit", "-q", "-m", "fixture")
    return blog_repo


@pytest.fixture
def connected(db, repo, server, workspace, monkeypatch):
    """The repo connected to the workspace and indexed there, with two agents on remote-mode hook deps."""
    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    key, ws, graph = workspace
    set_remote(repo, Remote(server.url, key, ws))
    remote_index(RpcClient(server.url, key), repo)
    deps = default_deps()
    yield graph, Agent(repo, "agent-a", "sess-aaaa", deps), Agent(repo, "agent-b", "sess-bbbb", deps)
    # Remote mode never opened the repo's own graph on this machine.
    assert graph_name(repo) not in db.list_graphs()


def _context(out) -> str:
    return out["hookSpecificOutput"]["additionalContext"] if out else ""


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Configuration


def test_remotes_are_keyed_by_real_path_and_private(tmp_path):
    real = tmp_path / "repo"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    set_remote(link, Remote("https://example.invalid", "ask_" + "0" * 40, "abcdef012345"))

    assert list(load_remotes()) == [os.path.realpath(real)]
    assert remote_for(real) == Remote("https://example.invalid", "ask_" + "0" * 40, "abcdef012345")
    assert stat.S_IMODE(remotes_path().stat().st_mode) == 0o600
    assert remotes_path().parent == Path(os.environ["AIRSPACE_CONFIG_DIR"])

    assert remove_remote(real) is True
    assert remote_for(real) is None and remove_remote(real) is False


def test_seen_sources_stay_in_the_local_cache(tmp_path):
    engine = RemoteAirspace(RpcClient("http://127.0.0.1:1", "ask_x"), seen_dir())
    assert engine.seen_source("/repo", "a.py") is None
    engine.note_seen("/repo", "a.py", "x = 1\r\n")
    assert engine.seen_source("/repo", "a.py") == "x = 1\r\n"
    assert engine.seen_source("/other", "a.py") is None
    assert str(seen_dir()).startswith(os.environ["AIRSPACE_CACHE_DIR"])


# RPC


def test_rpc_client_speaks_the_contract(server, workspace):
    key, ws, graph = workspace
    client = RpcClient(server.url, key)
    client.call("ensure_task", "agent-a", "t1")
    assert client.workspace == ws
    assert client.call("agent_of", "t1") == "agent-a"

    with pytest.raises(RemoteError) as refused:
        client.call("pause", "agent-a")  # a Tower control, not open to keys
    assert refused.value.status == 400 and str(refused.value) == "Unknown method pause."

    with pytest.raises(RemoteError) as bad_key:
        RpcClient(server.url, "ask_nope").call("graph.known")
    assert bad_key.value.status == 401 and str(bad_key.value) == "Unknown key."

    with pytest.raises(RemoteError) as down:
        RpcClient(f"http://127.0.0.1:{_closed_port()}", key).call("graph.known")
    assert down.value.status is None


def test_remote_index_writes_what_index_repo_writes(db, repo, server, workspace, monkeypatch):
    key, _, graph = workspace
    local = db.select_graph(f"test_{uuid.uuid4().hex[:12]}")
    try:
        expected = index_repo(local, repo)
        # Small batches: calls into files of a later batch must still resolve.
        monkeypatch.setattr("airspace.remote.BATCH_FILES", 3)
        stats = remote_index(RpcClient(server.url, key), repo)
        assert stats == expected

        def picture(g):
            symbols = g.query("MATCH (s:Symbol) RETURN s.qualname, s.signature ORDER BY s.qualname").result_set
            edges = g.query("MATCH (a)-[r]->(b:Symbol) RETURN type(r), a.qualname, b.qualname "
                            "ORDER BY type(r), a.qualname, b.qualname").result_set
            return symbols, edges

        assert picture(graph) == picture(local)
        index_calls = [json.loads(r["body"])["args"][1] for r in server.requests if r["method"] == "graph.index"]
        assert index_calls[0] is True and not any(index_calls[1:]) and len(index_calls) > 2
    finally:
        local.delete()


def test_remote_reindex_sends_facts_none_for_a_deleted_file_and_nothing_for_broken_code(repo, server, workspace):
    key, _, graph = workspace
    client = RpcClient(server.url, key)
    remote_index(client, repo)
    text = repo / "utils" / "text.py"
    source = text.read_text()

    text.write_text(source.replace("def slugify(value, allow_unicode=False):", "def slugify(value, *, unicode=False):"))
    changes = remote_reindex(client, repo, "utils/text.py")
    assert [(c.qualname, c.new_signature) for c in changes] == [("utils.text.slugify", "slugify(value, *, unicode=False)")]

    server.requests.clear()
    text.write_text("def slugify(value:\n")
    assert remote_reindex(client, repo, "utils/text.py") == []
    assert server.requests == []  # the last good picture stays

    text.unlink()
    assert remote_reindex(client, repo, "utils/text.py") == []
    assert json.loads(server.requests[-1]["body"])["args"] == ["utils/text.py", None]
    assert graph.query("MATCH (s:Symbol {file: 'utils/text.py'}) RETURN count(s)").result_set == [[0]]


# The hooks in remote mode


def test_call_after_the_change_is_held_in_remote_mode(connected, server):
    graph, a, b = connected
    assert a.apply(SLUG_A), a.holds
    assert b.apply(SLUG_B) is False

    reason = b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert "slugify(value, *, unicode=False)" in reason and "agent-a" in reason
    held = graph.query("MATCH (x:Collision) RETURN x.kind, x.held_agent, x.owner_agent, x.symbol").result_set
    assert held == [["contract", "agent-b", "agent-a", "utils.text.slugify"]]
    assert {"graph.known", "graph.write_file", "check_edit", "record_changes"} <= set(server.methods())


def test_stop_blocks_the_landing_in_remote_mode(connected):
    graph, a, b = connected
    assert b.apply(SLUG_B), b.holds
    assert a.apply(SLUG_A), a.holds

    # agent-a still claims slugify, so agent-b holds until agent-a lands, then its landing is blocked.
    t = FakeTime(lambda: a.stop(sleep=never))
    out = b.stop(sleep=t.sleep, clock=t.clock)

    assert t.sleeps == 1
    assert out is not None and out["decision"] == "block", out
    assert "slugify(value, *, unicode=False)" in out["reason"]
    assert "slugify(post.title, allow_unicode=True)" in out["reason"]
    assert graph.query("MATCH (t:Task {id: 'sess-aaaa'}) RETURN t.status").result_set == [["landed"]]


def test_shell_write_in_remote_mode_keeps_seen_sources_local(connected, server):
    graph, a, b = connected
    assert a.apply(TRUNCATE_A)

    out = b.shell_write("tags/views.py", B_VIEWS)
    text = _context(out)
    assert "tags/views.py was written outside the edit tools." in text
    assert "truncate_words(text, *, limit=30)" in text
    assert Airspace(graph).edited_files(b.session) == ["tags/views.py"]

    # What reconcile saw is on this machine, and no request carried a whole file or asked for one.
    scope = os.path.realpath(b.repo)
    engine = RemoteAirspace(RpcClient(server.url, "unused"), seen_dir())
    assert engine.seen_source(scope, "tags/views.py") == B_VIEWS
    assert engine.seen_source(scope, "utils/text.py") == (a.repo / "utils" / "text.py").read_text()
    assert not {"seen_source", "note_seen"} & set(server.methods())
    assert not any(MARKER in r["body"] for r in server.requests)
    assert graph.query("MATCH (v:Seen) RETURN count(v)").result_set == [[0]]

    assert a.stop(sleep=never) is None
    stop = b.stop(sleep=never)
    assert stop is not None and stop["decision"] == "block"
    assert "truncate_words(name, 3)" in stop["reason"]


# Failing open


def _edit_payload(repo) -> dict:
    return {"session_id": "sess-aaaa", "cwd": str(repo), "tool_name": "Edit",
            "tool_input": {"file_path": "utils/text.py", "old_string": "allow_unicode=False", "new_string": "u=False"}}


@pytest.mark.parametrize("why", ["down", "bad key"])
def test_hooks_fail_open_with_one_line_when_the_server_cannot_be_used(repo, server, workspace, capsys, why):
    key, ws, _ = workspace
    url = f"http://127.0.0.1:{_closed_port()}" if why == "down" else server.url
    set_remote(repo, Remote(url, key if why == "down" else "ask_revoked", ws))
    deps = default_deps()
    env = {"CLAUDE_PROJECT_DIR": str(repo), "AIRSPACE_AGENT": "agent-a"}
    payload = _edit_payload(repo)
    capsys.readouterr()

    hooks = [
        ("pre", handle_pre, payload),
        ("post", handle_post, payload),
        ("any", handle_any, {**payload, "tool_name": "Bash", "tool_input": {"command": "pytest"}}),
        ("stop", handle_stop, {"session_id": "sess-aaaa", "cwd": str(repo)}),
    ]
    for name, handler, event in hooks:
        assert handler(event, deps, env) is None, name
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and err.startswith("airspace: Airspace server unavailable ("), (name, err)
        assert ("did not answer" in err) if why == "down" else ("401 Unknown key." in err), err


# The CLI


def test_connect_with_a_bad_key_exits_1_and_saves_nothing(repo, server, workspace, capsys):
    assert cli.main(["connect", "--root", str(repo), "--server", server.url, "--key", "ask_wrong"]) == 1
    err = capsys.readouterr().err
    assert "did not accept this key" in err and "Nothing was saved." in err
    assert not remotes_path().exists()


def test_connect_to_a_server_that_is_down_exits_1(repo, capsys):
    url = f"http://127.0.0.1:{_closed_port()}"
    assert cli.main(["connect", "--root", str(repo), "--server", url, "--key", "ask_x"]) == 1
    assert "cannot connect" in capsys.readouterr().err
    assert not remotes_path().exists()


def test_connect_index_status_and_disconnect(repo, server, workspace, capsys):
    key, ws, graph = workspace
    root = repo.resolve()
    assert cli.main(["connect", "--root", str(repo), "--server", server.url + "/", "--key", key]) == 0
    out = capsys.readouterr().out
    assert f"Tower: {server.url}/w/{ws}" in out
    assert f"Next: airspace install-hooks --root {root}" in out
    assert re.search(r"^Indexed \d+ files, \d+ symbols, \d+ calls \(\d+ unresolved\)$", out, re.M), out
    assert load_remotes() == {str(root): {"server": server.url, "key": key, "workspace": ws}}
    assert stat.S_IMODE(remotes_path().stat().st_mode) == 0o600
    assert graph.query("MATCH (s:Symbol {qualname: 'utils.text.slugify'}) RETURN count(s)").result_set == [[1]]

    server.requests.clear()
    assert cli.main(["index", "--root", str(repo)]) == 0
    assert capsys.readouterr().out.startswith("Indexed ")
    assert set(server.methods()) == {"graph.index"}

    engine = Airspace(graph)
    engine.ensure_task("agent-a", "sess-aaaa")
    engine.claim("sess-aaaa", ["utils.text.slugify"])
    assert cli.main(["status", "--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert f"Workspace {ws} on {server.url}" in out
    line = next(line for line in out.splitlines() if "agent-a" in line)
    assert "active" in line and "utils.text.slugify" in line

    assert cli.main(["disconnect", "--root", str(repo)]) == 0
    assert "Disconnected" in capsys.readouterr().out
    assert load_remotes() == {}
    assert cli.main(["disconnect", "--root", str(repo)]) == 0
    assert "was not connected" in capsys.readouterr().out


def test_insights_and_the_mcp_tools_use_the_workspace(connected, monkeypatch, capsys):
    import airspace.mcp_server.server as mcp

    graph, a, _ = connected
    assert cli.main(["insights", "--root", str(a.repo)]) == 0
    assert capsys.readouterr().out.startswith("Hot zones (")

    built = {}

    class Server:
        def run(self, transport):
            built["transport"] = transport

    def build_server(root, airspace_factory=None):
        built["factory"] = airspace_factory
        return Server()

    monkeypatch.setattr(mcp, "build_server", build_server)
    assert cli.main(["mcp", "--root", str(a.repo)]) == 0
    engine = built["factory"](a.repo)
    assert isinstance(engine, RemoteAirspace) and built["transport"] == "stdio"

    plan = mcp.file_flight_plan(engine, "agent-m", "agent-m:mcp", ["utils.text.slugify"], "keyword only")
    assert "1 claimed" in plan
    assert "claimed by this agent" in mcp.check_symbols(engine, "agent-m", ["utils.text.slugify"])
    assert "utils.text.slugify" in mcp.explain(engine, "blog.models.Post.save", "utils.text.slugify")
    assert mcp.briefings(engine, "agent-m", "agent-m:mcp") == "No pending briefings or messages."
    assert "betweenness" in mcp.hot_zones(engine)
    assert graph.query("MATCH (:Task {id: 'agent-m:mcp'})-[:CLAIMS]->(s) RETURN s.qualname").result_set == [
        ["utils.text.slugify"]]


def test_status_and_index_report_a_server_that_is_down(repo, capsys):
    set_remote(repo, Remote(f"http://127.0.0.1:{_closed_port()}", "ask_x", "abcdef012345"))
    assert cli.main(["status", "--root", str(repo)]) == 1
    assert "Airspace server unavailable" in capsys.readouterr().err
    assert cli.main(["index", "--root", str(repo)]) == 1
    assert "Airspace server unavailable" in capsys.readouterr().err
