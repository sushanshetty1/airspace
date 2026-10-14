"""Admission engine: leases, cones, deterministic clearance, briefings and collisions on a seeded graph."""

import pytest

from airspace.admission.engine import Airspace
from airspace.types import CallSite, SignatureChange
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
    assert "\u2014" not in verdict.reason and "\u2013" not in verdict.reason
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
    paused = text.paused_hold("agent-x")
    assert paused == "Airspace hold: agent-x is paused from Tower. Its edits are held until it is resumed."
    for msg in (hold, claim, brief, paused):
        assert "\u2014" not in msg and "\u2013" not in msg


def test_same_agent_tasks_never_collide(airspace, graph):
    # The hooks fly a task per Claude session and MCP flies "<agent>:mcp": both belong to agent-a.
    airspace.file_plan("agent-a", "agent-a:mcp", "change slugify", [SLUGIFY])
    airspace.record_changes("agent-a:mcp", [SLUGIFY_CHANGE])
    airspace.file_plan("agent-a", "sess-a", "post saving", ["blog.models.Post.save"])
    airspace.ensure_task("agent-b", "task-b")

    assert airspace.check_edit("sess-a", [SLUGIFY], []).kind == "cleared"
    assert airspace.check_edit("sess-a", ["blog.views.render_post"], [NEW_CALL]).kind == "cleared"
    assert airspace.claim("sess-a", [SLUGIFY]) == [SLUGIFY]
    assert airspace.pending_briefings("sess-a") == []
    assert graph.query("MATCH (x:Collision) RETURN count(x)").result_set == [[0]]

    # Another agent is still held by either task's claim.
    assert airspace.check_edit("task-b", [SLUGIFY], []).kind == "hold"
    assert airspace.claim("task-b", ["blog.models.Post.save"]) == []


def test_collision_records_both_sides(airspace, graph):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.ensure_task("agent-b", "task-b")
    cid = airspace.check_edit("task-b", ["blog.views.render_post"], [NEW_CALL]).collision_id

    verdict_rows = graph.query(
        """MATCH (x:Collision {id: $id})
        RETURN x.held_agent, x.held_task, x.owner_agent, x.owner_task, x.symbol, x.caller, x.old_sig, x.new_sig,
               x.resolution""",
        {"id": cid},
    ).result_set
    assert verdict_rows == [
        ["agent-b", "task-b", "agent-a", "task-a", SLUGIFY, "blog.views.render_post", OLD_SIG, NEW_SIG, "held"]
    ]


# Call shapes: a call is checked against the new signature, every time.

RENDER = "blog.views.render_post"
OLD_STYLE = {SLUGIFY: [CallSite(RENDER, 2, (), False, False)]}  # slugify(post.title, True)
NEW_STYLE = {SLUGIFY: [CallSite(RENDER, 1, ("unicode",), False, False)]}  # slugify(post.title, unicode=True)


def _slugify_changed(airspace):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    airspace.ensure_task("agent-b", "task-b")


def _collisions(graph):
    return graph.query(
        "MATCH (x:Collision) RETURN x.kind, x.held_agent, x.owner_agent, x.symbol, x.caller, x.new_sig, x.resolution"
    ).result_set


def test_repeated_incompatible_call_stays_held(airspace, graph):
    _slugify_changed(airspace)

    first = airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE)
    second = airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE)

    assert first.kind == "hold" and second.kind == "hold"
    assert len(first.briefings) == 1 and second.briefings == []
    for verdict in (first, second):
        for fact in (SLUGIFY, "agent-a", NEW_SIG, RENDER):
            assert fact in verdict.reason
    assert first.reason == second.reason
    # One collision, held twice.
    assert second.collision_id == first.collision_id
    assert len(_collisions(graph)) == 1
    assert [e["kind"] for e in airspace.events() if e["agent"] == "agent-b"] == ["hold", "briefed", "hold"]


