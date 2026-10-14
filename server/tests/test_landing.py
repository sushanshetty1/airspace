"""The holding pattern on landing, through the real hooks, indexer and engine on a fixture copy.

An agent that finishes before the agent changing a contract it calls never makes another tool call, so a briefing
on the next tool call never reaches it. Its Stop hook checks the calls in the files it edited against every
contract change by another agent, waits while an active agent still holds a claim on a callee, and blocks the stop
with the change when a call no longer fits.
"""

import pytest

from airspace.admission.engine import Airspace
from airspace.graph.db import repo_graph
from bench_refs import REFS, SLUG_A, Agent, FakeTime, never

SLUGIFY = "utils.text.slugify"
NEW_SIG = "slugify(value, *, unicode=False)"
CALLER = "blog.views.render_post"
B_CALL = "slugify(post.title, allow_unicode=True)"
SLUG_B = REFS["slugify-keyword-only"][1]
FIX = {"file_path": "blog/views.py", "old_string": "allow_unicode=True", "new_string": "unicode=True"}


@pytest.fixture
def indexed(db, blog_repo, monkeypatch):
    from airspace.hooks.handlers import default_deps
    from airspace.indexer.writer import index_repo

    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    graph = repo_graph(db, blog_repo)
    index_repo(graph, blog_repo)
    deps = default_deps()
    yield graph, Agent(blog_repo, "agent-a", "sess-aaaa", deps), Agent(blog_repo, "agent-b", "sess-bbbb", deps)
    graph.delete()


def _status(graph, task: str) -> str:
    return graph.query("MATCH (t:Task {id: $t}) RETURN t.status", {"t": task}).result_set[0][0]


def _events(graph, kind: str) -> list[list]:
    return graph.query(
        "MATCH (e:Event {kind: $k}) RETURN e.agent, e.text, e.code ORDER BY e.at, e.seq", {"k": kind}
    ).result_set


def _collisions(graph):
    return graph.query(
        "MATCH (x:Collision) RETURN x.kind, x.held_agent, x.owner_agent, x.symbol, x.caller, x.resolution"
    ).result_set


def _plan(graph, agent: Agent, qualnames: list[str]) -> None:
    """The agent has started on these symbols (as an MCP flight plan files them) and has not changed them yet."""
    Airspace(graph).file_plan(agent.agent_id, agent.session, "change", qualnames)


def _reason(out) -> str:
    assert out is not None and out["decision"] == "block", out
    return out["reason"]


def test_stop_allows_when_nothing_depends_on_others(indexed):
    graph, _, b = indexed
    assert b.apply(SLUG_B)

    assert b.stop(sleep=never) is None
    assert _status(graph, b.session) == "landed"
    assert _events(graph, "landed") == [["agent-b", "landed", ""]]


def test_stop_without_a_task_allows(indexed):
    graph, a, _ = indexed
    assert a.stop(sleep=never) is None
    assert graph.query("MATCH (t:Task) RETURN count(t)").result_set == [[0]]


def test_stop_waits_for_active_owner_then_blocks_with_briefing(indexed):
    graph, a, b = indexed
    _plan(graph, a, [SLUGIFY])
    assert b.apply(SLUG_B)

    def a_changes():
        # agent-b is holding while agent-a's pre and post hooks run.
        assert _status(graph, b.session) == "holding"
        assert a.apply(SLUG_A), a.holds

    def a_lands():
        assert a.stop(sleep=never) is None

    t = FakeTime(a_changes, a_lands)
    reason = _reason(b.stop(**t.timing()))

    assert t.sleeps == 2
    assert reason.startswith(f"Airspace: before landing, {SLUGIFY} was changed by agent-a to {NEW_SIG}")
    assert "slugify(value, allow_unicode=False)" in reason
    assert f"The call {CALLER} makes, {B_CALL}, does not fit it." in reason
    # Both agents share this working copy, so the change is already on disk here and the reason says so.
    assert "This working copy already has that change" in reason
    assert chr(0x2014) not in reason and chr(0x2013) not in reason
    # One holding event for the whole wait, then the hold.
    assert _events(graph, "holding") == [["agent-b", "is holding for", "agent-a"]]
    assert ["agent-b", "was held editing", CALLER] in _events(graph, "hold")
    assert _collisions(graph) == [["contract", "agent-b", "agent-a", SLUGIFY, CALLER, "held"]]
    # Blocked means working again; agent-a landed.
    assert _status(graph, b.session) == "active"
    assert _status(graph, a.session) == "landed"
    # The block reason carried the change, so the next tool call does not repeat it.
    assert b.other_tool() is None


