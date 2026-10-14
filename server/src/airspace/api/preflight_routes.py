"""Pre-flight over HTTP: on the bundled demo repos, and on each hosted workspace's own graph.

    GET  /api/preflight/repos                  the demo repos whose graphs are ready
    GET  /api/preflight/symbols?repo=flask&q=  find_symbols on a demo repo, for search as you type
    POST /api/preflight                        {"repo": "flask", "tasks": [...], "depth": 2}: the preflight answer

A demo repo is indexed once, when the server starts, into its own graph (demo_flask from AIRSPACE_FLASK_REPO,
demo_blog from the bundled fixture). That runs in a background thread so startup never waits on it; until a graph is
ready its routes answer 503. These are public endpoints, so each client address has a rate limit. The workspace
routes (workspace_routes) are the same calls on the workspace graph, for its owner.
"""

import logging
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from airspace.api.app import ApiError
from airspace.api.playground import FIXTURE_REPO, Buckets

log = logging.getLogger("airspace.api")

PER_MINUTE = 30
# Search as you type sends a request every few keystrokes, so it gets a larger budget than the check itself.
SYMBOLS_PER_MINUTE = 120
FLASK_ENV = "AIRSPACE_FLASK_REPO"
PLAYGROUND_ENV = "AIRSPACE_PLAYGROUND_REPO"
_DOWN = (ConnectionError, TimeoutError, RedisConnectionError, RedisTimeoutError)


@dataclass(frozen=True)
class DemoRepo:
    id: str  # "flask", as the API names it
    name: str  # "Flask", as people read it
    graph: str  # "demo_flask"
    path: Path


class PreflightBody(BaseModel):
    repo: str = "flask"
    tasks: Any = None
    depth: Any = 2


class WorkspacePreflightBody(BaseModel):
    tasks: Any = None
    depth: Any = 2


class Demos:
    """The demo repos and their graphs: each indexed once by build(), which start() runs in a background thread.

    `connect` opens FalkorDB. When it is not up yet (the server and FalkorDB start together), build() tries again
    every `retry_seconds`, up to `attempts` times.
    """

    def __init__(self, repos: list[DemoRepo], connect: Callable[[], Any] | None = None, attempts: int = 12,
                 retry_seconds: float = 5.0, sleep: Callable[[float], None] = time.sleep):
        from airspace.api.playground import _default_connect

        self.repos = {r.id: r for r in repos}
        self.connect = connect or _default_connect
        self.attempts = attempts
        self.retry_seconds = retry_seconds
        self.sleep = sleep
        self._lock = threading.Lock()
        self._status = {r.id: "building" for r in repos}
        self._symbols: dict[str, int] = {}
        self._db: Any = None

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Demos":
        """Flask from AIRSPACE_FLASK_REPO, the blog from AIRSPACE_PLAYGROUND_REPO or the bundled fixture. A path
        that does not exist is left out without a word: most servers have no Flask checkout."""
        env = os.environ if env is None else env
        repos = []
        flask = (env.get(FLASK_ENV) or "").strip()
        if flask and Path(flask).is_dir():
            repos.append(DemoRepo("flask", "Flask", "demo_flask", Path(flask)))
        blog = Path((env.get(PLAYGROUND_ENV) or "").strip() or FIXTURE_REPO)
        if blog.is_dir():
            repos.append(DemoRepo("blog", "Sample blog", "demo_blog", blog))
        return cls(repos)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.build, name="airspace-demo-index", daemon=True)
        thread.start()
        return thread

    def _open(self) -> Any:
        for attempt in range(1, self.attempts + 1):
            try:
                return self.connect()
            except Exception as e:
                if attempt == self.attempts:
                    log.warning("airspace: demo repos not indexed, FalkorDB unavailable (%s)", e)
                    return None
                self.sleep(self.retry_seconds)
        return None

    def build(self) -> None:
        """Index every demo repo, the smallest first, so the blog is ready while Flask is still being read."""
        if not self.repos:
            return
        db = self._open()
        if db is None:
            with self._lock:
                self._status = {k: "failed" for k in self._status}
            return
        self._db = db
        from airspace.indexer.writer import index_repo

        for repo in sorted(self.repos.values(), key=lambda r: r.id != "blog"):
            try:
                graph = db.select_graph(repo.graph)
                # A fresh graph each start: the checkout or the indexer may have changed since the last one.
                if repo.graph in db.list_graphs():
                    graph.delete()
                    graph = db.select_graph(repo.graph)
                started = time.monotonic()
                index_repo(graph, repo.path)
                count = graph.query("MATCH (s:Symbol) RETURN count(s)").result_set[0][0]
                log.info("airspace: demo %s indexed, %d symbols in %.1fs", repo.id, count, time.monotonic() - started)
                with self._lock:
                    self._symbols[repo.id] = int(count)
                    self._status[repo.id] = "ready"
            except Exception as e:
                log.warning("airspace: demo %s not indexed (%s: %s)", repo.id, type(e).__name__, e)
                with self._lock:
                    self._status[repo.id] = "failed"

    def ready(self) -> list[dict]:
        with self._lock:
            return [{"id": r.id, "name": r.name, "symbols": self._symbols[r.id]}
                    for r in self.repos.values() if self._status[r.id] == "ready"]

    def graph(self, repo_id: str) -> Any:
        """The demo repo's graph, or ApiError 404 (unknown repo) or 503 (not built, or could not be)."""
        repo = self.repos.get(repo_id) if isinstance(repo_id, str) else None
        if repo is None:
            raise ApiError(404, "No such demo repo.")
        with self._lock:
            status = self._status[repo.id]
        if status == "building":
            raise ApiError(503, f"The {repo.name} graph is still being built. Try again in a few seconds.")
        if status == "failed":
            raise ApiError(503, f"The {repo.name} graph could not be built on this server.")
        return self._db.select_graph(repo.graph)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limited(buckets: Buckets, key: str) -> JSONResponse | None:
    wait = buckets.take(key)
    if wait <= 0:
        return None
    return JSONResponse(status_code=429, content={"error": "Too many requests from this address. Try again in a minute."},
                        headers={"Retry-After": str(max(1, math.ceil(wait)))})


