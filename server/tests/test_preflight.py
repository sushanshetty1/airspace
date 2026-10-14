"""Pre-flight on the real FalkorDB: pair kinds, paths, WCC groups, hot spots, cleanup, and every front end.

The blog fixture's shape, as the indexer sees it (depth 2):
    utils.text.slugify   <- Post.save, Tag.save, test_slugify; then test_post_save, test_render_post, tag_create
    tags.models.Tag.save <- tag_create
    blog.views.render_post <- LatestPosts.item_description, post_list, test_render_post
    utils.text.truncate_words <- LatestPosts.item_description
"""

import uuid
from pathlib import Path

import anyio
import httpx
import pytest
from cloud_helpers import (  # noqa: F401 (fixtures)
    WRITE,
    app_client,
    client,
    cloud,
    github,
    make_cloud,
    new_workspace,
    sign_in,
)
from conftest import FIXTURE_REPO
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from airspace import cli, wire
from airspace.admission import preflight as pf
from airspace.admission.engine import Airspace
from airspace.admission.preflight import PreflightError, as_text, find_symbols, preflight, resolve_symbol
from airspace.api import app as api_app
from airspace.api import preflight_routes
from airspace.api.app import ApiError, create_app
from airspace.api.preflight_routes import DemoRepo, Demos
from airspace.cloud.rpc import GRAPH_METHODS, RpcError, dispatch
from airspace.indexer.writer import index_repo
from airspace.mcp_server import server as mcp
from airspace.remote import RemoteAirspace, RpcClient, remote_preflight

SLUG = {"name": "Slug", "symbols": ["slugify"]}
TAGS = {"name": "Tags", "symbols": ["Tag.save"]}
RENDER = {"name": "Render", "symbols": ["render_post"]}
WORDS = {"name": "Words", "symbols": ["truncate_words"]}

SYNTHETIC = {
    "core.py": """
def base():
    return 1


def mid():
    return base()


def top():
    return mid()


class Model:
    def save(self):
        return self
""",
    "ext.py": """
from core import Model


class Special(Model):
    pass
""",
    "pkg/__init__.py": "from pkg.impl import thing\n",
    "pkg/impl.py": "def thing():\n    return 2\n",
}


def no_dashes(text: str) -> bool:
    return "\u2013" not in text and "\u2014" not in text


def temp_nodes(graph) -> int:
    return graph.query("MATCH (n) WHERE n:Flight OR n:FlightTask RETURN count(n)").result_set[0][0]


@pytest.fixture
def blog(graph):
    index_repo(graph, FIXTURE_REPO)
    return graph


@pytest.fixture
def synthetic(graph, tmp_path):
    for rel, text in SYNTHETIC.items():
        path = tmp_path / "repo" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    index_repo(graph, tmp_path / "repo")
    return graph


def pair(answer, a, b):
    found = [p for p in answer["pairs"] if {p["a"], p["b"]} == {a, b}]
    return found[0] if found else None


# Pair kinds and paths


def test_same_symbol(blog):
    out = preflight(blog, [SLUG, {"name": "Both", "symbols": ["utils.text.slugify", "truncate_words"]}])
    p = pair(out, "Slug", "Both")
    assert p["kind"] == "same_symbol"
    assert p["symbols"] == ["utils.text.slugify"] and p["path"] == ["utils.text.slugify"]
    assert p["shared"] == 6


def test_calls_has_the_path_from_the_caller_to_the_changed_symbol(blog):
    out = preflight(blog, [SLUG, TAGS])
    assert out["pairs"] == [{"a": "Slug", "b": "Tags", "kind": "calls",
                             "symbols": ["tags.models.Tag.save", "utils.text.slugify"],
                             "path": ["tags.models.Tag.save", "utils.text.slugify"], "shared": 1}]
    # Either way round, the path still runs from the caller to what is changed.
    assert preflight(blog, [TAGS, SLUG])["pairs"][0]["path"] == ["tags.models.Tag.save", "utils.text.slugify"]