def test_stop_does_not_wait_for_holding_agent(indexed):
    graph, a, b = indexed
    _plan(graph, a, [SLUGIFY])
    Airspace(graph).holding(a.session, "agent-b")  # agent-a is itself waiting at its own landing
    assert b.apply(SLUG_B)

    assert b.stop(sleep=never) is None
    assert _status(graph, b.session) == "landed"
    assert _status(graph, a.session) == "holding"


def test_mutual_wait_is_broken(indexed):
    # Each agent calls what the other claims. agent-a stops first and waits; agent-b does not wait for it.
    graph, a, b = indexed
    _plan(graph, a, ["blog.views.post_list"])
    _plan(graph, b, [SLUGIFY])
    a_edit = {"file_path": "blog/views.py", "old_string": 'return "\\n".join(render_post(p) for p in posts)',
              "new_string": 'return "\\n".join(slugify(p.title) for p in posts)'}
    b_edit = {"file_path": "tags/views.py", "old_string": "    return Tag(name).save()\n",
              "new_string": "    return Tag(name).save()\n\n\ndef tag_posts(posts):\n    return post_list(posts)\n"}
    assert a.edit("blog/views.py", "Edit", a_edit), a.holds
    assert b.edit("tags/views.py", "Edit", b_edit), b.holds

    def b_stops():
        assert b.stop(sleep=never) is None

    t = FakeTime(b_stops)
    assert a.stop(**t.timing()) is None
    assert t.sleeps == 1
    assert _status(graph, a.session) == "landed" and _status(graph, b.session) == "landed"


def test_stop_blocks_then_allows_after_fix(indexed):
    graph, a, b = indexed
    assert b.apply(SLUG_B)
    assert a.apply(SLUG_A) and a.stop(sleep=never) is None

    assert B_CALL in _reason(b.stop(sleep=never))

    assert b.edit("blog/views.py", "Edit", FIX), b.holds
    assert b.stop(stop_hook_active=True, sleep=never) is None
    assert _status(graph, b.session) == "landed"
    assert [row[-1] for row in _collisions(graph)] == ["resolved"]


def test_stop_same_violation_with_stop_hook_active_allows(indexed):
    graph, a, b = indexed
    assert b.apply(SLUG_B)
    assert a.apply(SLUG_A) and a.stop(sleep=never) is None

    first = _reason(b.stop(stop_hook_active=True, sleep=never))  # nothing blocked before: blocks
    # agent-b continued and could not fix the call; the same violation does not use up the continuation cap.
    assert b.stop(stop_hook_active=True, sleep=never) is None
    assert _status(graph, b.session) == "landed"
    assert NEW_SIG in first
    # A stop that is not a continuation is checked afresh.
    assert _reason(b.stop(sleep=never)) == first


def test_stop_times_out_and_lands(indexed):
    graph, a, b = indexed
    _plan(graph, a, [SLUGIFY])
    assert b.apply(SLUG_B)

    t = FakeTime()
    assert b.stop(**t.timing(wait_seconds=10.0, poll_seconds=2.0)) is None

    assert t.sleeps == 5
    assert _status(graph, b.session) == "landed"
    assert _events(graph, "holding") == [["agent-b", "is holding for", "agent-a"]]
    assert _events(graph, "landed") == [["agent-b", "landed", ""]]


def test_landed_change_still_holds_a_later_call(indexed):
    # agent-a's change stands after it lands: a call written against the old signature is still held.
    graph, a, b = indexed
    assert a.apply(SLUG_A) and a.stop(sleep=never) is None

    assert b.apply(SLUG_B) is False
    assert NEW_SIG in b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]


def test_agent_that_edits_again_is_active(indexed):
    graph, _, b = indexed
    assert b.apply(SLUG_B) and b.stop(sleep=never) is None
    assert _status(graph, b.session) == "landed"

    assert b.edit("blog/views.py", "Edit", FIX)
    assert _status(graph, b.session) == "active"


def test_state_reports_holding_and_landed(indexed):
    graph, a, b = indexed
    _plan(graph, a, [SLUGIFY])
    assert b.apply(SLUG_B) and b.stop(sleep=never, wait_seconds=0.0) is None
    airspace = Airspace(graph)
    airspace.holding(a.session, "agent-b")

    agents = {x["id"]: x for x in airspace.state()["agents"]}
    assert agents["agent-a"]["status"] == "holding" and agents["agent-a"]["claims"] == [SLUGIFY]
    assert agents["agent-b"]["status"] == "landed"
    # Both stay on the radar until active agents replace them.
    assert {x["id"] for x in airspace.radar()["agents"]} == {"agent-a", "agent-b"}


