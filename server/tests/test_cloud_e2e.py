"""The whole hosted path at once: the real cloud server on a socket, the real remote client and the real hooks.

A developer signs in through GitHub (faked), makes a workspace, connects a git repo with `airspace connect`, and
runs two Claude Code sessions through the hooks. The held edit shows up in that workspace's Tower routes, and
nowhere else: not in the demo Tower, not in a graph on the developer's machine.
"""

import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from airspace import cli
from airspace.api.app import create_app
from airspace.graph.db import graph_name
from airspace.hooks.handlers import default_deps
from bench_refs import REFS, Agent
from cloud_helpers import DemoAirspace, github, make_cloud  # noqa: F401 (fixtures)

SLUG_A, SLUG_B = REFS["slugify-keyword-only"]
WRITE = {"X-Airspace": "1"}


@pytest.fixture
def live(make_cloud):
    """The API with a signed-in cloud on a real local port. Yields (base url, cloud)."""
    import uvicorn

    cloud = make_cloud()
    app = create_app(DemoAirspace, cloud=cloud, max_seconds=1.0)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the API did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", cloud
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def repo(blog_repo):
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(blog_repo), "-c", "user.name=airspace", "-c",
                        "user.email=airspace@example.invalid", *args], check=True, capture_output=True)
    return blog_repo


def _sign_in(base: str) -> httpx.Client:
    """Through the real routes: login redirects to GitHub, the callback sets the session."""
    browser = httpx.Client(base_url=base, follow_redirects=False)
    to_github = browser.get("/auth/github/login", params={"next": "/app"})
    assert to_github.status_code == 302
    _keep_cookies(browser, to_github)
    state = parse_qs(urlparse(to_github.headers["location"]).query)["state"][0]
    back = browser.get("/auth/github/callback", params={"code": "good-code", "state": state})
    assert back.status_code == 302 and back.headers["location"].endswith("/app"), back.text
    _keep_cookies(browser, back)
    return browser


def _keep_cookies(browser: httpx.Client, response: httpx.Response) -> None:
    """The cookies are Secure (the public URL is https) and this socket is plain http, so carry them by hand."""
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        browser.cookies.set(name, rest.split(";", 1)[0])


def test_sign_in_connect_and_watch_your_own_sessions(db, live, repo, monkeypatch, capsys):
    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    base, cloud = live

    browser = _sign_in(base)
    assert browser.get("/api/me").json()["user"]["login"] == "octo"
    made = browser.post("/api/workspaces", json={"name": "blog"}, headers=WRITE).json()
    wid, key = made["workspace"]["id"], made["key"]
    cloud.made_ws.add(wid)

    assert cli.main(["connect", "--root", str(repo), "--server", base, "--key", key]) == 0
    assert f"{base}/w/{wid}" in capsys.readouterr().out

    deps = default_deps()
    a, b = Agent(repo, "agent-a", "sess-aaaa", deps), Agent(repo, "agent-b", "sess-bbbb", deps)
    assert a.apply(SLUG_A), a.holds
    assert b.apply(SLUG_B) is False
    assert "slugify(value, *, unicode=False)" in b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]

    # The owner's Tower shows both agents and the hold.
    state = browser.get(f"/api/w/{wid}/state").json()
    assert {x["id"] for x in state["agents"]} == {"agent-a", "agent-b"}
    assert [c["held_agent"] for c in state["collisions"]] == ["agent-b"]
    assert browser.get(f"/api/w/{wid}/mode").json() == {"mode": "live"}
    assert browser.get("/api/me").json()["workspaces"][0]["agents_flying"] == 2

    # Nobody else sees it: not signed out, not another account, not the public demo.
    assert httpx.get(f"{base}/api/w/{wid}/state").status_code == 401
    assert httpx.get(f"{base}/api/state").json()["agents"] == [{"id": "demo-agent", "status": "active"}]
    # And no graph was made for the repo on this machine.
    assert graph_name(repo) not in db.list_graphs()

    # Rotating the key cuts the old one off: the hooks fail open with one line, and the edit goes ahead.
    browser.post(f"/api/workspaces/{wid}/key", headers=WRITE)
    assert b.apply({"blog/views.py": ("<article>", "<article class=\"post\">")})
    assert "Airspace server unavailable" in capsys.readouterr().err
