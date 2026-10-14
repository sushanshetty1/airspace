"""Fixtures for the cloud tests: a Cloud on a uniquely named accounts graph, a fake GitHub, and signed-in clients.

Every graph a test creates (the accounts graph and each ws_<id> graph) is deleted afterwards, so the real
airspace_accounts graph and other agents' graphs on the shared FalkorDB are never touched.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from airspace.api.app import create_app
from airspace.cloud import Cloud, CloudConfig
from airspace.cloud import session

SECRET = "test-secret-" + "x" * 32
PUBLIC_URL = "https://airspace.test"
DEMO_STATE = {"now": 1.0, "agents": [{"id": "demo-agent", "status": "active"}], "collisions": []}


class DemoAirspace:
    """The single demo engine behind /api/..., so tests can tell it apart from a workspace engine."""

    def state(self):
        return DEMO_STATE


class FakeGitHub:
    """GitHub's token and user endpoints. `code` is the one code it accepts; `profile` is who signs in."""

    def __init__(self):
        self.code = "good-code"
        self.profile = {"id": 4242, "login": "octo", "name": "Octo Cat", "avatar_url": "https://avatars.test/octo"}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/login/oauth/access_token":
            ok = f"code={self.code}" in request.content.decode()
            return httpx.Response(200, json={"access_token": "tok"} if ok else {"error": "bad_verification_code"})
        if request.url.path == "/user":
            if request.headers.get("authorization") != "Bearer tok":
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json=self.profile)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def drop_cloud_graphs(db, accounts_graph: str) -> None:
    graphs = set(db.list_graphs())
    if accounts_graph in graphs:
        g = db.select_graph(accounts_graph)
        for (wid,) in g.query("MATCH (w:Workspace) RETURN w.id").result_set:
            if f"ws_{wid}" in graphs:
                db.select_graph(f"ws_{wid}").delete()
        g.delete()


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def make_cloud(db, github):
    """Builds a Cloud on a fresh accounts graph. Workspace graphs left behind are found through it and deleted."""
    names: list[str] = []
    made_ws: set[str] = set()

    def build(signin: bool = True, **kw) -> Cloud:
        name = f"test_accounts_{uuid.uuid4().hex[:12]}"
        names.append(name)
        if signin:
            config = CloudConfig(github_client_id="cid", github_client_secret="csecret", secret=SECRET,
                                 public_url=PUBLIC_URL, accounts_graph=name)
        else:
            config = CloudConfig(accounts_graph=name)
        cloud = Cloud(config, connect=lambda: db, http=github.client, **kw)
        cloud.made_ws = made_ws
        return cloud

    yield build
    for name in names:
        drop_cloud_graphs(db, name)
    # Workspaces whose records a test deleted but whose graph somehow survived.
    graphs = set(db.list_graphs())
    for wid in made_ws:
        if f"ws_{wid}" in graphs:
            db.select_graph(f"ws_{wid}").delete()


@pytest.fixture
def cloud(make_cloud):
    return make_cloud()


def app_client(cloud: Cloud) -> TestClient:
    return TestClient(create_app(DemoAirspace, cloud=cloud), base_url="https://testserver")


@pytest.fixture
def client(cloud):
    return app_client(cloud)


def sign_in(client: TestClient, cloud: Cloud, github_id: int = 1, login: str = "alice") -> str:
    """Upsert a user and give the client their session cookie. Returns the user id."""
    user_id = cloud.accounts().upsert_user(
        {"id": github_id, "login": login, "name": login.title(), "avatar_url": f"https://avatars.test/{login}"}
    )
    # Scoped like the server's own cookie (cookiejar names a dotless host .local), so a logout replaces it.
    client.cookies.set(session.COOKIE, session.sign(user_id, cloud.config.secret), domain="testserver.local", path="/")
    return user_id


WRITE = {"X-Airspace": "1"}


def new_workspace(client: TestClient, cloud: Cloud, name: str = "blog") -> tuple[str, str]:
    """(workspace id, key) for a workspace made through the API."""
    r = client.post("/api/workspaces", json={"name": name}, headers=WRITE)
    assert r.status_code == 200, r.text
    wid = r.json()["workspace"]["id"]
    cloud.made_ws.add(wid)
    return wid, r.json()["key"]
