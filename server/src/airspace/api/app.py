"""The Airspace HTTP API for Tower: read models, controls and a server-sent-events stream.

Every route is a thin call into the admission engine. Engine calls block on FalkorDB, so plain routes are sync
(FastAPI runs them in a thread pool) and the stream polls through a worker thread.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, StringConstraints

log = logging.getLogger("airspace.api")

TOWER_ORIGINS = ["http://localhost:4173", "http://127.0.0.1:4173"]

# Same budget as the hooks: a stalled socket must not stall a request.
_CONNECT_TIMEOUT = 2.0
_SOCKET_TIMEOUT = 10.0


class MessageBody(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class EngineUnavailable(Exception):
    pass


class ApiError(Exception):
    """A refusal with a status and a short sentence for the client, answered as {"error": text}."""

    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status = status
        self.text = text


def open_airspace(root: Path):
    """The real engine for a repository, on a FalkorDB client with short timeouts. Raises if FalkorDB is down."""
    from falkordb import FalkorDB

    from airspace.admission.engine import Airspace
    from airspace.config import settings
    from airspace.graph.db import ensure_schema, repo_graph

    s = settings()
    db = FalkorDB(
        host=s.falkordb_host,
        port=s.falkordb_port,
        socket_connect_timeout=_CONNECT_TIMEOUT,
        socket_timeout=_SOCKET_TIMEOUT,
    )
    db.connection.ping()
    graph = repo_graph(db, root)
    ensure_schema(graph)
    return Airspace(graph, lease_seconds=s.lease_seconds, cone_depth=s.cone_depth)


def _sse(event: dict) -> str:
    return f"event: airspace\ndata: {json.dumps(event)}\n\n"


def tower_routes(
    engine: Callable[[Request], Any],
    *,
    poll_interval: float = 0.5,
    ping_interval: float = 15.0,
    max_seconds: float | None = None,
) -> APIRouter:
    """Tower's read models, controls and event stream, with paths relative to where the router is mounted.

    `engine(request)` returns the Airspace the request is about, or raises ApiError or EngineUnavailable. The demo
    mounts this at /api with its one engine; each hosted workspace is served at /api/w/{workspace_id} with its own.
    """
    r = APIRouter()

    def act(name: str, call: Callable[[], Any], reply: Callable[[Any], dict]) -> dict:
        """Run a control. The engine treats unknown or finished agents as a no-op; a refusal it raises is reported."""
        try:
            result = call()
        except (ValueError, KeyError) as e:
            log.warning("airspace: %s refused (%s: %s)", name, type(e).__name__, e)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return reply(result)

    @r.get("/state")
    def state(request: Request) -> dict:
        return engine(request).state()

    @r.get("/radar")
    def radar(request: Request) -> dict:
        return engine(request).radar()

    @r.get("/events")
    def events(request: Request, since: float = 0.0) -> dict:
        return {"events": engine(request).events(since)}

    @r.get("/collisions/{collision_id}")
    def collision(request: Request, collision_id: str):
        found = engine(request).collision(collision_id)
        if found is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return found

    @r.get("/insights")
    def insights(request: Request) -> dict:
        return engine(request).insights()

    @r.post("/agents/{agent}/pause")
    def pause(request: Request, agent: str) -> dict:
        air = engine(request)
        return act("pause", lambda: air.pause(agent), lambda _: {"ok": True})

    @r.post("/agents/{agent}/resume")
    def resume(request: Request, agent: str) -> dict:
        air = engine(request)
        return act("resume", lambda: air.resume(agent), lambda _: {"ok": True})

    @r.post("/agents/{agent}/message")
    def message(request: Request, agent: str, body: MessageBody) -> dict:
        air = engine(request)
        return act("message", lambda: air.message(agent, body.text, sender="Tower"), lambda mid: {"ok": True, "id": mid})

    @r.post("/collisions/{collision_id}/release")
    def release(request: Request, collision_id: str) -> dict:
        air = engine(request)
        return act("release", lambda: air.release_collision(collision_id), lambda done: {"ok": bool(done)})

    @r.get("/events/stream")
    async def stream(request: Request, since: float = 0.0) -> StreamingResponse:
        airspace = await asyncio.to_thread(engine, request)
        return StreamingResponse(
            _event_stream(request, airspace, since),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _event_stream(request: Request, airspace: Any, since: float) -> AsyncIterator[str]:
        started = last_ping = time.monotonic()
        # Ids already sent at the current `since`, so equal timestamps never repeat an event.
        sent_at_since: set[str] = set()
        while True:
            if await request.is_disconnected():
                return
            for e in await asyncio.to_thread(airspace.events, since):
                at, eid = e.get("at", since), e.get("id")
                if at < since or (at == since and eid in sent_at_since):
                    continue
                if at > since:
                    since, sent_at_since = at, set()
                sent_at_since.add(eid)
                yield _sse(e)
            now = time.monotonic()
            if max_seconds is not None and now - started >= max_seconds:
                return
            if now - last_ping >= ping_interval:
                last_ping = now
                yield ": ping\n\n"
            await asyncio.sleep(poll_interval)

    return r


def create_app(
    airspace_factory: Callable[[], Any],
    *,
    poll_interval: float = 0.5,
    ping_interval: float = 15.0,
    max_seconds: float | None = None,
    cloud: Any = None,
    demos: Any = None,
) -> FastAPI:
    """The API over an engine built by airspace_factory on first use (and again after a failed attempt).

    max_seconds ends each event stream after that long; None streams until the client disconnects.
    cloud, an airspace.cloud.Cloud, adds sign-in, workspaces and the RPC endpoint remote hooks call.
    demos, an airspace.api.preflight_routes.Demos, holds the repos pre-flight runs on; None serves none, so an app
    built here never indexes anything by itself (default_app starts the real ones).
    """
    app = FastAPI(title="Airspace", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=TOWER_ORIGINS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    lock = threading.Lock()
    built: list[Any] = []

    def engine() -> Any:
        with lock:
            if not built:
                try:
                    built.append(airspace_factory())
                except Exception as e:
                    detail = " ".join(str(e).split()) or type(e).__name__
                    raise EngineUnavailable(f"FalkorDB unavailable ({detail})") from e
            return built[0]

    @app.exception_handler(EngineUnavailable)
    async def _unavailable(request: Request, exc: EngineUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": str(exc)})

    @app.exception_handler(ApiError)
    async def _refused(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.text})

    timing = {"poll_interval": poll_interval, "ping_interval": ping_interval, "max_seconds": max_seconds}
    app.include_router(tower_routes(lambda request: engine(), **timing), prefix="/api")

    from airspace.api import playground, preflight_routes, replay_routes
    app.include_router(replay_routes.router(engine))
    app.include_router(playground.router())
    app.include_router(preflight_routes.router(demos if demos is not None else preflight_routes.Demos([])))
    if cloud is not None:
        cloud.mount(app, **timing)
    return app


def default_app(root: Path) -> FastAPI:
    """The API for one repository on the configured FalkorDB, plus hosted accounts, workspaces and the pre-flight
    demo repos, which start indexing in the background now."""
    from airspace.api.preflight_routes import Demos
    from airspace.cloud import Cloud

    demos = Demos.from_env()
    app = create_app(lambda: open_airspace(root), cloud=Cloud.from_env(), demos=demos)
    demos.start()
    return app
