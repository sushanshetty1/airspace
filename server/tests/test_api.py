import json

import pytest
from fastapi.testclient import TestClient

from airspace.api.app import create_app

STATE = {
    "now": 1791958771.6,
    "agents": [
        {
            "id": "agent-a",
            "paused": False,
            "status": "active",
            "tasks": ["task-a"],
            "claims": ["utils.text.slugify"],
            "held": False,
        }
    ],
    "collisions": [
        {
            "id": "col_1",
            "at": 1791958700.1,
            "kind": "contract",
            "symbol": "utils.text.slugify",
            "held_agent": "agent-b",
            "owner_agent": "agent-a",
            "resolution": "held",
        }
    ],
}

RADAR = {
    "agents": [
        {
            "id": "agent-a",
            "center": "utils.text.slugify",
            "claims": ["utils.text.slugify"],
            "cone": [{"qualname": "blog.models.Post.save", "hop": 1}],
        }
    ],
    "symbols": {"utils.text.slugify": {"label": "slugify", "kind": "function", "is_test": False}},
    "edges": [["blog.models.Post.save", "utils.text.slugify"]],
    "collision": None,
}

COLLISION = {
    "id": "col_1",
    "at": 1791958700.1,
    "kind": "contract",
    "symbol": "utils.text.slugify",
    "caller": "blog.views.render_post",
    "path": ["blog.views.render_post", "utils.text.slugify"],
    "held_agent": "agent-b",
    "held_task": "task-b",
    "owner_agent": "agent-a",
    "owner_task": "task-a",
    "old_sig": "slugify(value, allow_unicode=False)",
    "new_sig": "slugify(value, *, unicode=False)",
    "resolution": "held",
}

INSIGHTS = {
    "hot_zones": [{"qualname": "utils.text.slugify", "collisions": 3, "betweenness": 2.0}],
    "parallel_groups": [
        {"agents": ["agent-a", "agent-b"], "conflict": True},
        {"agents": ["agent-c"], "conflict": False},
    ],
}


def event(n: int, at: float) -> dict:
    return {
        "id": f"ev_{n}",
        "at": at,
        "kind": "cleared",
        "agent": "agent-a",
        "task": "task-a",
        "text": "was cleared to edit",
        "code": "utils.text.slugify",
    }


