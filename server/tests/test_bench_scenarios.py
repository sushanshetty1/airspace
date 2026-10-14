"""Each benchmark task set through the real hooks, indexer and engine on a fixture copy, with the reference edits.

Calls after the change: agent-a's reference change goes through first, then agent-b's natural edit is held.
Caller first: agent-b's edit lands first, then agent-a's change holds it, and agent-b's next tool call of any kind
gets the briefing. The behaviour set keeps every signature, so nothing is held: that is a documented limit.
agent-b finishes first: agent-b's whole patch goes through and agent-b stops before agent-a's change. Its Stop hook
holds while agent-a still claims a contract agent-b calls, then blocks the landing with the change.
"""

import pytest

from airspace.admission.engine import Airspace
from airspace.graph.db import repo_graph
from bench_refs import BEHAVIOUR_SETS, REFS, SIGNATURE_SETS, Agent, FakeTime, never

# A's new interface, as B's briefing or hold must state it.
NEW_INTERFACE = {
    "slugify-keyword-only": "slugify(value, *, unicode=False)",
    "truncate-words-limit": "truncate_words(text, *, limit=30)",
    "rename-absolute-url": "renamed or removed by agent-a",
    "render-post-show-body": "render_post(post, *, show_body)",
    "post-requires-author": "__init__(self, title, body, author)",
}
CHANGED_SYMBOL = {
    "slugify-keyword-only": "utils.text.slugify",
    "truncate-words-limit": "utils.text.truncate_words",
    "rename-absolute-url": "blog.models.Post.get_absolute_url",
    "render-post-show-body": "blog.views.render_post",
    "post-requires-author": "blog.models.Post.__init__",
    "tag-save-returns-none": "tags.models.Tag.save",
}
# B's call as B writes it, and the caller it sits in.
B_CALL = {
    "slugify-keyword-only": ("blog.views.render_post", "slugify(post.title, allow_unicode=True)"),
    "truncate-words-limit": ("tags.views.tag_label", "truncate_words(name, 3)"),
    "rename-absolute-url": ("blog.feeds.LatestPosts.item_link", "post.get_absolute_url()"),
    "render-post-show-body": ("blog.index.render_index", "render_post(p)"),
    "post-requires-author": ("tests.test_feeds.test_item_description", "Post('Hi', 'x')"),
}


@pytest.fixture
def indexed(db, blog_repo, monkeypatch):
    from airspace.hooks.handlers import default_deps
    from airspace.indexer.writer import index_repo

    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    graph = repo_graph(db, blog_repo)
    index_repo(graph, blog_repo)
    deps = default_deps()
    a = Agent(blog_repo, "agent-a", "sess-aaaa", deps)
    b = Agent(blog_repo, "agent-b", "sess-bbbb", deps)
    yield graph, a, b
    graph.delete()


def _collisions(graph):
    return graph.query(
        "MATCH (x:Collision) RETURN x.kind, x.held_agent, x.owner_agent, x.symbol, x.resolution ORDER BY x.at"
    ).result_set


@pytest.mark.parametrize("set_id", SIGNATURE_SETS)
def test_call_after_the_change_is_held(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]

    assert a.apply(ref_a), a.holds
    assert b.apply(ref_b) is False

    reason = b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert NEW_INTERFACE[set_id] in reason and "agent-a" in reason
    assert chr(0x2014) not in reason and chr(0x2013) not in reason
    assert _collisions(graph) == [["contract", "agent-b", "agent-a", CHANGED_SYMBOL[set_id], "held"]]
    # Recorded once, at agent-a's pre hook, although the post hook saw the same change.
    count = graph.query(
        "MATCH (cc:ContractChange {qualname: $q}) RETURN count(cc)", {"q": CHANGED_SYMBOL[set_id]}
    ).result_set[0][0]
    assert count == 1


@pytest.mark.parametrize("set_id", SIGNATURE_SETS)
def test_held_call_stays_held_on_retry(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]
    a.apply(ref_a)
    b.apply(ref_b)

    # The same call again: still held, still one collision.
    assert b.apply(ref_b) is False
    assert len(b.holds) == 2
    assert len(_collisions(graph)) == 1


# Caller first. The rename set is left out: post.get_absolute_url() goes through an object of unknown type, so the
# stored graph has no edge for it (it never guesses) and nothing links agent-b's call to the rename until agent-b
# edits again. That is a documented limit.
CALLER_FIRST_SETS = [s for s in SIGNATURE_SETS if s != "rename-absolute-url"]


