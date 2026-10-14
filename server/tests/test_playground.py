"""The playground: the real engine on a scratch copy of the indexed fixture repo, one request at a time."""

import inspect
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from airspace.admission.engine import Airspace
from airspace.api import playground
from airspace.api.app import create_app

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"
NEW_SLUGIFY = "slugify(value, *, unicode=False)"

# The engine checks a call's arguments against the new signature once check_edit takes call_shapes.
CHECKS_SHAPES = "call_shapes" in inspect.signature(Airspace.check_edit).parameters
needs_shapes = pytest.mark.skipif(not CHECKS_SHAPES, reason="this engine's check_edit has no call_shapes yet")


def body(symbol=SLUGIFY, new_signature=NEW_SLUGIFY, caller=RENDER, call="slugify(post.title, True)"):
    return {"change": {"symbol": symbol, "new_signature": new_signature}, "edit": {"caller": caller, "call": call}}


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(playground.router(connect=lambda: db, per_minute=1000))
    return TestClient(app)


def check(client, **kw):
    return client.post("/api/playground/check", json=body(**kw))


# Verdicts


def test_slugify_story_is_held(client):
    r = check(client)
    assert r.status_code == 200
    out = r.json()
    assert out["verdict"] == "hold"
    assert SLUGIFY in out["reason"] and NEW_SLUGIFY in out["reason"]
    assert out["path"] == [RENDER, SLUGIFY]


def test_result_carries_the_scratch_radar(client):
    radar = check(client).json()["radar"]
    assert {a["id"] for a in radar["agents"]} == {"agent-a", "agent-b"}
    assert radar["collision"]["symbol"] == SLUGIFY
    assert radar["collision"]["caller"] == RENDER
    assert radar["symbols"][SLUGIFY]["label"] == "slugify"


def test_compatible_keyword_call_matches_what_the_engine_does(client):
    out = check(client, call="slugify(post.title, unicode=True)").json()
    assert out["verdict"] == ("cleared" if CHECKS_SHAPES else "hold")


@needs_shapes
def test_compatible_keyword_call_is_cleared_with_call_shapes(client):
    out = check(client, call="slugify(post.title, unicode=True)").json()
    assert out["verdict"] == "cleared"
    assert out["path"] == [RENDER, SLUGIFY]
    assert "fits" in out["reason"]


def test_call_to_something_nobody_changes_is_cleared(client):
    out = check(client, call="truncate_words(post.body, 10)").json()
    assert out["verdict"] == "cleared"
    assert out["reason"]


def test_renamed_method_is_held(client):
    out = check(
        client, symbol="blog.models.Post.get_absolute_url", new_signature="url(self)",
        caller="blog.feeds.LatestPosts.item_description", call="post.get_absolute_url()",
    ).json()
    assert out["verdict"] == "hold"
    assert out["path"] == ["blog.feeds.LatestPosts.item_description", "blog.models.Post.get_absolute_url"]


def test_constructor_with_a_new_argument_is_held(client):
    out = check(
        client, symbol="blog.models.Post.__init__", new_signature="__init__(self, title, body, author)",
        caller="blog.views.post_list", call="Post(title, body)",
    ).json()
    assert out["verdict"] == "hold"
    assert out["path"][-1] == "blog.models.Post.__init__"


@needs_shapes
def test_constructor_call_with_the_new_argument_is_cleared(client):
    out = check(
        client, symbol="blog.models.Post.__init__", new_signature="__init__(self, title, body, author)",
        caller="blog.views.post_list", call="Post(title, body, author)",
    ).json()
    assert out["verdict"] == "cleared"


# Validation


@pytest.mark.parametrize(
    "kw, words",
    [
        ({"new_signature": "slugify(value, *, unicode=False"}, "new signature"),
        ({"new_signature": "slugify(value): pass\nimport os\ndef f()"}, "new signature"),
        ({"new_signature": ""}, "new signature"),
        ({"call": "post.title + 1"}, "call"),
        ({"call": "slugify(a); slugify(b)"}, "call"),
        ({"call": "slugify(a"}, "call"),
        ({"call": "slugify(a).lower"}, "call"),
        ({"symbol": "utils.text.nope"}, "utils.text.nope"),
        ({"caller": "blog.views.nope"}, "blog.views.nope"),
        ({"call": "frobnicate(post)"}, "frobnicate"),
        ({"call": "x" * 300 + "()"}, "call"),
    ],
)
def test_bad_input_is_422_with_a_clear_message(client, kw, words):
    r = check(client, **kw)
    assert r.status_code == 422
    assert words in r.json()["error"]


def test_missing_fields_are_422(client):
    r = client.post("/api/playground/check", json={"change": {"symbol": SLUGIFY}})
    assert r.status_code == 422
    assert "required" in r.json()["error"]


# The scratch graph


def test_scratch_graph_is_deleted(client, db, monkeypatch):
    fixed = uuid.UUID(int=uuid.uuid4().int)
    monkeypatch.setattr(playground.uuid, "uuid4", lambda: fixed)
    name = f"playground_{fixed.hex}"
    assert check(client).status_code == 200
    assert name not in db.list_graphs()


def test_scratch_graph_is_deleted_after_a_422(client, db, monkeypatch):
    fixed = uuid.UUID(int=uuid.uuid4().int)
    monkeypatch.setattr(playground.uuid, "uuid4", lambda: fixed)
    assert check(client, caller="blog.views.nope").status_code == 422
    assert f"playground_{fixed.hex}" not in db.list_graphs()


# Availability and limits


def test_falkordb_down_is_503():
    def down():
        raise ConnectionError("Connection refused")

    app = FastAPI()
    app.include_router(playground.router(connect=down))
    r = TestClient(app).post("/api/playground/check", json=body())
    assert r.status_code == 503
    assert "FalkorDB" in r.json()["error"]


def test_rate_limited_per_client(db):
    app = FastAPI()
    app.include_router(playground.router(connect=lambda: db, per_minute=2))
    c = TestClient(app)
    bad = body(call="nope(")  # rejected before FalkorDB is touched, but still counted
    assert c.post("/api/playground/check", json=bad).status_code == 422
    assert c.post("/api/playground/check", json=bad).status_code == 422
    r = c.post("/api/playground/check", json=bad)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_mounted_in_the_app(db):
    client = TestClient(create_app(lambda: None))
    r = client.post("/api/playground/check", json=body(call="slugify("))
    assert r.status_code == 422


# Parsing


def test_parse_call_shapes():
    assert playground.parse_call("slugify(post.title, True)") == ("slugify", 2, (), False)
    assert playground.parse_call("text.slugify(t, unicode=True)") == ("text.slugify", 1, ("unicode",), False)
    assert playground.parse_call("f(*args)") == ("f", 0, (), True)
    assert playground.parse_call("f(a, **kw)") == ("f", 1, (), True)
    assert playground.parse_call("Tag(name).save()") == ("Tag().save", 0, (), False)