def test_calls_path_over_two_hops_and_depth(synthetic):
    tasks = [{"name": "Base", "symbols": ["core.base"]}, {"name": "Top", "symbols": ["core.top"]}]
    p = preflight(synthetic, tasks)["pairs"][0]
    assert p["kind"] == "calls" and p["path"] == ["core.top", "core.mid", "core.base"]
    # One hop: top is out of base's cone, and the cones share nothing.
    assert preflight(synthetic, tasks, depth=1)["pairs"] == []


def test_calls_over_inheritance(synthetic):
    out = preflight(synthetic, [{"name": "Model", "symbols": ["core.Model"]}, {"name": "Special", "symbols": ["Special"]}])
    assert out["pairs"][0]["kind"] == "calls"
    assert out["pairs"][0]["path"] == ["ext.Special", "core.Model"]


def test_shared_dependents(blog):
    out = preflight(blog, [SLUG, RENDER])
    p = pair(out, "Slug", "Render")
    assert p == {"a": "Slug", "b": "Render", "kind": "shared_dependents",
                 "symbols": ["tests.test_views.test_render_post"], "path": [], "shared": 1}


def test_pairs_with_nothing_in_common_are_left_out(blog):
    assert preflight(blog, [TAGS, RENDER])["pairs"] == []


def test_strongest_kind_wins(blog):
    # Same symbol and a caller in the cone: one entry, same_symbol.
    out = preflight(blog, [{"name": "A", "symbols": ["slugify"]}, {"name": "B", "symbols": ["slugify", "Tag.save"]}])
    assert [p["kind"] for p in out["pairs"]] == ["same_symbol"]


# Groups


def test_chain_plus_independent_task_gives_two_groups(blog):
    out = preflight(blog, [SLUG, TAGS, WORDS])
    assert out["groups"] == [{"tasks": ["Slug", "Tags"], "coordinate": True},
                             {"tasks": ["Words"], "coordinate": False}]
    assert out["summary"] == "Two groups. Slug and Tags must coordinate; Words can run in parallel."


def test_shared_dependents_alone_do_not_force_coordination(blog):
    out = preflight(blog, [SLUG, RENDER])
    assert [g["coordinate"] for g in out["groups"]] == [False, False]
    assert out["summary"] == "Both tasks can run in parallel. Neither changes or calls what the other changes."


def test_groups_join_through_a_middle_task(blog):
    out = preflight(blog, [SLUG, RENDER, TAGS, {"name": "Words", "symbols": ["truncate_words", "slugify"]}])
    assert out["groups"] == [{"tasks": ["Slug", "Tags", "Words"], "coordinate": True},
                             {"tasks": ["Render"], "coordinate": False}]
    assert out["summary"] == "Two groups. Slug, Tags and Words must coordinate; Render can run in parallel."


def test_summary_for_several_parallel_tasks(blog):
    out = preflight(blog, [SLUG, TAGS, RENDER, {"name": "Url", "symbols": ["get_absolute_url"]}])
    assert out["summary"] == "Three groups. Slug and Tags must coordinate; the others can run in parallel."
    out = preflight(blog, [TAGS, RENDER, {"name": "Url", "symbols": ["get_absolute_url"]}])
    assert out["summary"] == "All three tasks can run in parallel. None changes or calls what another changes."


# Cones, hot spots, the whole answer


def test_tasks_carry_resolved_symbols_and_cones(blog):
    out = preflight(blog, [SLUG, {"name": "Twice", "symbols": ["Tag.save", "tags.models.Tag.save"]}])
    slug, twice = out["tasks"]
    assert slug["symbols"] == ["utils.text.slugify"] and twice["symbols"] == ["tags.models.Tag.save"]
    assert slug["cone"] == 6
    # Nearest first, code before tests.
    assert slug["cone_sample"][:3] == ["blog.models.Post.save", "tags.models.Tag.save", "tests.test_text.test_slugify"]
    assert preflight(blog, [SLUG, TAGS], depth=1)["tasks"][0]["cone"] == 3


