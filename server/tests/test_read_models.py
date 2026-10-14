"""Read models served verbatim by the API: state(), radar() and collision(id)."""

import json

import pytest

from airspace.admission.engine import Airspace
from airspace.types import SignatureChange
from helpers import seed_blog_graph

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"
POST_SAVE = "blog.models.Post.save"
OLD_SIG = "slugify(value, allow_unicode=False)"
NEW_SIG = "slugify(value, *, unicode=False)"


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


@pytest.fixture
def contract_hold(airspace, clock):
    """agent-a changes slugify; agent-b is held adding a call to it. Returns the collision id."""
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    clock.now += 1
    airspace.record_changes("task-a", [SignatureChange(SLUGIFY, OLD_SIG, NEW_SIG)])
    clock.now += 1
    airspace.ensure_task("agent-b", "task-b")
    return airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)]).collision_id


def test_empty_read_models(airspace, clock):
    assert airspace.state() == {"now": clock.now, "agents": [], "collisions": []}
    assert airspace.radar() == {"agents": [], "symbols": {}, "edges": [], "collision": None}


def test_state_shape(airspace, contract_hold):
    state = airspace.state()

    assert state == {
        "now": 1002.0,
        "agents": [
            {"id": "agent-a", "paused": False, "status": "active", "tasks": ["task-a"], "claims": [SLUGIFY],
             "held": False},
            {"id": "agent-b", "paused": False, "status": "active", "tasks": ["task-b"], "claims": [],
             "held": True},
        ],
        "collisions": [
            {"id": contract_hold, "at": 1002.0, "kind": "contract", "symbol": SLUGIFY, "held_agent": "agent-b",
             "owner_agent": "agent-a", "resolution": "held"},
        ],
    }
    json.dumps(state)


def test_state_reflects_pause_release_and_expiry(airspace, contract_hold, clock):
    airspace.pause("agent-a")
    airspace.release("task-b")
    clock.now += 901

    agents = {a["id"]: a for a in airspace.state()["agents"]}

    assert agents["agent-a"]["paused"] is True
    assert agents["agent-a"]["claims"] == []
    assert agents["agent-b"]["status"] == "released"


def test_state_lists_newest_collisions_first_and_at_most_20(airspace, clock):
    airspace.file_plan("agent-a", "task-a", "change slugify", [SLUGIFY])
    airspace.ensure_task("agent-b", "task-b")
    ids = []
    for _ in range(22):
        clock.now += 1
        ids.append(airspace.check_edit("task-b", [SLUGIFY], []).collision_id)

    collisions = airspace.state()["collisions"]

    assert [c["id"] for c in collisions] == ids[::-1][:20]


def test_radar_shape_and_hops(airspace, contract_hold):
    radar = airspace.radar()

    assert radar["agents"] == [
        {"id": "agent-b", "center": None, "claims": [], "cone": []},
        {
            "id": "agent-a",
            "center": SLUGIFY,
            "claims": [SLUGIFY],
            "cone": [
                {"qualname": POST_SAVE, "hop": 1},
                {"qualname": "tags.models.Tag.save", "hop": 1},
                {"qualname": "tests.test_text.test_slugify", "hop": 1},
                {"qualname": "tags.views.tag_create", "hop": 2},
                {"qualname": "tests.test_models.test_post_save", "hop": 2},
                {"qualname": "tests.test_views.test_render_post", "hop": 2},
            ],
        },
    ]
    assert set(radar["symbols"]) == {
        SLUGIFY, POST_SAVE, RENDER, "tags.models.Tag.save", "tests.test_text.test_slugify", "tags.views.tag_create",
        "tests.test_models.test_post_save", "tests.test_views.test_render_post",
    }
    assert radar["symbols"][SLUGIFY] == {"label": "slugify", "kind": "function", "is_test": False}
    assert radar["symbols"][POST_SAVE] == {"label": "Post.save", "kind": "method", "is_test": False}
    assert radar["symbols"]["tests.test_text.test_slugify"] == {
        "label": "test_slugify", "kind": "function", "is_test": True,
    }
    assert radar["edges"] == [
        [POST_SAVE, SLUGIFY],
        ["tags.models.Tag.save", SLUGIFY],
        ["tags.views.tag_create", "tags.models.Tag.save"],
        ["tests.test_models.test_post_save", POST_SAVE],
        ["tests.test_text.test_slugify", SLUGIFY],
        ["tests.test_views.test_render_post", POST_SAVE],
        ["tests.test_views.test_render_post", RENDER],
    ]
    assert radar["collision"] == {
        "id": contract_hold, "symbol": SLUGIFY, "caller": RENDER, "held_agent": "agent-b",
        "owner_agent": "agent-a", "resolution": "held",
    }
    json.dumps(radar)


def test_radar_center_is_latest_claim(airspace, clock):
    airspace.file_plan("agent-a", "task-a", "slugs", [SLUGIFY])
    clock.now += 1
    airspace.check_edit("task-a", ["utils.text.truncate_words"], [])

    agent = airspace.radar()["agents"][0]

    assert agent["center"] == "utils.text.truncate_words"
    assert agent["claims"] == [SLUGIFY, "utils.text.truncate_words"]


def test_radar_keeps_four_most_recently_active_agents(airspace, clock):
    symbols = [SLUGIFY, "utils.text.truncate_words", RENDER, "blog.views.post_list", "tags.views.tag_create"]
    for i, q in enumerate(symbols):
        clock.now += 1
        airspace.ensure_task(f"agent-{i}", f"task-{i}")
        airspace.check_edit(f"task-{i}", [q], [])
    airspace.ensure_task("agent-done", "task-done")
    airspace.release("task-done")

    assert [a["id"] for a in airspace.radar()["agents"]] == ["agent-4", "agent-3", "agent-2", "agent-1"]


def test_radar_collision_falls_back_to_most_recent(airspace, contract_hold):
    airspace.check_edit("task-b", [RENDER], [(RENDER, SLUGIFY)])

    assert airspace.radar()["collision"]["resolution"] == "resolved"


def test_collision_detail(airspace, contract_hold, clock):
    assert airspace.collision(contract_hold) == {
        "id": contract_hold, "at": 1002.0, "kind": "contract", "symbol": SLUGIFY, "caller": RENDER,
        "path": [RENDER, SLUGIFY], "held_agent": "agent-b", "held_task": "task-b", "owner_agent": "agent-a",
        "owner_task": "task-a", "old_sig": OLD_SIG, "new_sig": NEW_SIG, "resolution": "held", "fix": None,
    }

    clock.now += 1
    claim_id = airspace.check_edit("task-b", [SLUGIFY], []).collision_id
    assert airspace.collision(claim_id) == {
        "id": claim_id, "at": 1003.0, "kind": "claim", "symbol": SLUGIFY, "caller": None, "path": [SLUGIFY],
        "held_agent": "agent-b", "held_task": "task-b", "owner_agent": "agent-a", "owner_task": "task-a",
        "old_sig": None, "new_sig": None, "resolution": "held", "fix": None,
    }
    assert airspace.collision("no-such-collision") is None