@pytest.mark.parametrize("set_id", CALLER_FIRST_SETS)
def test_caller_first_is_briefed_on_the_next_tool_call(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]

    assert b.apply(ref_b), b.holds
    assert a.apply(ref_a), a.holds

    out = b.other_tool("Bash", {"command": "python -m pytest -q"})
    assert out is not None
    context = out["hookSpecificOutput"]["additionalContext"]
    assert NEW_INTERFACE[set_id] in context and "agent-a" in context and "no longer fits" in context
    assert _collisions(graph) == [["contract", "agent-b", "agent-a", CHANGED_SYMBOL[set_id], "held"]]
    # Delivered once.
    assert b.other_tool() is None


@pytest.mark.parametrize("set_id", BEHAVIOUR_SETS)
def test_behaviour_set_is_not_held(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]

    assert a.apply(ref_a), a.holds
    assert b.apply(ref_b), b.holds
    assert b.other_tool() is None
    assert _collisions(graph) == []


@pytest.mark.parametrize("set_id", BEHAVIOUR_SETS)
def test_behaviour_set_caller_first_is_not_held(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]

    assert b.apply(ref_b), b.holds
    assert a.apply(ref_a), a.holds
    assert b.other_tool() is None
    assert _collisions(graph) == []


def _landing_status(graph, task):
    return graph.query("MATCH (t:Task {id: $t}) RETURN t.status", {"t": task}).result_set[0][0]


@pytest.mark.parametrize("set_id", SIGNATURE_SETS)
def test_b_finishes_first_holds_then_is_blocked_at_landing(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]
    # agent-a has started on the contract (its flight plan claims it) and has not changed it yet.
    Airspace(graph).file_plan("agent-a", a.session, "change", [CHANGED_SYMBOL[set_id]])
    assert b.apply(ref_b), b.holds

    def a_changes_and_lands():
        assert _landing_status(graph, b.session) == "holding"
        assert a.apply(ref_a), a.holds
        assert a.stop(sleep=never) is None

    t = FakeTime(a_changes_and_lands)
    out = b.stop(sleep=t.sleep, clock=t.clock)

    assert t.sleeps == 1
    assert out is not None and out["decision"] == "block", out
    reason = out["reason"]
    caller, call = B_CALL[set_id]
    assert NEW_INTERFACE[set_id] in reason and CHANGED_SYMBOL[set_id] in reason
    assert f"The call {caller} makes, {call}," in reason
    assert chr(0x2014) not in reason and chr(0x2013) not in reason
    assert _collisions(graph) == [["contract", "agent-b", "agent-a", CHANGED_SYMBOL[set_id], "held"]]
    assert _landing_status(graph, a.session) == "landed"


@pytest.mark.parametrize("set_id", SIGNATURE_SETS)
def test_b_stops_after_the_change_is_blocked_at_landing(indexed, set_id):
    # agent-b's edits land first, agent-a's change follows, and agent-b's next and last action is to stop.
    # This includes the rename set: the call through an object is resolved at landing as clearance resolves it.
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]
    assert b.apply(ref_b), b.holds
    assert a.apply(ref_a), a.holds

    # agent-a is still flying with its claim on the contract, so agent-b holds until agent-a lands. (A renamed
    # method is gone from the code graph, and so is the claim on it: nothing to wait for.)
    t = FakeTime(lambda: a.stop(sleep=never))
    out = b.stop(sleep=t.sleep, clock=t.clock)

    assert t.sleeps == (0 if set_id == "rename-absolute-url" else 1)
    assert out is not None and out["decision"] == "block", out
    assert NEW_INTERFACE[set_id] in out["reason"] and B_CALL[set_id][1] in out["reason"]
    assert _collisions(graph) == [["contract", "agent-b", "agent-a", CHANGED_SYMBOL[set_id], "held"]]


@pytest.mark.parametrize("set_id", BEHAVIOUR_SETS)
def test_behaviour_set_b_finishes_first_lands(indexed, set_id):
    graph, a, b = indexed
    ref_a, ref_b = REFS[set_id]
    Airspace(graph).file_plan("agent-a", a.session, "change", [CHANGED_SYMBOL[set_id]])
    assert b.apply(ref_b), b.holds

    def a_changes_and_lands():
        assert a.apply(ref_a), a.holds
        assert a.stop(sleep=never) is None

    t = FakeTime(a_changes_and_lands)
    assert b.stop(sleep=t.sleep, clock=t.clock) is None
    assert t.sleeps == 1
    assert _landing_status(graph, b.session) == "landed"
    assert _collisions(graph) == []
