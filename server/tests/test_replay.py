"""Replay: recording a real run into frames, the replay CLI, and the /api/replay and /api/mode routes."""

import json

import pytest
from fastapi.testclient import TestClient
from helpers import seed_blog_graph

from airspace import replay
from airspace.admission.engine import Airspace
from airspace.api.app import create_app
from airspace.types import SignatureChange

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def airspace(graph, clock):
    seed_blog_graph(graph)
    return Airspace(graph, lease_seconds=900, cone_depth=2, clock=clock)


def story_part_one(air: Airspace, clock: Clock) -> None:
    air.file_plan("agent-a", "ta", "change slugify", [SLUGIFY])
    clock.t += 1
    air.file_plan("agent-b", "tb", "edit render_post", [RENDER])


def story_part_two(air: Airspace, clock: Clock) -> None:
    clock.t += 1
    air.record_changes("ta", [SignatureChange(SLUGIFY, "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")])
    clock.t += 1
    air.check_edit("tb", [RENDER], [(RENDER, SLUGIFY)])


# Recorder: live frames


def test_snapshot_adds_a_frame_only_when_there_are_new_events(airspace, clock):
    rec = replay.Recorder(airspace)
    assert rec.snapshot() is False
    assert rec.frames == []

    story_part_one(airspace, clock)
    assert rec.snapshot() is True
    assert rec.snapshot() is False
    assert len(rec.frames) == 1
    assert [e["kind"] for e in rec.events] == ["plan", "plan"]


def test_frames_hold_the_state_and_radar_at_that_moment(airspace, clock):
    rec = replay.Recorder(airspace)
    story_part_one(airspace, clock)
    rec.snapshot()
    story_part_two(airspace, clock)
    rec.snapshot()

    first, second = rec.frames
    assert first["at"] == rec.events[1]["at"]
    assert first["state"]["collisions"] == []
    assert first["radar"]["collision"] is None
    assert second["at"] == rec.events[-1]["at"]
    assert second["state"]["collisions"][0]["resolution"] == "held"
    assert second["radar"]["collision"]["symbol"] == SLUGIFY
    assert {a["id"] for a in second["radar"]["agents"]} == {"agent-a", "agent-b"}


def test_document_shape(airspace, clock):
    rec = replay.Recorder(airspace)
    story_part_one(airspace, clock)
    rec.snapshot()
    story_part_two(airspace, clock)
    rec.snapshot()

    doc = rec.document()
    assert doc["version"] == 1
    assert isinstance(doc["recorded_at"], float)
    assert [e["kind"] for e in doc["events"]] == ["plan", "plan", "contract", "hold", "briefed"]
    assert len(doc["frames"]) == 2
    (cid,) = doc["collisions"]
    assert doc["collisions"][cid]["path"] == [RENDER, SLUGIFY]
    assert doc["collisions"][cid]["new_sig"] == "slugify(value, *, unicode=False)"
    assert set(doc["insights"]) == {"hot_zones", "parallel_groups", "notes"}
    json.dumps(doc)


def test_save_writes_json(airspace, clock, tmp_path):
    rec = replay.Recorder(airspace)
    story_part_one(airspace, clock)
    rec.snapshot()
    out = tmp_path / "demo" / "replay.json"
    rec.save(out)
    assert json.loads(out.read_text())["frames"][0]["state"]["agents"]


# record(): after the fact, from the final graph


def test_record_after_the_fact_keeps_every_event_and_a_final_frame(airspace, clock, graph, tmp_path):
    story_part_one(airspace, clock)
    story_part_two(airspace, clock)
    out = tmp_path / "replay.json"
    doc = replay.record(graph, out)

    assert json.loads(out.read_text()) == doc
    assert len(doc["events"]) == 5
    assert len(doc["frames"]) == 1
    assert doc["frames"][0]["at"] == doc["events"][-1]["at"]
    assert len(doc["collisions"]) == 1


# The command line: python -m airspace.replay


