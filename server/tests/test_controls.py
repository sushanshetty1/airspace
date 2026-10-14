"""Per-agent controls from Tower: pause, resume, messages, releasing holds, resolution and the event log."""

import pytest

from airspace.admission.engine import Airspace
from airspace.hooks.handlers import Deps, handle_pre
from airspace.types import EditAnalysis, SignatureChange
from helpers import seed_blog_graph

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"
OLD_SIG = "slugify(value, allow_unicode=False)"
NEW_SIG = "slugify(value, *, unicode=False)"
SLUGIFY_CHANGE = SignatureChange(SLUGIFY, OLD_SIG, NEW_SIG)
NEW_CALL = (RENDER, SLUGIFY)
PAUSED_REASON = "Airspace hold: agent-b is paused from Tower. Its edits are held until it is resumed."
EVENT_KEYS = {"id", "at", "kind", "agent", "task", "text", "code"}


class FakeClock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def airspace(graph, clock):
    seed_blog_graph(graph)
    return Airspace(graph, lease_seconds=900, cone_depth=2, clock=clock)


def _resolution(graph, cid):
    return graph.query("MATCH (x:Collision {id: $id}) RETURN x.resolution", {"id": cid}).result_set[0][0]


def _contract_hold(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.ensure_task("agent-b", "task-b")
    verdict = airspace.check_edit("task-b", [RENDER], [NEW_CALL])
    assert verdict.kind == "hold"
    return verdict


def _deps(airspace, analysis):
    return Deps(
        airspace=lambda root: airspace,
        analyze=lambda root, tool, tool_input, known: analysis,
        known=lambda root: set(),
        reindex=lambda root, rel: [],
    )


def _payload(root, session):
    return {
        "session_id": session,
        "cwd": str(root),
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(root / "blog/views.py"), "old_string": "a", "new_string": "b"},
    }


def test_pause_holds_and_resume_clears(airspace, graph):
    airspace.ensure_task("agent-b", "task-b")

    airspace.pause("agent-b")
    held = airspace.check_edit("task-b", ["utils.text.truncate_words"], [])

    assert held.kind == "hold"
    assert held.reason == PAUSED_REASON
    assert held.collision_id is None
    assert graph.query("MATCH (a:Agent {id: 'agent-b'}) RETURN a.paused").result_set == [[True]]

    airspace.resume("agent-b")
    assert airspace.check_edit("task-b", ["utils.text.truncate_words"], []).kind == "cleared"
    assert graph.query("MATCH (a:Agent {id: 'agent-b'}) RETURN a.paused").result_set == [[False]]


def test_pause_unknown_agent_is_noop(airspace, graph):
    airspace.pause("agent-zz")
    airspace.resume("agent-zz")
    assert graph.query("MATCH (a:Agent) RETURN count(a)").result_set == [[0]]
    assert airspace.events() == []


def test_message_is_included_in_hold_reason(airspace, tmp_path):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "sess-b")
    mid = airspace.message("agent-b", "slugify is mid change, wait for agent-a")
    assert len(mid) == 32

    analysis = EditAnalysis(file="utils/text.py", touched=[SLUGIFY], new_calls=[], parse_ok=True)
    out = handle_pre(_payload(tmp_path, "sess-b"), _deps(airspace, analysis), {"AIRSPACE_AGENT": "agent-b"})

    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"].endswith("\nMessage from Tower: slugify is mid change, wait for agent-a")
    assert airspace.pending_messages("agent-b") == []


def test_message_delivered_once_on_cleared(airspace, graph, tmp_path):
    airspace.ensure_task("agent-b", "sess-b")
    airspace.message("agent-b", "first")
    airspace.message("agent-b", "second")
    analysis = EditAnalysis(file="blog/views.py", touched=[RENDER], new_calls=[], parse_ok=True)
    deps = _deps(airspace, analysis)
    env = {"AIRSPACE_AGENT": "agent-b"}

    out = handle_pre(_payload(tmp_path, "sess-b"), deps, env)

    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx == "Message from Tower: first\nMessage from Tower: second"
    assert handle_pre(_payload(tmp_path, "sess-b"), deps, env) is None
    delivered = graph.query(
        "MATCH (m:Message)-[:DELIVERED]->(t:Task) RETURN m.text, t.id ORDER BY m.text"
    ).result_set
    assert delivered == [["first", "sess-b"], ["second", "sess-b"]]


def test_pending_messages_without_task_delivers_to_newest_active_task(airspace, graph, clock):
    airspace.ensure_task("agent-b", "sess-b")
    clock.now += 1
    airspace.ensure_task("agent-b", "agent-b:mcp")
    airspace.message("agent-b", "hello")

    assert airspace.pending_messages("agent-b") == ["hello"]
    assert airspace.pending_messages("agent-b") == []
    delivered = graph.query("MATCH (:Message)-[d:DELIVERED]->(t:Task) RETURN t.id, d.at").result_set
    assert delivered == [["agent-b:mcp", clock.now]]


def test_message_to_unknown_agent_is_noop(airspace, graph):
    assert airspace.message("agent-zz", "hello") == ""
    assert graph.query("MATCH (m:Message) RETURN count(m)").result_set == [[0]]
    assert airspace.pending_messages("agent-zz") == []