def test_depth_is_clamped_and_must_be_a_number(blog):
    assert preflight(blog, [SLUG, TAGS], depth=99) == preflight(blog, [SLUG, TAGS], depth=4)
    assert preflight(blog, [SLUG, TAGS], depth="1")["tasks"][0]["cone"] == 3
    for bad in ("deep", None, True, [2]):
        with pytest.raises(PreflightError, match="depth"):
            preflight(blog, [SLUG, TAGS], depth=bad)


def test_hot_spots_are_in_play_and_ranked_by_betweenness(blog):
    assert preflight(blog, [SLUG, TAGS])["hot"] == [{"qualname": "tags.models.Tag.save", "betweenness": 1.0}]
    # Tag.save is outside these cones, so it is not in play.
    assert preflight(blog, [RENDER, WORDS])["hot"] == []


def test_same_answer_every_time_and_no_dashes(blog):
    tasks = [SLUG, TAGS, RENDER, WORDS]
    first = preflight(blog, tasks)
    assert first == preflight(blog, tasks)
    assert set(first) == {"tasks", "pairs", "groups", "hot", "summary"}
    assert no_dashes(as_text(first)) and no_dashes(first["summary"])


def test_one_symbol_graph_skips_the_algorithms_that_need_two(graph, tmp_path):
    (tmp_path / "solo").mkdir()
    (tmp_path / "solo" / "one.py").write_text("def only():\n    return 1\n")
    index_repo(graph, tmp_path / "solo")
    out = preflight(graph, [{"name": "A", "symbols": ["only"]}, {"name": "B", "symbols": ["one.only"]}])
    assert out["pairs"][0]["kind"] == "same_symbol"
    assert out["hot"] == []
    assert out["groups"] == [{"tasks": ["A", "B"], "coordinate": True}]


# Temporary nodes


def test_temporary_nodes_are_gone_afterwards(blog):
    preflight(blog, [SLUG, TAGS, RENDER])
    assert temp_nodes(blog) == 0


class FailingWcc:
    """The graph, except that algo.WCC fails, after the Flight nodes are written."""

    def __init__(self, graph):
        self.graph = graph
        self.seen_temp = 0

    def query(self, cypher, params=None):
        if "algo.WCC" in cypher:
            self.seen_temp = temp_nodes(self.graph)
            raise RuntimeError("WCC went away")
        return self.graph.query(cypher, params)


def test_temporary_nodes_are_gone_when_preflight_raises(blog):
    failing = FailingWcc(blog)
    with pytest.raises(RuntimeError, match="WCC went away"):
        preflight(failing, [SLUG, TAGS, WORDS])
    assert failing.seen_temp == 4  # one Flight, three FlightTasks
    assert temp_nodes(blog) == 0


def test_other_plans_on_the_graph_do_not_join_the_groups(blog):
    blog.query("CREATE (:FlightTask {flight: 'other', name: 'Slug'})-[:MEETS]->(:FlightTask {flight: 'other', name: 'Words'})")
    out = preflight(blog, [SLUG, TAGS, WORDS])
    assert out["groups"][1] == {"tasks": ["Words"], "coordinate": False}
    assert temp_nodes(blog) == 2  # only the other plan's nodes are left


# Finding and resolving symbols


def test_find_symbols(blog):
    found = find_symbols(blog, "SLUG")
    assert [s["qualname"] for s in found] == ["utils.text.slugify", "tests.test_text.test_slugify"]
    assert found[0] == {"qualname": "utils.text.slugify", "kind": "function",
                        "signature": "slugify(value, allow_unicode=False)"}
    assert find_symbols(blog, "save", limit=1) == [
        {"qualname": "tags.models.Tag.save", "kind": "method", "signature": "save(self)"}]
    assert find_symbols(blog, "") == [] and find_symbols(blog, "   ") == []
    assert find_symbols(blog, "zzz") == []


def test_resolve_exact_and_suffix(blog):
    assert resolve_symbol(blog, "utils.text.slugify") == "utils.text.slugify"
    assert resolve_symbol(blog, "slugify") == "utils.text.slugify"
    assert resolve_symbol(blog, "text.truncate_words") == "utils.text.truncate_words"
    assert resolve_symbol(blog, " Post.save ") == "blog.models.Post.save"


def test_resolve_package_reexport(synthetic):
    assert resolve_symbol(synthetic, "pkg.thing") == "pkg.impl.thing"


