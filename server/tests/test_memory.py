"""Memory: notes and fixes on the code graph, told once to every later task that touches the code.

Engine tests run on the seeded blog graph with a fake clock. Hook tests run through the real hooks, indexer and
engine on a copy of the blog fixture, as test_landing does; the scenario at the end tells the whole story.
"""

import pytest
from cloud_helpers import (  # noqa: F401 (fixtures)
    app_client,
    client,
    cloud,
    github,
    make_cloud,
    new_workspace,
    sign_in,
)
from fastapi.testclient import TestClient

from airspace import cli
from airspace.admission import text as hook_text
from airspace.admission.engine import Airspace
from airspace.admission.memory import fix_text, resolve_names
from airspace.admission.preflight import PreflightError, as_text, preflight
from airspace.api.app import create_app
from airspace.graph.db import repo_graph
from airspace.indexer.writer import index_repo
from airspace.mcp_server import server as mcp
from airspace.types import CallSite, SignatureChange
from bench_refs import REFS, SLUG_A, Agent, is_deny, never
from conftest import FIXTURE_REPO
from helpers import seed_blog_graph

SLUGIFY = "utils.text.slugify"
TRUNCATE = "utils.text.truncate_words"
RENDER = "blog.views.render_post"
POST_LIST = "blog.views.post_list"
OLD_SIG = "slugify(value, allow_unicode=False)"
NEW_SIG = "slugify(value, *, unicode=False)"
HELD_CALL = "slugify(post.title, allow_unicode=True)"
FIXED_CALL = "slugify(post.title, unicode=True)"
FIX = (f"agent-b's call {HELD_CALL} did not fit {NEW_SIG} after agent-a's change. It cleared as {FIXED_CALL}.")
WRITE = {"X-Airspace": "1"}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 1.0) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def airspace(graph, clock):
    seed_blog_graph(graph)
    return Airspace(graph, lease_seconds=900, cone_depth=2, clock=clock)


def _site(kwargs: tuple[str, ...], text: str = "") -> CallSite:
    return CallSite(RENDER, 1, kwargs, False, False, False, text=text)


def _change_slugify(airspace, task: str = "task-a", agent: str = "agent-a") -> None:
    airspace.ensure_task(agent, task)
    airspace.record_changes(task, [SignatureChange(SLUGIFY, OLD_SIG, NEW_SIG)])


def _hold_then_clear(airspace, clock, held_text: str = HELD_CALL, fixed_text: str = FIXED_CALL) -> str:
    """agent-b's natural call is held against agent-a's change, then its retry with the new keyword clears."""
    _change_slugify(airspace)
    airspace.ensure_task("agent-b", "task-b")
    clock.tick()
    held = airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)],
                               {SLUGIFY: [_site(("allow_unicode",), held_text)]})
    assert held.kind == "hold"
    clock.tick()
    cleared = airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)], {SLUGIFY: [_site(("unicode",), fixed_text)]})
    assert cleared.kind == "cleared"
    return held.collision_id


# Engine: remember and recall


def test_remember_and_recall_newest_first(airspace, graph, clock):
    first = airspace.remember("agent-a", "task-a", [SLUGIFY], "  slugify strips accents unless unicode is set.  ")
    clock.tick()
    second = airspace.remember("Tower", None, [TRUNCATE, SLUGIFY], "Both helpers are used by the feeds.")

    items = airspace.recall([SLUGIFY])
    assert items == [
        {"id": second, "kind": "note", "symbol": TRUNCATE, "text": "Both helpers are used by the feeds.",
         "agent": "Tower", "at": 1001.0},
        {"id": first, "kind": "note", "symbol": SLUGIFY, "text": "slugify strips accents unless unicode is set.",
         "agent": "agent-a", "at": 1000.0},
    ]
    # A file path means every symbol the file defines.
    assert airspace.recall(["utils/text.py"]) == items
    assert [i["id"] for i in airspace.recall([TRUNCATE])] == [second]
    assert airspace.recall([RENDER]) == [] and airspace.recall([]) == []
    assert airspace.recall([SLUGIFY], limit=1) == items[:1]
    # One ABOUT edge per symbol, and a noted event for each note.
    assert graph.query("MATCH (:Note {id: $id})-[:ABOUT]->(s:Symbol) RETURN s.qualname ORDER BY s.qualname",
                       {"id": second}).result_set == [[SLUGIFY], [TRUNCATE]]
    events = graph.query("MATCH (e:Event {kind: 'noted'}) RETURN e.agent, e.text, e.code ORDER BY e.seq").result_set
    assert events == [["agent-a", "added a note on", SLUGIFY], ["Tower", "added a note on", TRUNCATE]]