def test_release_contract_collision_clears_retry(airspace, graph):
    verdict = _contract_hold(airspace)

    assert airspace.release_collision(verdict.collision_id) is True

    assert _resolution(graph, verdict.collision_id) == "released"
    briefed = graph.query("MATCH (:ContractChange)-[:BRIEFED]->(t:Task) RETURN t.id").result_set
    assert briefed == [["task-b"]]
    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL]).kind == "cleared"
    # A cleared retry does not overwrite a release.
    assert _resolution(graph, verdict.collision_id) == "released"
    assert airspace.release_collision(verdict.collision_id) is False
    assert airspace.release_collision("no-such-collision") is False
    released = [e for e in airspace.events() if e["kind"] == "released"]
    assert [(e["agent"], e["task"], e["text"], e["code"]) for e in released] == [
        ("agent-b", "task-b", "had a hold released at", SLUGIFY)
    ]


def test_release_claim_collision_grants_one_pass(airspace, graph, clock):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")
    held = airspace.check_edit("task-b", [SLUGIFY], [])
    assert held.kind == "hold"

    assert airspace.release_collision(held.collision_id) is True
    until = graph.query("MATCH (:Task {id: 'task-b'})-[p:PASS]->(:Symbol {qualname: $q}) RETURN p.until", {"q": SLUGIFY})
    assert until.result_set == [[clock.now + 900]]

    assert airspace.check_edit("task-b", [SLUGIFY], []).kind == "cleared"
    assert graph.query("MATCH ()-[p:PASS]->() RETURN count(p)").result_set == [[0]]
    again = airspace.check_edit("task-b", [SLUGIFY], [])
    assert again.kind == "hold" and again.collision_id != held.collision_id
    assert _resolution(graph, held.collision_id) == "released"


def test_pass_is_kept_when_the_edit_is_held_elsewhere(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "two symbols", [SLUGIFY, "utils.text.truncate_words"])
    airspace.ensure_task("agent-b", "task-b")
    held = airspace.check_edit("task-b", [SLUGIFY], [])
    airspace.release_collision(held.collision_id)

    assert airspace.check_edit("task-b", [SLUGIFY, "utils.text.truncate_words"], []).kind == "hold"
    assert graph.query("MATCH ()-[p:PASS]->() RETURN count(p)").result_set == [[1]]


def test_expired_pass_does_not_skip(airspace, clock):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")
    held = airspace.check_edit("task-b", [SLUGIFY], [])
    airspace.release_collision(held.collision_id)
    clock.now += 600
    airspace.claim("task-a", [SLUGIFY])  # renews agent-a's lease past the pass
    clock.now += 400

    assert airspace.check_edit("task-b", [SLUGIFY], []).kind == "hold"


def test_cleared_retry_resolves_collision(airspace, graph):
    verdict = _contract_hold(airspace)

    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL]).kind == "cleared"

    assert _resolution(graph, verdict.collision_id) == "resolved"
    resolved = [e for e in airspace.events() if e["kind"] == "resolved"]
    assert [(e["agent"], e["text"], e["code"]) for e in resolved] == [("agent-b", "cleared the collision at", SLUGIFY)]


def test_unrelated_cleared_edit_does_not_resolve(airspace, graph):
    verdict = _contract_hold(airspace)

    assert airspace.check_edit("task-b", ["blog.views.post_list"], []).kind == "cleared"

    assert _resolution(graph, verdict.collision_id) == "held"


def test_events_written_in_order_with_texts(airspace, clock):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    clock.now += 1
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    clock.now += 1
    airspace.ensure_task("agent-b", "task-b")
    airspace.check_edit("task-b", [RENDER], [NEW_CALL])
    # Same timestamp from here on: insertion order still decides.
    airspace.check_edit("task-b", [RENDER], [NEW_CALL])
    airspace.check_edit("task-b", [], [])  # touches nothing: no event
    airspace.pause("agent-a")
    airspace.pause("agent-a")  # already paused: no second event
    airspace.message("agent-a", "hold on")
    airspace.resume("agent-a")

    events = airspace.events()

    assert all(set(e) == EVENT_KEYS for e in events)
    assert [(e["kind"], e["agent"], e["text"], e["code"]) for e in events] == [
        ("plan", "agent-a", "filed a plan for", SLUGIFY),
        ("contract", "agent-a", "changed the signature of", SLUGIFY),
        ("hold", "agent-b", "was held editing", RENDER),
        ("briefed", "agent-b", "got the new signature of", SLUGIFY),
        ("cleared", "agent-b", "was cleared to edit", RENDER),
        ("resolved", "agent-b", "cleared the collision at", SLUGIFY),
        ("paused", "agent-a", "was paused from", "Tower"),
        ("message", "agent-a", "got a message from", "Tower"),
        ("resumed", "agent-a", "was resumed from", "Tower"),
    ]
    assert [e["task"] for e in events[:6]] == ["task-a", "task-a", "task-b", "task-b", "task-b", "task-b"]
    assert [e["at"] for e in events[:3]] == [1000.0, 1001.0, 1002.0]
    assert len({e["id"] for e in events}) == len(events)

    assert [e["kind"] for e in airspace.events(since=1001.0)] == [
        "hold", "briefed", "cleared", "resolved", "paused", "message", "resumed",
    ]
    assert [e["kind"] for e in airspace.events(limit=2)] == ["plan", "contract"]


def test_event_texts_are_dash_free(airspace):
    _contract_hold(airspace)
    for e in airspace.events():
        assert chr(0x2014) not in e["text"] and chr(0x2013) not in e["text"]