def test_resolve_ambiguous_gives_the_candidates(blog):
    with pytest.raises(PreflightError) as e:
        resolve_symbol(blog, "save")
    assert e.value.message == "save matches several symbols."
    assert e.value.suggestions == ["tags.models.Tag.save", "blog.models.Post.save"]


def test_resolve_unknown_suggests_near_names(blog):
    with pytest.raises(PreflightError) as e:
        resolve_symbol(blog, "slugifyy")
    assert e.value.message == "No symbol named slugifyy."
    assert e.value.suggestions[0] == "utils.text.slugify"
    with pytest.raises(PreflightError) as e:
        resolve_symbol(blog, "qqqqqq")
    assert e.value.suggestions == []
    with pytest.raises(PreflightError, match="empty"):
        resolve_symbol(blog, " ")


@pytest.mark.parametrize("tasks, message", [
    ("Slug", "Tasks must be a list"),
    ([SLUG], "takes 2 to 6 tasks, not 1"),
    ([{"name": f"T{i}", "symbols": ["slugify"]} for i in range(7)], "takes 2 to 6 tasks, not 7"),
    ([SLUG, "Tags"], "Task 2 must have a name and symbols."),
    ([SLUG, {"name": " ", "symbols": ["slugify"]}], "Task 2 has no name."),
    ([SLUG, {"name": "x" * 61, "symbols": ["slugify"]}], "longer than 60 characters"),
    ([SLUG, {"name": "a\nb", "symbols": ["slugify"]}], "one line"),
    ([SLUG, {"name": "Slug", "symbols": ["Tag.save"]}], "Two tasks are named Slug."),
    ([SLUG, {"name": "Tags", "symbols": []}], "Tags needs 1 to 10 symbols, not 0."),
    ([SLUG, {"name": "Tags", "symbols": ["slugify"] * 11}], "Tags needs 1 to 10 symbols, not 11."),
    ([SLUG, {"name": "Tags", "symbols": "Tag.save"}], "Tags needs a list of symbols."),
    ([SLUG, {"name": "Tags", "symbols": [3]}], "Tags needs a list of symbols."),
    ([SLUG, {"name": "Tags", "symbols": ["nothing_like_it"]}], "No symbol named nothing_like_it."),
])
def test_validation_errors(blog, tasks, message):
    with pytest.raises(PreflightError, match=message.replace(".", r"\.").replace("(", r"\(")):
        preflight(blog, tasks)
    assert temp_nodes(blog) == 0


# The demo API


@pytest.fixture
def demo_blog(db):
    """A Demos with the blog under a test graph name, not built yet. The graph is deleted afterwards."""
    name = f"test_demo_{uuid.uuid4().hex[:12]}"
    demos = Demos([DemoRepo("blog", "Sample blog", name, FIXTURE_REPO)], connect=lambda: db)
    yield demos
    if name in db.list_graphs():
        db.select_graph(name).delete()


def demo_client(demos, **limits) -> TestClient:
    """The demo routes as create_app mounts them, or on their own app with other rate limits."""
    if not limits:
        return TestClient(create_app(lambda: None, demos=demos))
    app = FastAPI()

    @app.exception_handler(ApiError)
    async def refused(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.text})

    app.include_router(preflight_routes.router(demos, **limits))
    return TestClient(app)


def test_demo_routes_answer_503_until_the_graph_is_ready(demo_blog):
    c = demo_client(demo_blog)
    assert c.get("/api/preflight/repos").json() == {"repos": []}
    building = {"error": "The Sample blog graph is still being built. Try again in a few seconds."}
    r = c.post("/api/preflight", json={"repo": "blog", "tasks": [SLUG, TAGS]})
    assert (r.status_code, r.json()) == (503, building)
    assert c.get("/api/preflight/symbols", params={"repo": "blog", "q": "slug"}).status_code == 503

    demo_blog.build()
    assert c.get("/api/preflight/repos").json() == {"repos": [{"id": "blog", "name": "Sample blog", "symbols": 17}]}
    r = c.post("/api/preflight", json={"repo": "blog", "tasks": [SLUG, TAGS, WORDS]})
    assert r.status_code == 200
    assert r.json()["groups"][0] == {"tasks": ["Slug", "Tags"], "coordinate": True}
    symbols = c.get("/api/preflight/symbols", params={"repo": "blog", "q": "slug"}).json()["symbols"]
    assert symbols[0]["qualname"] == "utils.text.slugify"