def test_watch_records_frames_for_a_run(airspace, clock, graph, tmp_path, monkeypatch):
    monkeypatch.setenv("AIRSPACE_GRAPH", graph.name)
    story_part_one(airspace, clock)
    out = tmp_path / "replay.json"
    assert replay.main(["watch", "--root", str(tmp_path), "--out", str(out), "--seconds", "0.2"]) == 0
    doc = json.loads(out.read_text())
    assert len(doc["frames"]) == 1
    assert len(doc["events"]) == 2


def test_watch_reports_falkordb_down(tmp_path, monkeypatch, capsys):
    def down(root):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(replay, "_open", down)
    assert replay.main(["watch", "--root", str(tmp_path), "--out", str(tmp_path / "r.json"), "--seconds", "0"]) == 1
    assert "FalkorDB unavailable" in capsys.readouterr().err


def test_summarize(airspace, clock, graph, tmp_path, capsys):
    story_part_one(airspace, clock)
    story_part_two(airspace, clock)
    out = tmp_path / "replay.json"
    replay.record(graph, out)
    assert replay.main(["summarize", str(out)]) == 0
    text = capsys.readouterr().out
    assert "5 events" in text
    assert "1 frame" in text
    assert "1 collision" in text
    assert "agent-a, agent-b" in text


def test_summarize_rejects_a_file_that_is_not_a_replay(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    assert replay.main(["summarize", str(bad)]) == 1
    assert "not an Airspace replay" in capsys.readouterr().err


# The API


class FakeAirspace:
    def __init__(self, agents):
        self.agents = agents

    def state(self):
        return {"now": 1.0, "agents": self.agents, "collisions": []}


ACTIVE = [{"id": "agent-a", "paused": False, "status": "active", "tasks": ["t"], "claims": [], "held": False}]
RELEASED = [{"id": "agent-a", "paused": False, "status": "released", "tasks": ["t"], "claims": [], "held": False}]


def replay_file(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps({"version": 1, "recorded_at": 1.0, "events": [], "frames": [], "collisions": {},
                                "insights": {"hot_zones": [], "parallel_groups": []}}))
    return path


def test_replay_is_404_when_unset(monkeypatch):
    monkeypatch.delenv("AIRSPACE_REPLAY", raising=False)
    client = TestClient(create_app(lambda: FakeAirspace([])))
    r = client.get("/api/replay")
    assert r.status_code == 404
    assert "AIRSPACE_REPLAY" in r.json()["error"]


def test_replay_serves_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRSPACE_REPLAY", str(replay_file(tmp_path)))
    client = TestClient(create_app(lambda: FakeAirspace([])))
    r = client.get("/api/replay")
    assert r.status_code == 200
    assert r.json()["version"] == 1


def test_replay_missing_file_is_404(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRSPACE_REPLAY", str(tmp_path / "nope.json"))
    client = TestClient(create_app(lambda: FakeAirspace([])))
    assert client.get("/api/replay").status_code == 404


def test_mode_is_live_without_a_replay(monkeypatch):
    monkeypatch.delenv("AIRSPACE_REPLAY", raising=False)
    client = TestClient(create_app(lambda: FakeAirspace([])))
    assert client.get("/api/mode").json() == {"mode": "live"}


def test_mode_is_replay_when_no_agent_is_flying(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRSPACE_REPLAY", str(replay_file(tmp_path)))
    assert TestClient(create_app(lambda: FakeAirspace([]))).get("/api/mode").json() == {"mode": "replay"}
    assert TestClient(create_app(lambda: FakeAirspace(RELEASED))).get("/api/mode").json() == {"mode": "replay"}


def test_mode_is_live_when_an_agent_is_flying(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRSPACE_REPLAY", str(replay_file(tmp_path)))
    client = TestClient(create_app(lambda: FakeAirspace(ACTIVE)))
    assert client.get("/api/mode").json() == {"mode": "live"}


def test_mode_is_replay_when_falkordb_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRSPACE_REPLAY", str(replay_file(tmp_path)))

    def down():
        raise ConnectionError("refused")

    assert TestClient(create_app(down)).get("/api/mode").json() == {"mode": "replay"}
