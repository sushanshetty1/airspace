"""Memory: hot zones from collision history plus betweenness, and safe parallel groups from WCC over agents."""

import pytest

from airspace.admission import insights
from airspace.admission.engine import Airspace
from helpers import seed_blog_graph

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"


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


def test_insights_on_an_empty_graph(graph, clock):
    assert Airspace(graph, clock=clock).insights() == {"hot_zones": [], "parallel_groups": []}


def test_insights_with_one_symbol_and_one_agent(graph, clock):
    # FalkorDB's algorithms fail on a single node, so these cases are answered without them.
    graph.query("CREATE (:Symbol {qualname: 'm.f', kind: 'function', is_test: false})")
    airspace = Airspace(graph, clock=clock)
    airspace.ensure_task("agent-a", "task-a")
    airspace.check_edit("task-a", ["m.f"], [])
    airspace.ensure_task("agent-b", "task-b")
    airspace.check_edit("task-b", ["m.f"], [])

    assert airspace.insights() == {
        "hot_zones": [{"qualname": "m.f", "collisions": 1, "betweenness": 0.0}],
        "parallel_groups": [{"agents": ["agent-a", "agent-b"], "conflict": True}],
    }
    airspace.release("task-b")
    graph.query("MATCH (a:Agent {id: 'agent-b'}) DETACH DELETE a")
    assert airspace.insights()["parallel_groups"] == [{"agents": ["agent-a"], "conflict": False}]


def test_insights_without_agents_still_rank_bridges(airspace):
    zones = airspace.insights()["hot_zones"]

    # tags.views.tag_create -> tags.models.Tag.save -> utils.text.slugify: Tag.save lies on the only shortest path.
    assert zones == [{"qualname": "tags.models.Tag.save", "collisions": 0, "betweenness": 1.0}]
    assert airspace.insights()["parallel_groups"] == []


def test_insights_hot_zones_use_betweenness_and_collisions(airspace, clock):
    airspace.file_plan("agent-a", "task-a", "slugs", [SLUGIFY, RENDER])
    airspace.ensure_task("agent-b", "task-b")
    for q in (SLUGIFY, SLUGIFY, RENDER):
        clock.now += 1
        assert airspace.check_edit("task-b", [q], []).kind == "hold"

    zones = airspace.insights()["hot_zones"]

    assert zones == [
        {"qualname": SLUGIFY, "collisions": 2, "betweenness": 0.0},
        {"qualname": RENDER, "collisions": 1, "betweenness": 0.0},
        {"qualname": "tags.models.Tag.save", "collisions": 0, "betweenness": 1.0},
    ]
    assert all(isinstance(z["betweenness"], float) for z in zones)


def test_hot_zones_are_capped_at_ten(airspace, graph):
    for i in range(12):
        graph.query(
            "CREATE (:Symbol {qualname: $q, kind: 'function', is_test: false})<-[:AT]-(:Collision {id: $id, symbol: $q})",
            {"q": f"m.f{i:02d}", "id": f"c{i}"},
        )

    assert len(insights.hot_zones(graph)) == 10


def test_parallel_groups_from_wcc(airspace, graph):
    # agent-b claims Post.save, which is in agent-a's cone: they conflict. agent-c works elsewhere.
    airspace.file_plan("agent-a", "task-a", "slugs", [SLUGIFY])
    airspace.file_plan("agent-b", "task-b", "saving", ["blog.models.Post.save"])
    airspace.file_plan("agent-c", "task-c", "feeds", ["utils.text.truncate_words"])
    airspace.file_plan("agent-d", "task-d", "done", ["tags.views.tag_create"])
    airspace.release("task-d")

    groups = airspace.insights()["parallel_groups"]

    assert groups == [
        {"agents": ["agent-a", "agent-b"], "conflict": True},
        {"agents": ["agent-c"], "conflict": False},
    ]
    edges = graph.query("MATCH (a:Agent)-[:CONFLICTS]->(b:Agent) RETURN a.id, b.id").result_set
    assert edges == [["agent-a", "agent-b"]]


def test_parallel_groups_join_agents_with_an_open_collision(airspace):
    airspace.file_plan("agent-a", "task-a", "slugs", ["utils.text.truncate_words"])
    airspace.ensure_task("agent-b", "task-b")
    held = airspace.check_edit("task-b", ["utils.text.truncate_words"], [])
    airspace.file_plan("agent-c", "task-c", "tags", ["tags.views.tag_create"])

    assert airspace.insights()["parallel_groups"] == [
        {"agents": ["agent-a", "agent-b"], "conflict": True},
        {"agents": ["agent-c"], "conflict": False},
    ]

    # Once the hold is released and nothing else overlaps, the CONFLICTS edges are rebuilt without it.
    airspace.release_collision(held.collision_id)
    assert airspace.insights()["parallel_groups"] == [
        {"agents": ["agent-a"], "conflict": False},
        {"agents": ["agent-b"], "conflict": False},
        {"agents": ["agent-c"], "conflict": False},
    ]


def test_same_agent_tasks_form_one_group_without_conflict(airspace):
    airspace.file_plan("agent-a", "sess-a", "slugs", [SLUGIFY])
    airspace.file_plan("agent-a", "agent-a:mcp", "saving", ["blog.models.Post.save"])

    assert airspace.insights()["parallel_groups"] == [{"agents": ["agent-a"], "conflict": False}]