def test_edited_files_are_recorded_once(indexed):
    graph, _, b = indexed
    assert b.apply(SLUG_B)  # two edits to one file

    assert Airspace(graph).edited_files(b.session) == ["blog/views.py"]


def test_reading_the_callee_file_makes_a_lander_wait(indexed):
    """agent-a has only read utils/text.py, with no edit or plan yet. agent-b still waits for it at landing."""
    graph, a, b = indexed
    a.other_tool("Read", {"file_path": str(a.repo / "utils/text.py")})
    assert b.apply(SLUG_B)

    def a_changes():
        assert _status(graph, b.session) == "holding"
        assert a.apply(SLUG_A), a.holds

    def a_lands():
        assert a.stop(sleep=never) is None

    t = FakeTime(a_changes, a_lands)
    reason = _reason(b.stop(**t.timing()))
    assert NEW_SIG in reason and B_CALL in reason
    assert _events(graph, "holding") == [["agent-b", "is holding for", "agent-a"]]


def test_reading_an_unrelated_file_does_not_make_a_lander_wait(indexed):
    graph, a, b = indexed
    a.other_tool("Read", {"file_path": str(a.repo / "tags/models.py")})
    assert b.apply(SLUG_B)
    assert b.stop(sleep=never) is None
    assert _status(graph, b.session) == "landed"


def test_hold_reason_states_whether_the_change_is_in_this_working_copy(tmp_path, blog_repo):
    from airspace.admission.text import BRANCH_NOTE
    from airspace.hooks.handlers import _localize

    text = f"Airspace hold: ... {BRANCH_NOTE}"
    change = [(SLUGIFY, NEW_SIG)]
    assert "is not in this working copy yet" in _localize(text, blog_repo, change)
    p = blog_repo / "utils/text.py"
    p.write_text(p.read_text().replace("def slugify(value, allow_unicode=False):", f"def {NEW_SIG}:"))
    assert "This working copy already has that change" in _localize(text, blog_repo, change)
    # A removal is on disk when the symbol is gone.
    assert "already has" in _localize(text, blog_repo, [("utils.text.no_such_function", "")])


def test_prompt_names_become_interest_that_a_lander_waits_for(indexed):
    """agent-a has only been given its task. Its prompt names utils/text.py and slugify, so agent-b waits."""
    from airspace.hooks.handlers import handle_prompt

    graph, a, b = indexed
    prompt = "In utils/text.py, make the unicode option of slugify keyword-only: slugify(value, *, unicode=False)."
    handle_prompt({"session_id": a.session, "cwd": str(a.repo), "prompt": prompt}, a.deps, a.env)
    assert b.apply(SLUG_B)

    def a_changes():
        assert _status(graph, b.session) == "holding"
        assert a.apply(SLUG_A), a.holds

    def a_lands():
        assert a.stop(sleep=never) is None

    t = FakeTime(a_changes, a_lands)
    assert NEW_SIG in _reason(b.stop(**t.timing()))


def test_prompt_interest_ignores_short_common_names(indexed):
    from airspace.admission.engine import Airspace

    graph, a, _ = indexed
    noted = Airspace(graph).note_interest_from_text(a.agent_id, a.session, "save the url and get it")
    assert noted == []
    noted = Airspace(graph).note_interest_from_text(a.agent_id, a.session, "Rename Post.get_absolute_url to Post.url")
    assert noted == ["blog/models.py"]


def test_rename_is_detected_and_named_in_the_landing_hold(indexed):
    """agent-a renames Post.get_absolute_url to Post.url; agent-b's new call to the old name is told the new one."""
    graph, a, b = indexed
    rename_a, call_b = REFS["rename-absolute-url"]
    assert a.apply(rename_a), a.holds
    changes = graph.query("MATCH (cc:ContractChange) RETURN cc.qualname, cc.renamed_to, cc.renamed_sig").result_set
    assert ["blog.models.Post.get_absolute_url", "blog.models.Post.url", "url(self)"] in changes
    b.apply(call_b)
    reasons = [h["hookSpecificOutput"]["permissionDecisionReason"] for h in b.holds]
    out = b.stop(sleep=never)
    if out is not None:
        reasons.append(out["reason"])
    assert any("renamed to blog.models.Post.url (url(self))" in r for r in reasons), reasons