def test_remember_refuses_what_it_cannot_store(airspace):
    with pytest.raises(ValueError, match=r"Not in the code graph: utils\.text\.nope, nope/x\.py\."):
        airspace.remember("a", "t", [SLUGIFY, "utils.text.nope", "nope/x.py"], "text")
    with pytest.raises(ValueError, match="1 to 500 characters"):
        airspace.remember("a", "t", [SLUGIFY], "   ")
    with pytest.raises(ValueError, match="1 to 500 characters"):
        airspace.remember("a", "t", [SLUGIFY], "x" * 501)
    with pytest.raises(ValueError, match="at least one symbol"):
        airspace.remember("a", "t", [], "text")
    with pytest.raises(ValueError, match="kind"):
        airspace.remember("a", "t", [SLUGIFY], "text", kind="gossip")
    assert airspace.recent_notes() == []
    assert airspace.remember("a", "t", [SLUGIFY], "x" * 500)


def test_recall_includes_contract_changes_by_other_tasks(airspace, clock):
    _change_slugify(airspace)
    clock.tick()
    airspace.ensure_task("agent-c", "task-c")
    airspace.record_changes("task-c", [
        SignatureChange("blog.models.Post.get_absolute_url", "get_absolute_url(self)", "", "blog.models.Post.url",
                        "url(self)"),
        SignatureChange(TRUNCATE, "truncate_words(text, count=30)", ""),
    ])

    (item,) = airspace.recall([SLUGIFY])
    assert item["kind"] == "contract" and item["symbol"] == SLUGIFY and item["agent"] == "agent-a"
    assert item["text"] == f"Contract changed: {OLD_SIG} -> {NEW_SIG}" and item["at"] == 1000.0
    assert airspace.recall([SLUGIFY], exclude_task="task-a") == []
    # Written in one tick: the later write is the newer.
    assert [i["text"] for i in airspace.recall(["blog.models.Post.get_absolute_url", TRUNCATE])] == [
        "Removed", "Renamed to blog.models.Post.url"]


# Engine: delivery to a task


def test_memory_for_task_tells_each_task_once_and_never_its_own(airspace, clock):
    note = airspace.remember("agent-a", "task-a", [SLUGIFY], "Keep slugify ASCII by default.")
    _change_slugify(airspace)
    for task, agent in (("task-b", "agent-b"), ("task-c", "agent-c")):
        airspace.ensure_task(agent, task)

    # Its own note and its own change are not news to task-a.
    assert airspace.memory_for_task("task-a", [SLUGIFY]) == []
    got = airspace.memory_for_task("task-b", ["utils/text.py"])
    assert [(i["kind"], i["id"] == note) for i in got] == [("note", True), ("contract", False)]
    assert airspace.memory_for_task("task-b", [SLUGIFY, TRUNCATE]) == []
    # Another task hears it all, once.
    assert len(airspace.memory_for_task("task-c", [SLUGIFY])) == 2
    assert airspace.memory_for_task("task-c", [SLUGIFY]) == []
    # A task the graph does not know hears nothing (it could not be marked).
    assert airspace.memory_for_task("task-unknown", [SLUGIFY]) == []


def test_memory_for_task_leaves_out_a_change_the_task_was_briefed_on(airspace):
    _change_slugify(airspace)
    airspace.ensure_task("agent-b", "task-b")
    held = airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)])  # held, and briefed on the change
    assert held.kind == "hold" and held.briefings
    assert airspace.memory_for_task("task-b", [SLUGIFY]) == []