def test_compatible_call_clears_without_briefing(airspace, graph):
    _slugify_changed(airspace)

    verdict = airspace.check_edit("task-b", [RENDER], [NEW_CALL], NEW_STYLE)

    assert verdict.kind == "cleared"
    assert _collisions(graph) == []


def test_fitting_retry_resolves_and_clears(airspace, graph):
    _slugify_changed(airspace)
    held = airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE)

    # Touching the caller again without fixing the call does not resolve the collision.
    assert airspace.check_edit("task-b", [RENDER], [], {}).kind == "cleared"
    assert _collisions(graph)[0][-1] == "held"

    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], NEW_STYLE).kind == "cleared"
    rows = graph.query("MATCH (x:Collision {id: $id}) RETURN x.resolution", {"id": held.collision_id}).result_set
    assert rows == [["resolved"]]


def test_shapes_for_other_callers_fall_back_to_briefing_once(airspace):
    _slugify_changed(airspace)
    other_caller = {SLUGIFY: [CallSite("blog.views.post_list", 2, (), False, False)]}

    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], other_caller).kind == "hold"
    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], other_caller).kind == "cleared"


def test_released_shape_hold_lets_the_call_through(airspace):
    _slugify_changed(airspace)
    held = airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE)

    assert airspace.release_collision(held.collision_id) is True

    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE).kind == "cleared"


def test_latest_change_decides(airspace, clock):
    _slugify_changed(airspace)
    clock.now += 1
    airspace.record_changes("task-a", [SignatureChange(SLUGIFY, NEW_SIG, "slugify(value, flag=False)")])

    # slugify(post.title, True) fits the latest signature again.
    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], OLD_STYLE).kind == "cleared"
    assert airspace.check_edit("task-b", [RENDER], [NEW_CALL], NEW_STYLE).kind == "hold"


def test_removed_symbol_holds_callers_engine(airspace):
    url = "blog.models.Post.get_absolute_url"
    airspace.ensure_task("agent-a", "task-a")
    airspace.record_changes("task-a", [SignatureChange(url, "get_absolute_url(self)", "")])
    airspace.ensure_task("agent-b", "task-b")
    link = "blog.feeds.LatestPosts.item_link"

    verdict = airspace.check_edit("task-b", [link], [(link, url)], {url: [CallSite(link, 0, (), False, True)]})

    assert verdict.kind == "hold"
    assert "removed by agent-a" in verdict.reason and url in verdict.reason and link in verdict.reason
    assert "—" not in verdict.reason and "–" not in verdict.reason


def test_record_changes_skips_a_repeat(airspace, graph, clock):
    airspace.ensure_task("agent-a", "task-a")
    assert len(airspace.record_changes("task-a", [SLUGIFY_CHANGE])) == 1
    clock.now += 1
    assert airspace.record_changes("task-a", [SLUGIFY_CHANGE]) == []
    assert graph.query("MATCH (cc:ContractChange) RETURN count(cc)").result_set == [[1]]
    # A different new signature is a new change.
    assert len(airspace.record_changes("task-a", [SignatureChange(SLUGIFY, NEW_SIG, "slugify(value)")])) == 1
    assert [e["kind"] for e in airspace.events()] == ["contract", "contract"]


def test_removal_is_recorded_after_the_symbol_is_gone(airspace, graph):
    airspace.ensure_task("agent-a", "task-a")
    graph.query("MATCH (s:Symbol {qualname: 'utils.text.truncate_words'}) DETACH DELETE s")
    ids = airspace.record_changes("task-a", [SignatureChange("utils.text.truncate_words", "truncate_words(text, count=30)", "")])
    assert len(ids) == 1
    airspace.ensure_task("agent-b", "task-b")
    caller = "tags.views.tag_label"
    shapes = {"utils.text.truncate_words": [CallSite(caller, 2, (), False, False)]}
    verdict = airspace.check_edit("task-b", [caller], [(caller, "utils.text.truncate_words")], shapes)
    assert verdict.kind == "hold" and verdict.collision_id


