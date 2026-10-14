import re
from urllib.parse import parse_qs, urlparse

from cloud_helpers import (  # noqa: F401 (fixtures)
    DEMO_STATE,
    PUBLIC_URL,
    WRITE,
    app_client,
    client,
    cloud,
    github,
    make_cloud,
    new_workspace,
    sign_in,
)

from airspace.cloud import session
from airspace.cloud.accounts import MAX_WORKSPACES, key_hash


def _users(cloud):
    return cloud.accounts().graph.query(
        "MATCH (u:User) RETURN u.github_id, u.login, u.name, u.avatar_url ORDER BY u.github_id"
    ).result_set


def _start_login(client, next_path=None):
    r = client.get("/auth/github/login", params={"next": next_path} if next_path else None, follow_redirects=False)
    assert r.status_code == 302
    location = urlparse(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://github.com/login/oauth/authorize"
    query = parse_qs(location.query)
    assert query["scope"] == ["read:user"]
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == [f"{PUBLIC_URL}/auth/github/callback"]
    return query["state"][0]


# Sign-in


def test_login_sets_a_state_cookie_matching_the_redirect(client):
    state = _start_login(client)
    assert client.cookies.get("airspace_oauth_state").split(".")[0] == state


def test_callback_signs_in_and_upserts_the_user(client, cloud, github):
    state = _start_login(client, "/w/0123456789ab")
    r = client.get("/auth/github/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/w/0123456789ab"
    set_cookie = [v for k, v in r.headers.multi_items() if k == "set-cookie"]
    sess = next(c for c in set_cookie if c.startswith(session.COOKIE + "="))
    assert "HttpOnly" in sess and "Secure" in sess and "samesite=lax" in sess.lower() and "Path=/" in sess
    assert f"Max-Age={session.MAX_AGE}" in sess
    assert _users(cloud) == [[4242, "octo", "Octo Cat", "https://avatars.test/octo"]]

    me = client.get("/api/me").json()
    assert me == {
        "user": {"login": "octo", "name": "Octo Cat", "avatar_url": "https://avatars.test/octo"},
        "workspaces": [],
        "signin": True,
    }

    # Signing in again updates the same user rather than making a second one.
    github.profile = {**github.profile, "name": "Octo Renamed"}
    state = _start_login(client)
    client.get("/auth/github/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    assert _users(cloud) == [[4242, "octo", "Octo Renamed", "https://avatars.test/octo"]]
    # The token exchange posted the client secret, never the browser.
    assert b"client_secret=csecret" in github.requests[0].content


def test_callback_rejects_a_state_mismatch(client, cloud):
    _start_login(client)
    r = client.get("/auth/github/callback", params={"code": "good-code", "state": "forged"}, follow_redirects=False)
    assert r.status_code == 400
    assert "state" in r.json()["error"]
    assert _users(cloud) == []
    assert client.get("/api/me").json()["user"] is None


def test_callback_without_a_state_cookie_is_rejected(client):
    r = client.get("/auth/github/callback", params={"code": "good-code", "state": "x"}, follow_redirects=False)
    assert r.status_code == 400


def test_callback_sanitises_next(client):
    state = _start_login(client, "//evil.example/steal")
    r = client.get("/auth/github/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/app"


def test_callback_with_a_code_github_refuses(client, cloud):
    state = _start_login(client)
    r = client.get("/auth/github/callback", params={"code": "bad", "state": state}, follow_redirects=False)
    assert r.status_code == 502
    assert _users(cloud) == []


def test_logout_clears_the_session(client, cloud):
    sign_in(client, cloud)
    assert client.post("/auth/logout").status_code == 403
    r = client.post("/auth/logout", headers=WRITE)
    assert r.json() == {"ok": True}
    assert client.get("/api/me").json()["user"] is None


def test_me_signed_out(client):
    assert client.get("/api/me").json() == {"user": None, "workspaces": [], "signin": True}


def test_me_with_a_forged_cookie(client, cloud):
    sign_in(client, cloud)
    client.cookies.set(session.COOKIE, session.sign("someoneelse", "another-secret-" + "y" * 32))
    assert client.get("/api/me").json()["user"] is None


def test_signin_not_configured(make_cloud):
    cloud = make_cloud(signin=False)
    c = app_client(cloud)
    for path in ("/auth/github/login", "/auth/github/callback"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 503
        assert r.json() == {"error": "Sign-in is not configured on this server."}
    assert c.get("/api/me").json() == {"user": None, "workspaces": [], "signin": False}
    # Keys made before still work.
    user = cloud.accounts().upsert_user({"id": 7, "login": "kim"})
    _, key = cloud.accounts().create_workspace(user, "repo")
    r = c.post("/api/rpc", json={"method": "graph.known"}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json() == {"ok": True, "result": []}


# Workspaces


def test_create_workspace(client, cloud):
    sign_in(client, cloud)
    r = client.post("/api/workspaces", json={"name": "  my blog  "}, headers=WRITE)
    assert r.status_code == 200
    body = r.json()
    ws, key = body["workspace"], body["key"]
    cloud.made_ws.add(ws["id"])
    assert re.fullmatch(r"[0-9a-f]{12}", ws["id"])
    assert re.fullmatch(r"ask_[0-9a-f]{40}", key)
    assert ws["name"] == "my blog"
    assert ws["key_prefix"] == key[:12]
    assert ws["agents_flying"] == 0
    # The graph exists from the start, and only the key's hash is stored.
    assert f"ws_{ws['id']}" in cloud.db().list_graphs()
    stored = cloud.accounts().graph.query("MATCH (k:Key) RETURN k.hash, k.prefix").result_set
    assert stored == [[key_hash(key), key[:12]]]

    me = client.get("/api/me").json()
    assert me["workspaces"] == [ws]


def test_create_workspace_needs_a_session_and_the_header(client, cloud):
    assert client.post("/api/workspaces", json={"name": "x"}, headers=WRITE).status_code == 401
    assert client.post("/api/workspaces", json={"name": "x"}, headers=WRITE).json() == {"error": "Sign in first."}
    sign_in(client, cloud)
    r = client.post("/api/workspaces", json={"name": "x"})
    assert r.status_code == 403
    assert client.get("/api/me").json()["workspaces"] == []


def test_workspace_names(client, cloud):
    sign_in(client, cloud)
    for name in ("", "   ", "x" * 61):
        r = client.post("/api/workspaces", json={"name": name}, headers=WRITE)
        assert r.status_code == 422, name
    new_workspace(client, cloud, "x" * 60)


def test_workspace_limit(client, cloud):
    sign_in(client, cloud)
    for i in range(MAX_WORKSPACES):
        new_workspace(client, cloud, f"repo {i}")
    r = client.post("/api/workspaces", json={"name": "one more"}, headers=WRITE)
    assert r.status_code == 409
    assert "5 workspaces" in r.json()["error"]
    assert len(client.get("/api/me").json()["workspaces"]) == MAX_WORKSPACES


def test_rotate_key(client, cloud):
    sign_in(client, cloud)
    wid, old = new_workspace(client, cloud)
    assert client.post(f"/api/workspaces/{wid}/key").status_code == 403
    r = client.post(f"/api/workspaces/{wid}/key", headers=WRITE)
    new = r.json()["key"]
    assert new != old and re.fullmatch(r"ask_[0-9a-f]{40}", new)
    assert client.get("/api/me").json()["workspaces"][0]["key_prefix"] == new[:12]
    call = {"method": "graph.known"}
    assert client.post("/api/rpc", json=call, headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.post("/api/rpc", json=call, headers={"Authorization": f"Bearer {new}"}).status_code == 200
    assert cloud.accounts().graph.query("MATCH (k:Key) RETURN count(k)").result_set == [[1]]


def test_delete_workspace_deletes_its_graph(client, cloud):
    sign_in(client, cloud)
    wid, key = new_workspace(client, cloud)
    assert client.delete(f"/api/workspaces/{wid}").status_code == 403
    assert client.delete(f"/api/workspaces/{wid}", headers=WRITE).json() == {"ok": True}
    assert f"ws_{wid}" not in cloud.db().list_graphs()
    assert client.get("/api/me").json()["workspaces"] == []
    assert cloud.accounts().graph.query("MATCH (n) WHERE n:Workspace OR n:Key RETURN count(n)").result_set == [[0]]
    r = client.post("/api/rpc", json={"method": "graph.known"}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 401
    assert client.get(f"/api/w/{wid}/state").status_code == 404
    assert client.delete(f"/api/workspaces/{wid}", headers=WRITE).status_code == 404


def test_foreign_workspace_is_not_found(client, cloud):
    sign_in(client, cloud, github_id=1, login="alice")
    wid, _ = new_workspace(client, cloud)
    other = app_client(cloud)
    sign_in(other, cloud, github_id=2, login="bob")
    assert other.get(f"/api/w/{wid}/state").status_code == 404
    assert other.get(f"/api/w/{wid}/state").json() == {"error": "No such workspace."}
    assert other.get(f"/api/w/{wid}/mode").status_code == 404
    assert other.post(f"/api/w/{wid}/agents/a/pause", headers=WRITE).status_code == 404
    assert other.post(f"/api/workspaces/{wid}/key", headers=WRITE).status_code == 404
    assert other.delete(f"/api/workspaces/{wid}", headers=WRITE).status_code == 404
    assert other.get("/api/me").json()["workspaces"] == []
    # Still there for its owner.
    assert client.get(f"/api/w/{wid}/state").status_code == 200
    assert other.get("/api/w/not-an-id/state").status_code == 404


# Workspace Tower


def test_workspace_tower_needs_a_session(client, cloud):
    sign_in(client, cloud)
    wid, _ = new_workspace(client, cloud)
    anon = app_client(cloud)
    for path in ("state", "radar", "events", "insights", "mode"):
        assert anon.get(f"/api/w/{wid}/{path}").status_code == 401


def test_workspace_tower_controls_need_the_header(client, cloud):
    sign_in(client, cloud)
    wid, key = new_workspace(client, cloud)
    rpc = {"Authorization": f"Bearer {key}"}
    client.post("/api/rpc", json={"method": "ensure_task", "args": ["agent-a", "task-a"]}, headers=rpc)
    assert client.post(f"/api/w/{wid}/agents/agent-a/pause").status_code == 403
    assert client.post(f"/api/w/{wid}/agents/agent-a/message", json={"text": "hi"}).status_code == 403
    assert client.post(f"/api/w/{wid}/agents/agent-a/pause", headers=WRITE).json() == {"ok": True}
    agents = client.get(f"/api/w/{wid}/state").json()["agents"]
    assert [a["paused"] for a in agents if a["id"] == "agent-a"] == [True]


def test_workspace_state_reflects_rpc_tasks_and_demo_is_unchanged(client, cloud):
    sign_in(client, cloud)
    wid, key = new_workspace(client, cloud)
    assert client.get(f"/api/w/{wid}/mode").json() == {"mode": "live"}
    assert client.get(f"/api/w/{wid}/state").json()["agents"] == []
    r = client.post(
        "/api/rpc", json={"method": "ensure_task", "args": ["agent-a", "task-a"], "kwargs": {"intent": "fix slugs"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.json() == {"ok": True, "result": None}
    agents = client.get(f"/api/w/{wid}/state").json()["agents"]
    assert [a["id"] for a in agents] == ["agent-a"]
    assert client.get("/api/me").json()["workspaces"][0]["agents_flying"] == 1
    events = client.get(f"/api/w/{wid}/events").json()["events"]
    assert isinstance(events, list)
    # The demo routes still answer from the single demo engine, without a session.
    anon = app_client(cloud)
    assert anon.get("/api/state").json() == DEMO_STATE