class FakeAirspace:
    """Returns contract-shaped data and records every call."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.log = [event(1, 1.0), event(2, 2.0)]
        self.known_agents = {"agent-a"}

    def state(self):
        self.calls.append(("state",))
        return STATE

    def radar(self):
        self.calls.append(("radar",))
        return RADAR

    def events(self, since=0.0, limit=200):
        self.calls.append(("events", since))
        return [e for e in self.log if e["at"] > since][:limit]

    def collision(self, collision_id):
        self.calls.append(("collision", collision_id))
        return COLLISION if collision_id == "col_1" else None

    def insights(self):
        self.calls.append(("insights",))
        return INSIGHTS

    def pause(self, agent_id):
        self.calls.append(("pause", agent_id))

    def resume(self, agent_id):
        self.calls.append(("resume", agent_id))

    def message(self, agent_id, text, sender="Tower"):
        self.calls.append(("message", agent_id, text, sender))
        return "msg_1"

    def release_collision(self, collision_id):
        self.calls.append(("release_collision", collision_id))
        return collision_id == "col_1"


@pytest.fixture
def fake():
    return FakeAirspace()


@pytest.fixture
def client(fake):
    return TestClient(create_app(lambda: fake))


def test_state(client, fake):
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json() == STATE


def test_state_empty_graph_returns_empty_lists():
    class Empty(FakeAirspace):
        def state(self):
            return {"now": 1.0, "agents": [], "collisions": []}

        def radar(self):
            return {"agents": [], "symbols": {}, "edges": [], "collision": None}

    client = TestClient(create_app(Empty))
    assert client.get("/api/state").json()["agents"] == []
    assert client.get("/api/radar").json()["agents"] == []


def test_radar(client):
    r = client.get("/api/radar")
    assert r.status_code == 200
    assert r.json() == RADAR


def test_events_passes_since(client, fake):
    r = client.get("/api/events?since=1.5")
    assert r.status_code == 200
    assert r.json() == {"events": [event(2, 2.0)]}
    assert ("events", 1.5) in fake.calls


def test_events_since_defaults_to_zero(client, fake):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert [e["id"] for e in r.json()["events"]] == ["ev_1", "ev_2"]
    assert ("events", 0.0) in fake.calls


def test_collision_detail(client):
    r = client.get("/api/collisions/col_1")
    assert r.status_code == 200
    assert r.json() == COLLISION


def test_unknown_collision_is_404(client):
    r = client.get("/api/collisions/nope")
    assert r.status_code == 404
    assert r.json() == {"error": "not found"}


def test_insights(client):
    r = client.get("/api/insights")
    assert r.status_code == 200
    assert r.json() == INSIGHTS


def test_pause_and_resume(client, fake):
    assert client.post("/api/agents/agent-a/pause").json() == {"ok": True}
    assert client.post("/api/agents/agent-a/resume").json() == {"ok": True}
    assert ("pause", "agent-a") in fake.calls
    assert ("resume", "agent-a") in fake.calls


def test_pause_unknown_or_released_agent_is_noop(client, fake):
    for agent in ("agent-gone", "agent-released"):
        r = client.post(f"/api/agents/{agent}/pause")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        r = client.post(f"/api/agents/{agent}/resume")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
    assert ("pause", "agent-gone") in fake.calls


def test_engine_value_error_on_action_is_reported_not_500(fake):
    def refuse(agent_id):
        raise KeyError(agent_id)

    fake.pause = refuse
    r = TestClient(create_app(lambda: fake)).post("/api/agents/agent-x/pause")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "agent-x" in r.json()["error"]


def test_message(client, fake):
    r = client.post("/api/agents/agent-b/message", json={"text": "  slugify takes unicode= now  "})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": "msg_1"}
    assert ("message", "agent-b", "slugify takes unicode= now", "Tower") in fake.calls


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_message_out_of_range_is_422(client, fake, text):
    r = client.post("/api/agents/agent-b/message", json={"text": text})
    assert r.status_code == 422
    assert not any(c[0] == "message" for c in fake.calls)


def test_message_of_500_characters_is_accepted(client):
    assert client.post("/api/agents/agent-b/message", json={"text": "x" * 500}).status_code == 200


def test_message_without_text_is_422(client):
    assert client.post("/api/agents/agent-b/message", json={}).status_code == 422


def test_release_collision(client, fake):
    assert client.post("/api/collisions/col_1/release").json() == {"ok": True}
    r = client.post("/api/collisions/nope/release")
    assert r.status_code == 200
    assert r.json() == {"ok": False}
    assert ("release_collision", "col_1") in fake.calls


def test_engine_unavailable_is_503_and_retried():
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("refused")
        return FakeAirspace()

    client = TestClient(create_app(factory))
    r = client.get("/api/state")
    assert r.status_code == 503
    assert "FalkorDB" in r.json()["error"]
    assert client.get("/api/state").status_code == 200


def test_factory_called_once(fake):
    built = []

    def factory():
        built.append(1)
        return fake

    client = TestClient(create_app(factory))
    client.get("/api/state")
    client.get("/api/radar")
    assert len(built) == 1


@pytest.mark.parametrize("origin", ["http://localhost:4173", "http://127.0.0.1:4173"])
def test_cors_allows_tower(client, origin):
    r = client.get("/api/state", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin
    pre = client.options(
        "/api/agents/agent-a/message",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin


def test_cors_rejects_other_origins(client):
    r = client.get("/api/state", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# Server-sent events


class AdvancingAirspace(FakeAirspace):
    """Every poll writes one more event. Pairs share a timestamp, and since is inclusive, so a naive stream repeats."""

    def __init__(self):
        super().__init__()
        self.log = [event(1, 1.0), event(2, 2.0), event(3, 2.0)]

    def events(self, since=0.0, limit=200):
        self.calls.append(("events", since))
        out = [e for e in self.log if e["at"] >= since][:limit]
        n = len(self.log) + 1
        self.log.append(event(n, 2.0 + n // 2))
        return out


def frames(body: str) -> list[str]:
    return [f for f in body.split("\n\n") if f]


def stream_body(app, url="/api/events/stream?since=0") -> tuple[int, str, str]:
    with TestClient(app).stream("GET", url) as r:
        return r.status_code, r.headers["content-type"], "".join(r.iter_text())


def test_stream_sends_events_once_in_order():
    fake = AdvancingAirspace()
    status, content_type, body = stream_body(create_app(lambda: fake, poll_interval=0.01, max_seconds=0.3))
    assert status == 200
    assert content_type.startswith("text/event-stream")
    events = []
    for f in frames(body):
        if f.startswith(":"):
            continue
        name, data = f.split("\n")
        assert name == "event: airspace"
        assert data.startswith("data: ")
        events.append(json.loads(data[len("data: "):]))
    ids = [e["id"] for e in events]
    assert ids[:3] == ["ev_1", "ev_2", "ev_3"]
    assert len(ids) > 3, "events written after the stream opened are sent"
    assert len(ids) == len(set(ids)), "no event is sent twice"
    ats = [e["at"] for e in events]
    assert ats == sorted(ats)


def test_stream_advances_since():
    fake = AdvancingAirspace()
    stream_body(create_app(lambda: fake, poll_interval=0.01, max_seconds=0.2), "/api/events/stream?since=1.5")
    sinces = [c[1] for c in fake.calls if c[0] == "events"]
    assert sinces[0] == 1.5
    assert sinces[-1] > 2.0
    assert sinces == sorted(sinces)


def test_stream_pings():
    class Quiet(FakeAirspace):
        def events(self, since=0.0, limit=200):
            return []

    _, _, body = stream_body(create_app(Quiet, poll_interval=0.01, ping_interval=0.05, max_seconds=0.3))
    assert ": ping" in frames(body)
    assert "event: airspace" not in body
