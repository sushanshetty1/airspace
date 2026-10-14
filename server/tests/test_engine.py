"""Admission engine: leases, cones, deterministic clearance, briefings and collisions on a seeded graph."""

import pytest

from airspace.admission.engine import Airspace
from airspace.types import SignatureChange
from helpers import seed_blog_graph

SLUGIFY = "utils.text.slugify"
OLD_SIG = "slugify(value, allow_unicode=False)"
NEW_SIG = "slugify(value, *, unicode=False)"
SLUGIFY_CHANGE = SignatureChange(SLUGIFY, OLD_SIG, NEW_SIG)
NEW_CALL = ("blog.views.render_post", SLUGIFY)


class FakeClock:
    """A settable clock so lease expiry is tested without sleeping."""

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


def _claims(graph, task_id):
    return graph.query(
        "MATCH (:Task {id: $task})-[c:CLAIMS]->(s:Symbol) RETURN s.qualname, c.fence ORDER BY s.qualname",
        {"task": task_id},
    ).result_set


def test_file_plan_builds_cone(airspace):
    cone = airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    assert {
        "blog.models.Post.save",
        "tags.models.Tag.save",
        "tests.test_text.test_slugify",
        "tests.test_models.test_post_save",
        "tags.views.tag_create",
    } <= set(cone)
    assert SLUGIFY not in cone
    assert cone == sorted(cone)
    assert airspace.agent_of("task-a") == "agent-a"


def test_cone_excludes_every_claimed_symbol(airspace):
    # Post.save calls slugify, so it would enter the cone if claims were not excluded.
    cone = airspace.file_plan("agent-a", "task-a", "slugs", [SLUGIFY, "blog.models.Post.save"])
    assert "blog.models.Post.save" not in cone
    assert "tests.test_models.test_post_save" in cone


def test_claim_skips_unknown_symbols(airspace):
    airspace.ensure_task("agent-a", "task-a")
    assert airspace.claim("task-a", [SLUGIFY, "no.such.symbol"]) == [SLUGIFY]