def test_history_counts_collisions_notes_and_changes(airspace, clock):
    assert airspace.history([SLUGIFY]) == {"collisions": 0, "notes": 0, "changes": 0, "last_at": None}
    _hold_then_clear(airspace, clock)  # one contract collision, one change, one fix note
    clock.tick()
    airspace.remember("Tower", None, [SLUGIFY], "Check the feeds after changing slugify.")
    assert airspace.history([SLUGIFY]) == {"collisions": 1, "notes": 2, "changes": 1, "last_at": 1003.0}
    assert airspace.history(["utils/text.py"]) == airspace.history([SLUGIFY])
    assert airspace.history([TRUNCATE]) == {"collisions": 0, "notes": 0, "changes": 0, "last_at": None}


def test_recent_notes_and_insights(airspace, clock):
    for i in range(7):
        clock.tick()
        airspace.remember("Tower", None, [SLUGIFY], f"note {i}")
    assert [n["text"] for n in airspace.recent_notes(3)] == ["note 6", "note 5", "note 4"]
    assert [n["text"] for n in airspace.insights()["notes"]] == ["note 6", "note 5", "note 4", "note 3", "note 2"]


def test_notes_outlive_a_full_reindex(airspace, graph):
    note = airspace.remember("Tower", None, [SLUGIFY], "Survives re-indexing.")
    graph.query("MATCH (s:Symbol) DETACH DELETE s")
    graph.query("MATCH (f:File) DETACH DELETE f")
    seed_blog_graph(graph)
    assert [i["id"] for i in airspace.recall(["utils/text.py"])] == [note]


# Engine: fix notes


def test_a_resolved_contract_collision_writes_a_fix_note(airspace, graph, clock):
    cid = _hold_then_clear(airspace, clock)

    (fix,) = [i for i in airspace.recall([SLUGIFY]) if i["kind"] == "fix"]
    assert fix == {"id": fix["id"], "kind": "fix", "symbol": SLUGIFY, "text": FIX, "agent": "agent-b", "at": 1002.0}
    # About the changed symbol and the caller that was fixed.
    assert [i["id"] for i in airspace.recall([RENDER])] == [fix["id"]]
    detail = airspace.collision(cid)
    assert detail["resolution"] == "resolved" and detail["fix"] == fix
    assert graph.query("MATCH (x:Collision {id: $id}) RETURN x.held_call, x.fixed_call", {"id": cid}).result_set == [
        [HELD_CALL, FIXED_CALL]]
    # agent-b fixed it, so it is not news to agent-b; agent-a and any later task hear it.
    assert airspace.memory_for_task("task-b", [SLUGIFY]) == []
    assert [i["kind"] for i in airspace.memory_for_task("task-a", [RENDER])] == ["fix"]
    assert chr(0x2014) not in FIX and chr(0x2013) not in FIX


def test_a_fix_note_without_call_texts_says_what_it_knows(airspace, clock):
    cid = _hold_then_clear(airspace, clock, held_text="", fixed_text="")
    assert airspace.collision(cid)["fix"]["text"] == (
        f"agent-b was held at {SLUGIFY} after agent-a's change to {NEW_SIG}, and cleared with a call that fits.")
    assert fix_text("b", "a", SLUGIFY, NEW_SIG, HELD_CALL, "") == fix_text("b", "a", SLUGIFY, NEW_SIG, "", "")
    assert fix_text("b", "a", SLUGIFY, "", "", "") == (
        f"b was held at {SLUGIFY} after a renamed or removed it, and cleared.")


def test_a_released_collision_writes_no_fix_note(airspace, clock):
    _change_slugify(airspace)
    airspace.ensure_task("agent-b", "task-b")
    natural = {SLUGIFY: [_site(("allow_unicode",), HELD_CALL)]}
    held = airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)], natural)
    airspace.release_collision(held.collision_id)
    assert airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)], natural).kind == "cleared"
    assert airspace.recent_notes() == [] and airspace.collision(held.collision_id)["fix"] is None


# Hook text