def _answer(graph: Any, tasks: Any, depth: Any):
    """The preflight answer, 422 {"error", "suggestions"} for input it cannot plan, 503 when FalkorDB went away."""
    from airspace.admission.preflight import PreflightError, preflight

    try:
        return preflight(graph, tasks, depth)
    except PreflightError as e:
        return JSONResponse(status_code=422, content={"error": e.message, "suggestions": e.suggestions})
    except _DOWN as e:
        log.warning("airspace: pre-flight lost FalkorDB (%s)", type(e).__name__)
        return JSONResponse(status_code=503, content={"error": "FalkorDB is unavailable. Try again."})


def _symbols(graph: Any, q: str):
    from airspace.admission.preflight import find_symbols

    try:
        return {"symbols": find_symbols(graph, q)}
    except _DOWN:
        return JSONResponse(status_code=503, content={"error": "FalkorDB is unavailable. Try again."})


def router(demos: Demos, per_minute: int = PER_MINUTE, symbols_per_minute: int = SYMBOLS_PER_MINUTE) -> APIRouter:
    r = APIRouter()
    checks = Buckets(per_minute)
    searches = Buckets(symbols_per_minute)

    @r.get("/api/preflight/repos")
    def repos() -> dict:
        return {"repos": demos.ready()}

    @r.get("/api/preflight/symbols")
    def symbols(request: Request, repo: str = "flask", q: str = ""):
        limited = _limited(searches, _client(request))
        if limited is not None:
            return limited
        return _symbols(demos.graph(repo), q)

    @r.post("/api/preflight")
    def check(request: Request, body: PreflightBody):
        limited = _limited(checks, _client(request))
        if limited is not None:
            return limited
        return _answer(demos.graph(body.repo), body.tasks, body.depth)

    return r


def workspace_routes(r: APIRouter, cloud: Any, per_minute: int = PER_MINUTE) -> None:
    """Add /preflight and /preflight/symbols to the workspace router (mounted at /api/w/{workspace_id}).

    Owner only, like the rest of the workspace's Tower; the POST also needs X-Airspace: 1 (require_user checks it).
    The limit is per workspace, so one owner's script cannot crowd out the server.
    """
    from airspace.cloud.workspaces import owned_workspace

    checks = Buckets(per_minute)

    @r.get("/preflight/symbols")
    def symbols(request: Request, workspace_id: str, q: str = ""):
        owned_workspace(cloud, request, workspace_id)
        return _symbols(cloud.engine(workspace_id).graph, q)

    @r.post("/preflight")
    def check(request: Request, workspace_id: str, body: WorkspacePreflightBody):
        owned_workspace(cloud, request, workspace_id)
        limited = _limited(checks, workspace_id)
        if limited is not None:
            return limited
        return _answer(cloud.engine(workspace_id).graph, body.tasks, body.depth)