def _set_shapes(graph, caller, callee, shapes):
    graph.query(
        "MATCH (:Symbol {qualname: $a})-[r]->(:Symbol {qualname: $b}) SET r.shapes = $s",
        {"a": caller, "b": callee, "s": shapes},
    )


def test_caller_first_change_holds_the_claimed_caller(airspace, graph):
    # agent-b's cleared edit added slugify(post.title, True) to render_post; the post hook stored its shape.
    graph.query(
        "MATCH (a:Symbol {qualname: $a}), (b:Symbol {qualname: $b}) MERGE (a)-[r:CALLS]->(b) SET r.shapes = ['2|']",
        {"a": RENDER, "b": SLUGIFY},
    )
    airspace.file_plan("agent-b", "task-b", "slugs in posts", [RENDER])
    # agent-c claims a caller whose call still fits.
    _set_shapes(graph, "blog.models.Post.save", SLUGIFY, ["1|"])
    airspace.file_plan("agent-c", "task-c", "post saving", ["blog.models.Post.save"])
    airspace.ensure_task("agent-a", "task-a")

    airspace.record_changes("task-a", [SLUGIFY_CHANGE])

    assert _collisions(graph) == [["contract", "agent-b", "agent-a", SLUGIFY, RENDER, NEW_SIG, "held"]]
    holds = [e for e in airspace.events() if e["kind"] == "hold"]
    assert [(e["agent"], e["task"], e["code"]) for e in holds] == [("agent-b", "task-b", RENDER)]
    # The briefing is left for agent-b's next tool call, and says which call no longer fits.
    briefings = airspace.pending_briefings("task-b")
    assert [(b.symbol, b.new_signature, b.from_agent, b.caller) for b in briefings] == [(SLUGIFY, NEW_SIG, "agent-a", RENDER)]
    assert airspace.pending_briefings("task-b") == []
    assert airspace.state()["agents"][[a["id"] for a in airspace.state()["agents"]].index("agent-b")]["held"] is True
    # Recording the same change again writes nothing new.
    airspace.record_changes("task-a", [SLUGIFY_CHANGE])
    assert len(_collisions(graph)) == 1


def test_caller_first_constructor_change_checks_class_callers(airspace, graph):
    test = "tests.test_views.test_render_post"
    _set_shapes(graph, test, "blog.models.Post", ["2|"])
    airspace.file_plan("agent-b", "task-b", "view tests", [test])
    airspace.ensure_task("agent-a", "task-a")

    init = "blog.models.Post.__init__"
    airspace.record_changes("task-a", [SignatureChange(init, "__init__(self, title, body)", "__init__(self, title, body, author)")])

    rows = _collisions(graph)
    assert rows == [["contract", "agent-b", "agent-a", init, test, "__init__(self, title, body, author)", "held"]]


def test_new_symbols_are_claimed_once_written(airspace, graph):
    # The pre hook clears an edit that adds tags.views.tag_label; the symbol exists only after the write.
    airspace.ensure_task("agent-b", "task-b")
    label = "tags.views.tag_label"
    assert airspace.check_edit("task-b", [label, "tags.views.tag_create"], []).kind == "cleared"
    assert _claims(graph, "task-b") == [["tags.views.tag_create", 1]]

    graph.query("CREATE (:Symbol {qualname: $q, kind: 'function', file: 'tags/views.py'})", {"q": label})
    assert airspace.claim_pending("task-b") == [label]

    assert [q for q, _ in _claims(graph, "task-b")] == ["tags.views.tag_create", label]
    assert airspace.claim_pending("task-b") == []


def test_caller_first_skips_unknown_shapes_and_own_claims(airspace, graph):
    # Edges without stored shapes (an older index) and the changer's own claims never hold anyone.
    airspace.file_plan("agent-b", "task-b", "post saving", ["blog.models.Post.save"])
    _set_shapes(graph, "tags.models.Tag.save", SLUGIFY, ["2|"])
    airspace.file_plan("agent-a", "task-a", "tags", ["tags.models.Tag.save"])

    airspace.record_changes("task-a", [SLUGIFY_CHANGE])

    assert _collisions(graph) == []