def test_flask_still_building_message(db):
    demos = Demos([DemoRepo("flask", "Flask", "demo_flask_never_built", Path("/nowhere"))], connect=lambda: db)
    r = demo_client(demos).post("/api/preflight", json={"repo": "flask", "tasks": [SLUG, TAGS]})
    assert r.status_code == 503
    assert r.json() == {"error": "The Flask graph is still being built. Try again in a few seconds."}


def test_demo_errors(demo_blog):
    demo_blog.build()
    c = demo_client(demo_blog)
    r = c.post("/api/preflight", json={"repo": "blog", "tasks": [SLUG, {"name": "Tags", "symbols": ["save"]}]})
    assert r.status_code == 422
    assert r.json() == {"error": "save matches several symbols.",
                        "suggestions": ["tags.models.Tag.save", "blog.models.Post.save"]}
    r = c.post("/api/preflight", json={"repo": "blog", "tasks": [SLUG]})
    assert r.status_code == 422 and r.json()["suggestions"] == []
    r = c.post("/api/preflight", json={"repo": "django", "tasks": [SLUG, TAGS]})
    assert (r.status_code, r.json()) == (404, {"error": "No such demo repo."})


def test_demo_rate_limit(demo_blog):
    demo_blog.build()
    c = demo_client(demo_blog, per_minute=2, symbols_per_minute=1)
    body = {"repo": "blog", "tasks": [SLUG, TAGS]}
    assert [c.post("/api/preflight", json=body).status_code for _ in range(3)] == [200, 200, 429]
    r = c.post("/api/preflight", json=body)
    assert int(r.headers["Retry-After"]) >= 1
    assert [c.get("/api/preflight/symbols", params={"repo": "blog", "q": "s"}).status_code for _ in range(2)] == [
        200, 429]


def test_default_limit_is_30_a_minute(demo_blog):
    demo_blog.build()
    c = demo_client(demo_blog)
    body = {"repo": "blog", "tasks": [SLUG, TAGS]}
    codes = [c.post("/api/preflight", json=body).status_code for _ in range(31)]
    assert codes.count(200) == 30 and codes[-1] == 429


def test_demo_that_cannot_reach_falkordb_reports_it(tmp_path):
    def down():
        raise ConnectionError("refused")

    demos = Demos([DemoRepo("blog", "Sample blog", "never", FIXTURE_REPO)], connect=down, attempts=3,
                  sleep=lambda s: None)
    demos.build()
    r = demo_client(demos).post("/api/preflight", json={"repo": "blog", "tasks": [SLUG, TAGS]})
    assert (r.status_code, r.json()) == (503, {"error": "The Sample blog graph could not be built on this server."})


def test_app_without_demos_serves_none():
    c = TestClient(create_app(lambda: None))
    assert c.get("/api/preflight/repos").json() == {"repos": []}
    assert c.post("/api/preflight", json={"repo": "flask", "tasks": [SLUG, TAGS]}).status_code == 404


def test_demos_from_env(tmp_path):
    flask, blog = tmp_path / "flask", tmp_path / "blog"
    flask.mkdir()
    blog.mkdir()
    demos = Demos.from_env({"AIRSPACE_FLASK_REPO": str(flask), "AIRSPACE_PLAYGROUND_REPO": str(blog)})
    assert [(r.id, r.name, r.graph, r.path) for r in demos.repos.values()] == [
        ("flask", "Flask", "demo_flask", flask), ("blog", "Sample blog", "demo_blog", blog)]
    # A Flask path that does not exist is skipped; the blog falls back to the bundled fixture.
    demos = Demos.from_env({"AIRSPACE_FLASK_REPO": str(tmp_path / "missing")})
    assert [(r.id, r.path) for r in demos.repos.values()] == [("blog", FIXTURE_REPO)]