def test_own_claim_is_cleared_and_renewed(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    assert _claims(graph, "task-a") == [[SLUGIFY, 1]]

    verdict = airspace.check_edit("task-a", [SLUGIFY], [])

    assert verdict.kind == "cleared"
    assert verdict.reason == ""
    assert _claims(graph, "task-a") == [[SLUGIFY, 2]]


def test_other_live_claim_holds(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")

    verdict = airspace.check_edit("task-b", [SLUGIFY], [])

    assert verdict.kind == "hold"
    assert verdict.other_agent == "agent-a"
    assert verdict.path == [SLUGIFY]
    assert SLUGIFY in verdict.reason and "agent-a" in verdict.reason
    kind = graph.query(
        "MATCH (x:Collision {id: $id}) RETURN x.kind, x.resolution", {"id": verdict.collision_id}
    ).result_set
    assert kind == [["claim", "held"]]
    assert _claims(graph, "task-b") == []


def test_expired_claim_does_not_hold(airspace, graph, clock):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")
    clock.now += 901

    verdict = airspace.check_edit("task-b", [SLUGIFY], [])

    assert verdict.kind == "cleared"
    assert _claims(graph, "task-b") == [[SLUGIFY, 1]]


def test_new_call_into_changed_contract_holds_then_clears(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    assert len(airspace.record_changes("task-a", [SLUGIFY_CHANGE])) == 1
    airspace.ensure_task("agent-b", "task-b", "render post titles")

    verdict = airspace.check_edit("task-b", ["blog.views.render_post"], [NEW_CALL])

    assert verdict.kind == "hold"
    for fact in (SLUGIFY, "agent-a", NEW_SIG, OLD_SIG, "blog.views.render_post"):
        assert fact in verdict.reason
    assert "—" not in verdict.reason and "–" not in verdict.reason
    assert verdict.path == ["blog.views.render_post", SLUGIFY]
    assert verdict.other_agent == "agent-a"
    assert len(verdict.briefings) == 1
    b = verdict.briefings[0]
    assert (b.symbol, b.old_signature, b.new_signature, b.from_agent) == (SLUGIFY, OLD_SIG, NEW_SIG, "agent-a")

    retry = airspace.check_edit("task-b", ["blog.views.render_post"], [NEW_CALL])
    assert retry.kind == "cleared"
    assert retry.briefings == []


def test_own_contract_change_does_not_hold(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])

    verdict = airspace.check_edit("task-a", ["blog.views.render_post"], [NEW_CALL])

    assert verdict.kind == "cleared"


def test_collision_node_written_on_hold(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.ensure_task("agent-b", "task-b")

    verdict = airspace.check_edit("task-b", ["blog.views.render_post"], [NEW_CALL])

    rows = graph.query(
        """MATCH (x:Collision {id: $id})-[:BETWEEN]->(t:Task)
        MATCH (x)-[:AT]->(s:Symbol)
        RETURN x.kind, t.id, s.qualname ORDER BY t.id""",
        {"id": verdict.collision_id},
    ).result_set
    assert rows == [["contract", "task-a", SLUGIFY], ["contract", "task-b", SLUGIFY]]


def test_check_edit_on_unknown_task_registers_it(airspace):
    verdict = airspace.check_edit("session-1", ["blog.views.post_list"], [])

    assert verdict.kind == "cleared"
    assert airspace.agent_of("session-1") == "session-1"


def test_explain_returns_path_and_empty_when_none(airspace):
    assert airspace.explain("tests.test_models.test_post_save", SLUGIFY) == [
        "tests.test_models.test_post_save",
        "blog.models.Post.save",
        SLUGIFY,
    ]
    assert airspace.explain(SLUGIFY, "utils.text.truncate_words") == []
    assert airspace.explain("no.such.symbol", SLUGIFY) == []


def test_pending_briefings_for_dependents(airspace):
    airspace.file_plan("agent-c", "task-c", "post saving", ["blog.models.Post.save"])
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])

    briefings = airspace.pending_briefings("task-c")

    assert len(briefings) == 1
    assert (briefings[0].symbol, briefings[0].from_agent, briefings[0].new_signature) == (SLUGIFY, "agent-a", NEW_SIG)
    assert airspace.pending_briefings("task-c") == []
    assert airspace.pending_briefings("task-a") == []


def test_hold_delivers_briefing_so_it_is_not_pending_again(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.file_plan("agent-c", "task-c", "post saving", ["blog.models.Post.save"])

    assert airspace.check_edit("task-c", ["blog.models.Post.save"], [("blog.models.Post.save", SLUGIFY)]).kind == "hold"
    assert airspace.pending_briefings("task-c") == []


def test_record_changes_skips_unknown_symbols(airspace):
    airspace.ensure_task("agent-a", "task-a")
    ids = airspace.record_changes("task-a", [SLUGIFY_CHANGE, SignatureChange("no.such.symbol", "f()", "f(x)")])
    assert len(ids) == 1 and len(ids[0]) == 32


def test_release_frees_claims(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")
    assert airspace.claim("task-b", [SLUGIFY]) == []

    airspace.release("task-a")

    assert _claims(graph, "task-a") == []
    assert airspace.refresh_cone("task-a") == []
    status = graph.query("MATCH (t:Task {id: 'task-a'}) RETURN t.status").result_set[0][0]
    assert status == "released"
    assert airspace.claim("task-b", [SLUGIFY]) == [SLUGIFY]


def test_released_task_changes_do_not_hold(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.release("task-a")
    airspace.ensure_task("agent-b", "task-b")

    verdict = airspace.check_edit("task-b", ["blog.views.render_post"], [NEW_CALL])

    assert verdict.kind == "cleared"


def test_messages_are_factual_and_dash_free():
    from airspace.admission import text
    from airspace.types import Briefing

    hold = text.contract_hold(SLUGIFY, "blog.views.render_post", "agent-a", OLD_SIG, NEW_SIG)
    assert "Path: blog.views.render_post -> utils.text.slugify" in hold
    claim = text.claim_hold(SLUGIFY, "agent-a", "task-a")
    assert SLUGIFY in claim and "agent-a" in claim and "released" in claim
    brief = text.briefing_text([Briefing("x", SLUGIFY, OLD_SIG, NEW_SIG, "agent-a")])
    for fact in (SLUGIFY, OLD_SIG, NEW_SIG, "agent-a"):
        assert fact in brief
    assert text.briefing_text([]) == ""
    for msg in (hold, claim, brief):
        assert "—" not in msg and "–" not in msg