def test_memory_block_is_short_factual_and_keeps_the_newest():
    items = [{"id": str(i), "kind": "note", "symbol": SLUGIFY, "text": "x" * 400, "agent": "Tower", "at": 1e9 + i}
             for i in range(10, 0, -1)]
    block = hook_text.memory_block(items)
    assert len(block) <= 1200 and block.count("\n") == 1
    assert block.splitlines()[0].startswith(f"Airspace memory: {SLUGIFY}: xxx")
    assert block.splitlines()[0].endswith(f"... (note by Tower, {hook_text._day(1e9 + 10)})")
    fix = {"id": "f", "kind": "fix", "symbol": SLUGIFY, "text": FIX, "agent": "agent-b", "at": 1e9}
    change = {"id": "c", "kind": "contract", "symbol": SLUGIFY, "text": f"Contract changed: {OLD_SIG} -> {NEW_SIG}",
              "agent": "agent-a", "at": 1e9}
    day = hook_text._day(1e9)
    assert hook_text.memory_line(fix) == f"Airspace memory: {SLUGIFY}: {FIX} (fix, {day})"
    assert hook_text.memory_line(change) == (
        f"Airspace memory: {SLUGIFY}: Contract changed: {OLD_SIG} -> {NEW_SIG}. (changed by agent-a, {day})")
    assert hook_text.memory_block([]) == ""


# Hooks through the real engine


@pytest.fixture
def indexed(db, blog_repo, monkeypatch):
    from airspace.hooks.handlers import default_deps

    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    graph = repo_graph(db, blog_repo)
    index_repo(graph, blog_repo)
    deps = default_deps()
    yield graph, blog_repo, deps
    graph.delete()


SLUG_B = REFS["slugify-keyword-only"][1]
B_RETRY = {"file_path": "blog/views.py", "old_string": "<article>",
           "new_string": f'<article data-slug="{{{FIXED_CALL}}}">'}
C_CALL = {"file_path": "blog/views.py", "old_string": 'return "\\n".join(render_post(p) for p in posts)',
          "new_string": 'return "\\n".join(f\'<li id="{slugify(p.title)}">{render_post(p)}</li>\' for p in posts)'}


def _context(out) -> str:
    return out["hookSpecificOutput"]["additionalContext"] if out else ""


def _session_one(repo, deps) -> tuple[Agent, Agent]:
    """agent-a makes slugify's unicode option keyword-only; agent-b's natural call is held, and its retry clears."""
    a = Agent(repo, "agent-a", "sess-a1", deps)
    b = Agent(repo, "agent-b", "sess-b1", deps)
    assert a.apply(SLUG_A), a.holds
    assert b.apply(SLUG_B) is False
    held = b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert held.startswith(f"Airspace hold: {SLUGIFY} is being changed by agent-a.")
    assert "Airspace memory" not in held  # agent-b was briefed on the change in the hold itself
    assert b.edit("blog/views.py", "Edit", B_RETRY), b.holds[1:]
    # The fix is agent-b's own: it is not told it back.
    assert all("Airspace memory" not in c for c in b.contexts)
    assert a.stop(sleep=never) is None and b.stop(sleep=never) is None
    return a, b


def _fix_line(graph) -> str:
    (at,) = graph.query("MATCH (m:Note {kind: 'fix'}) RETURN m.at").result_set[0]
    return f"Airspace memory: {SLUGIFY}: {FIX} (fix, {hook_text._day(at)})"


def test_a_later_session_hears_the_fix_on_its_first_edit_that_calls_the_symbol(indexed):
    graph, repo, deps = indexed
    _session_one(repo, deps)
    c = Agent(repo, "agent-c", "sess-c2", deps)

    out = c.pre("Edit", C_CALL)
    assert not is_deny(out)
    assert _fix_line(graph) in _context(out)
    c.write("blog/views.py", "Edit", C_CALL)
    c.post("Edit", C_CALL)
    again = {"file_path": "blog/views.py", "old_string": "def post_list(posts):",
             "new_string": "def post_list(posts):\n    _ = slugify('x')"}
    assert FIX not in _context(c.pre("Edit", again))


def test_a_later_session_hears_the_fix_on_reading_the_file_once(indexed):
    graph, repo, deps = indexed
    _session_one(repo, deps)
    c = Agent(repo, "agent-c", "sess-c2", deps)

    first = _context(c.read("utils/text.py"))
    assert first.splitlines()[0] == _fix_line(graph)
    assert "Contract changed: " in first and len(first.splitlines()) == 2
    assert c.read("utils/text.py") is None
    assert c.read("blog/views.py") is None  # the fix is about render_post too, and it was told already
    assert c.read("README.md") is None