def test_default_app_starts_indexing_in_the_background(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(Demos, "from_env", classmethod(lambda cls: Demos([])))
    monkeypatch.setattr(Demos, "start", lambda self: started.append(self))
    api_app.default_app(tmp_path)
    assert len(started) == 1


# The workspace routes


@pytest.fixture
def ws(client, cloud):
    sign_in(client, cloud)
    wid, key = new_workspace(client, cloud)
    index_repo(cloud.engine(wid).graph, FIXTURE_REPO)
    return wid, key


def test_workspace_preflight_for_its_owner(client, cloud, ws):
    wid, _ = ws
    r = client.post(f"/api/w/{wid}/preflight", json={"tasks": [SLUG, TAGS, WORDS]}, headers=WRITE)
    assert r.status_code == 200, r.text
    assert r.json()["pairs"][0]["path"] == ["tags.models.Tag.save", "utils.text.slugify"]
    r = client.get(f"/api/w/{wid}/preflight/symbols", params={"q": "truncate"})
    assert r.json() == {"symbols": [{"qualname": "utils.text.truncate_words", "kind": "function",
                                     "signature": "truncate_words(text, count=30)"}]}
    r = client.post(f"/api/w/{wid}/preflight", json={"tasks": [SLUG, {"name": "X", "symbols": ["nope"]}]}, headers=WRITE)
    assert r.status_code == 422 and r.json()["error"] == "No symbol named nope."
    assert temp_nodes(cloud.engine(wid).graph) == 0


def test_workspace_preflight_needs_the_header_and_the_owner(client, cloud, ws):
    wid, _ = ws
    body = {"tasks": [SLUG, TAGS]}
    r = client.post(f"/api/w/{wid}/preflight", json=body)
    assert r.status_code == 403 and "X-Airspace: 1" in r.json()["error"]
    other = app_client(cloud)
    assert other.post(f"/api/w/{wid}/preflight", json=body, headers=WRITE).status_code == 401
    assert other.get(f"/api/w/{wid}/preflight/symbols", params={"q": "s"}).status_code == 401
    sign_in(other, cloud, github_id=2, login="bob")
    assert other.post(f"/api/w/{wid}/preflight", json=body, headers=WRITE).status_code == 404
    assert other.get(f"/api/w/{wid}/preflight/symbols", params={"q": "s"}).status_code == 404


# RPC and the remote client


def test_graph_preflight_over_rpc_dispatch(blog):
    assert "graph.preflight" in GRAPH_METHODS
    air = Airspace(blog)
    out = wire.decode(dispatch(air, blog, "graph.preflight", wire.encode([[SLUG, TAGS], 1]), {}))
    assert out == preflight(blog, [SLUG, TAGS], 1)
    out = dispatch(air, blog, "graph.preflight", [[SLUG, {"name": "T", "symbols": ["save"]}]], {})
    assert out == {"error": "save matches several symbols.",
                   "suggestions": ["tags.models.Tag.save", "blog.models.Post.save"]}
    with pytest.raises(RpcError, match="Bad arguments"):
        dispatch(air, blog, "graph.preflight", [], {})


def rpc_client(client, key) -> RpcClient:
    """An RpcClient whose requests go to the test app, as the CLI's would go to the hosted server."""

    def forward(request: httpx.Request) -> httpx.Response:
        r = client.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        return httpx.Response(r.status_code, headers=r.headers, content=r.content)

    return RpcClient("https://testserver", key, transport=httpx.MockTransport(forward))


def test_remote_preflight_round_trip(client, cloud, ws):
    _, key = ws
    remote = RemoteAirspace(rpc_client(client, key), Path("/nonexistent"))
    out = remote.preflight([SLUG, TAGS, WORDS])
    assert out["summary"] == "Two groups. Slug and Tags must coordinate; Words can run in parallel."
    with pytest.raises(PreflightError) as e:
        remote_preflight(remote.client, [SLUG, {"name": "T", "symbols": ["slugifyy"]}])
    assert e.value.message == "No symbol named slugifyy." and e.value.suggestions[0] == "utils.text.slugify"


# CLI


ARGS = ["--task", "Slug: slugify", "--task", "Tags: Tag.save", "--task", "Words: truncate_words"]


def test_cli_prints_summary_groups_pairs_and_hot_spots(blog, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_graph", lambda root: blog)
    assert cli.main(["preflight", "--root", str(tmp_path), *ARGS]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Two groups. Slug and Tags must coordinate; Words can run in parallel.\n")
    assert "Must coordinate\n  Slug, Tags\nCan run in parallel\n  Words\n" in out
    assert "  Slug and Tags: calls, tags.models.Tag.save -> utils.text.slugify\n" in out
    assert "Hot spots (1)\n  tags.models.Tag.save  betweenness 1.0" in out
    assert out.strip() == as_text(preflight(blog, [SLUG, TAGS, WORDS]))


def test_cli_depth_and_task_parsing(blog, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_graph", lambda root: blog)
    assert cli.main(["preflight", "--root", str(tmp_path), "--task", "Rename: slug: slugify, Post.save",
                     "--task", "Tags: Tag.save", "--depth", "1"]) == 0
    out = capsys.readouterr().out
    assert "  Rename: slug: utils.text.slugify, blog.models.Post.save (cone 4)" in out
    assert cli._parse_task(" A : x ,, y ") == {"name": "A", "symbols": ["x", "y"]}


def test_cli_errors_exit_1_with_suggestions(blog, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_graph", lambda root: blog)
    assert cli.main(["preflight", "--root", str(tmp_path), "--task", "A: slugify", "--task", "B: save"]) == 1
    err = capsys.readouterr().err
    assert "airspace: save matches several symbols." in err
    assert "Did you mean:\n  tags.models.Tag.save\n  blog.models.Post.save" in err
    assert cli.main(["preflight", "--root", str(tmp_path), "--task", "no colon here", "--task", "B: save"]) == 1
    assert 'Write each task as "Name: symbol, symbol"' in capsys.readouterr().err

    def down(root):
        raise ConnectionError("refused")

    monkeypatch.setattr(cli, "_graph", down)
    assert cli.main(["preflight", "--root", str(tmp_path), *ARGS]) == 1
    assert "FalkorDB unavailable" in capsys.readouterr().err


def test_cli_in_remote_mode_uses_the_workspace(client, cloud, ws, tmp_path, monkeypatch, capsys):
    _, key = ws

    def no_local_graph(root):
        raise AssertionError("remote mode opened a local graph")

    monkeypatch.setattr(cli, "_graph", no_local_graph)
    monkeypatch.setattr(cli, "_remote", lambda root: rpc_client(client, key))
    assert cli.main(["preflight", "--root", str(tmp_path), *ARGS]) == 0
    assert "tags.models.Tag.save -> utils.text.slugify" in capsys.readouterr().out
    assert cli.main(["preflight", "--root", str(tmp_path), "--task", "A: slugify", "--task", "B: nope"]) == 1
    assert "No symbol named nope." in capsys.readouterr().err


# MCP


def test_mcp_tool_answers_the_cli_text(blog, tmp_path):
    air = Airspace(blog)
    assert mcp.preflight(air, [SLUG, TAGS, WORDS]) == as_text(preflight(blog, [SLUG, TAGS, WORDS]))
    text = mcp.preflight(air, [SLUG, {"name": "T", "symbols": ["save"]}])
    assert text == "save matches several symbols. Did you mean: tags.models.Tag.save, blog.models.Post.save?"

    server = mcp.build_server(tmp_path, env={}, airspace_factory=lambda root: air)

    async def run():
        return await server.call_tool("preflight", {"tasks": [SLUG, TAGS]})

    result = anyio.run(run)
    assert "tags.models.Tag.save -> utils.text.slugify" in str(result)
    assert temp_nodes(blog) == 0


def test_plan_for_uses_the_remote_engine_when_there_is_one():
    class Remote:
        def preflight(self, tasks, depth):
            return {"remote": tasks, "depth": depth}

    assert pf.plan_for(Remote(), [SLUG], 3) == {"remote": [SLUG], "depth": 3}