def test_a_later_session_hears_the_fix_from_its_prompt(indexed):
    graph, repo, deps = indexed
    _session_one(repo, deps)
    c = Agent(repo, "agent-c", "sess-c2", deps)

    out = c.prompt("Make post_list in blog/views.py link each post by its slug.")
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert _context(out) == _fix_line(graph)
    assert c.prompt("Make post_list in blog/views.py link each post by its slug.") is None
    assert c.prompt("Nothing here names the code.") is None


def test_a_memory_failure_never_changes_the_verdict(tmp_path, capsys):
    from test_hooks import ENV, FakeAirspace, make_deps, payload, touched_render_post

    from airspace.hooks.handlers import handle_any, handle_pre, handle_prompt
    from airspace.types import Verdict

    class Broken(FakeAirspace):
        def memory_for_task(self, task_id, qualnames, limit=8):
            raise RuntimeError("graph went away")

        def note_interest_from_text(self, agent_id, task_id, text):
            return ["utils/text.py"]

        def note_reading(self, agent_id, task_id, rel):
            pass

    deps = make_deps(Broken(verdict=Verdict("hold", "r")), analysis=touched_render_post())
    held = handle_pre(payload(tmp_path), deps, ENV)
    assert held["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert held["hookSpecificOutput"]["permissionDecisionReason"] == "r"
    assert handle_pre(payload(tmp_path), make_deps(Broken(), analysis=touched_render_post()), ENV) is None
    read = {"session_id": "s", "cwd": str(tmp_path), "tool_name": "Read",
            "tool_input": {"file_path": str(tmp_path / "utils/text.py")}}
    assert handle_any(read, make_deps(Broken()), ENV) is None
    assert handle_prompt({"session_id": "s", "cwd": str(tmp_path), "prompt": "utils/text.py"},
                         make_deps(Broken()), ENV) is None
    err = capsys.readouterr().err
    assert err.count("memory not delivered") == 4 and err.count("\n") == 4


# The whole story


def test_scenario_a_fix_from_one_session_reaches_the_next(indexed):
    """Session 1: agent-a changes slugify, agent-b's natural call is held and its retry with the new keyword clears,
    which writes the fix to the graph. Session 2: agent-c starts on blog/views.py and is told the fix before it writes
    a call; reading utils/text.py does not repeat it; a note a person adds in Tower reaches agent-c's next edit that
    calls slugify."""
    graph, repo, deps = indexed
    _session_one(repo, deps)
    fix_line = _fix_line(graph)

    # Session 2: new task ids, a new agent.
    c = Agent(repo, "agent-c", "sess-c2", deps)
    told = _context(c.prompt("Make post_list in blog/views.py link each post by its slug."))
    assert told == fix_line

    read = _context(c.read("utils/text.py"))
    assert FIX not in read
    assert read == (f"Airspace memory: {SLUGIFY}: Contract changed: {OLD_SIG} -> {NEW_SIG}. "
                    f"(changed by agent-a, {hook_text._day(_change_at(graph))})")

    # A person adds a note in Tower.
    api = TestClient(create_app(lambda: Airspace(graph)))
    human = "Feeds cache slugs for a day, so a slug change shows up there tomorrow."
    r = api.post("/api/notes", json={"symbols": ["slugify"], "text": human}, headers=WRITE)
    assert r.status_code == 200, r.text
    (at,) = graph.query("MATCH (m:Note {id: $id}) RETURN m.at", {"id": r.json()["id"]}).result_set[0]

    out = c.pre("Edit", C_CALL)
    assert not is_deny(out)
    # The briefing on agent-a's change comes from the impact cone, as before memory; the note follows it.
    assert _context(out) == (
        f"Airspace briefing: {SLUGIFY} was changed by agent-a. New signature: {NEW_SIG} (was {OLD_SIG}).\n"
        f"Airspace memory: {SLUGIFY}: {human} (note by Tower, {hook_text._day(at)})")
    c.write("blog/views.py", "Edit", C_CALL)
    c.post("Edit", C_CALL)
    assert c.read("utils/text.py") is None


def _change_at(graph) -> float:
    return graph.query("MATCH (cc:ContractChange {qualname: $q}) RETURN cc.at", {"q": SLUGIFY}).result_set[0][0]


# API


@pytest.fixture
def blog(graph):
    index_repo(graph, FIXTURE_REPO)
    return graph


def test_demo_api_memory_routes(blog):
    air = Airspace(blog)
    api = TestClient(create_app(lambda: air))

    assert api.post("/api/notes", json={"symbols": ["slugify"], "text": "x"}).status_code == 403
    r = api.post("/api/notes", json={"symbols": ["slugify", "utils/text.py"], "text": " Keep it ASCII. "},
                 headers=WRITE)
    assert r.status_code == 200 and set(r.json()) == {"id"}
    note_id = r.json()["id"]

    item = api.get("/api/memory", params={"symbols": "utils.text.slugify"}).json()["items"][0]
    assert item["id"] == note_id and item["text"] == "Keep it ASCII." and item["agent"] == "Tower"
    assert item["kind"] == "note" and item["symbol"] == SLUGIFY
    assert api.get("/api/memory", params={"symbols": "truncate_words, blog/views.py"}).json()["items"] == [item]
    assert api.get("/api/memory/recent", params={"limit": 5}).json() == {"items": [item]}

    bad = api.get("/api/memory", params={"symbols": "save"})
    assert bad.status_code == 422 and bad.json()["suggestions"] == ["tags.models.Tag.save", "blog.models.Post.save"]
    assert api.get("/api/memory").status_code == 422
    for body in ({"symbols": ["slugify"], "text": ""}, {"symbols": ["slugify"], "text": "x" * 501},
                 {"symbols": [], "text": "x"}, {"symbols": "slugify", "text": "x"}, {"text": "x"}):
        assert api.post("/api/notes", json=body, headers=WRITE).status_code == 422, body
    nope = api.post("/api/notes", json={"symbols": ["slugifyy"], "text": "x"}, headers=WRITE)
    assert nope.status_code == 422 and nope.json()["error"] == "No symbol named slugifyy."
    assert len(air.recent_notes()) == 1


def test_workspace_memory_routes_are_for_its_owner(client, cloud):  # noqa: F811 (fixtures)
    sign_in(client, cloud)
    wid, _ = new_workspace(client, cloud)
    index_repo(cloud.engine(wid).graph, FIXTURE_REPO)
    body = {"symbols": ["slugify"], "text": "Workspace note."}

    assert client.post(f"/api/w/{wid}/notes", json=body).status_code == 403
    r = client.post(f"/api/w/{wid}/notes", json=body, headers=WRITE)
    assert r.status_code == 200, r.text
    items = client.get(f"/api/w/{wid}/memory", params={"symbols": "utils/text.py"}).json()["items"]
    assert [(i["id"], i["text"], i["agent"]) for i in items] == [(r.json()["id"], "Workspace note.", "Tower")]
    assert client.get(f"/api/w/{wid}/memory/recent").json()["items"] == items
    other = app_client(cloud)
    assert other.get(f"/api/w/{wid}/memory/recent").status_code == 401
    assert other.post(f"/api/w/{wid}/notes", json=body, headers=WRITE).status_code == 401
    sign_in(other, cloud, github_id=2, login="bob")
    assert other.get(f"/api/w/{wid}/memory", params={"symbols": "slugify"}).status_code == 404
    assert other.post(f"/api/w/{wid}/notes", json=body, headers=WRITE).status_code == 404


# CLI and MCP


def test_cli_remember_recall_and_insights(blog, tmp_path, monkeypatch, capsys):
    air = Airspace(blog)
    monkeypatch.setattr(cli, "_airspace", lambda root: air)
    monkeypatch.setenv("AIRSPACE_AGENT", "agent-z")
    assert cli.main(["remember", "--root", str(tmp_path), "--symbol", "slugify", "--symbol", "truncate_words",
                     "Both are pure functions."]) == 0
    assert capsys.readouterr().out.startswith("Noted ")
    assert cli.main(["recall", "--root", str(tmp_path), "utils/text.py"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{SLUGIFY}: Both are pure functions. (note by agent-z, ")
    assert cli.main(["recall", "--root", str(tmp_path), "render_post"]) == 0
    assert capsys.readouterr().out == f"Nothing remembered about {RENDER}.\n"
    assert cli.main(["recall", "--root", str(tmp_path), "save"]) == 1
    assert "Did you mean:\n  tags.models.Tag.save" in capsys.readouterr().err
    assert cli.main(["remember", "--root", str(tmp_path), "--symbol", "slugify", " "]) == 1
    assert "1 to 500 characters" in capsys.readouterr().err
    assert cli.main(["insights", "--root", str(tmp_path)]) == 0
    assert f"Recent notes (1)\n  {SLUGIFY}: Both are pure functions." in capsys.readouterr().out


def test_mcp_remember_and_recall(blog):
    air = Airspace(blog)
    assert mcp.remember(air, "agent-m", "agent-m:mcp", ["slugify"], "Callers pass titles.") == (
        f"Noted about {SLUGIFY}. Later agents that touch this code hear it once.")
    assert mcp.recall(air, ["utils/text.py"]).startswith(f"{SLUGIFY}: Callers pass titles. (note by agent-m, ")
    assert mcp.recall(air, ["render_post"]) == f"Nothing remembered about {RENDER}."
    assert mcp.remember(air, "agent-m", "agent-m:mcp", ["save"], "x").startswith("save matches several symbols.")
    assert mcp.remember(air, "agent-m", "agent-m:mcp", ["slugify"], "").startswith("A note is 1 to 500")
    assert resolve_names(air, ["slugify", "utils/text.py"]) == [SLUGIFY, "utils/text.py"]
    with pytest.raises(PreflightError, match="No file nope.py"):
        resolve_names(air, ["nope.py"])


# Pre-flight


def test_memory_methods_are_open_to_a_key_and_refusals_come_back(blog):
    from airspace import wire
    from airspace.cloud.rpc import ENGINE_METHODS, RpcError, dispatch

    assert {"remember", "recall", "memory_for_task", "history", "recent_notes", "lookup_symbols"} <= ENGINE_METHODS
    air = Airspace(blog)
    note = wire.decode(dispatch(air, blog, "remember", ["agent-r", "t", [SLUGIFY], "Over RPC."], {}))
    assert wire.decode(dispatch(air, blog, "recall", [["utils/text.py"]], {}))[0]["id"] == note
    with pytest.raises(RpcError, match="remember refused: ValueError: Not in the code graph: nope."):
        dispatch(air, blog, "remember", ["agent-r", "t", ["nope"], "x"], {})
    assert dispatch(air, blog, "lookup_symbols", [["save"]], {})["error"] == "save matches several symbols."


def test_preflight_carries_each_tasks_history(blog):
    air = Airspace(blog)
    for i in range(2):
        air.ensure_task("agent-a", f"a{i}")
        air.check_edit(f"a{i}", [SLUGIFY], [])
        air.ensure_task("agent-b", f"b{i}")
        assert air.check_edit(f"b{i}", [SLUGIFY], []).kind == "hold"
        air.release(f"a{i}")
    air.remember("Tower", None, [SLUGIFY], "Hot.")
    slug, tags = {"name": "Slug", "symbols": ["slugify"]}, {"name": "Tags", "symbols": ["Tag.save"]}

    answer = preflight(blog, [slug, tags])
    assert answer["tasks"][0]["history"] == {"collisions": 2, "notes": 1, "changes": 0}
    assert answer["tasks"][1]["history"] == {"collisions": 0, "notes": 0, "changes": 0}
    assert answer["summary"].endswith(" Slug touches utils.text.slugify, which collided twice before.")
    assert f"  Slug: {SLUGIFY} (cone 6), from earlier sessions: 2 collisions, 1 note\n" in as_text(answer)
    assert "  Tags: tags.models.Tag.save (cone 1)\n" in as_text(answer)


def test_notes_on_the_public_demo_are_read_only(blog, monkeypatch):
    # A hosted demo anyone can open must not let anyone write text everyone reads. Workspaces stay writable.
    monkeypatch.setenv("AIRSPACE_PUBLIC_DEMO", "1")
    api = TestClient(create_app(lambda: Airspace(blog)))
    r = api.post("/api/notes", json={"symbols": ["slugify"], "text": "spam"}, headers=WRITE)
    assert r.status_code == 403 and "read-only" in r.json()["error"]
    assert api.get("/api/memory/recent").json() == {"items": []}
