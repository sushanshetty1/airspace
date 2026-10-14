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

from fastapi import FastAPI, Request
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


def create_app(
    airspace_factory: Callable[[], Any],
    *,
    poll_interval: float = 0.5,
    ping_interval: float = 15.0,
    max_seconds: float | None = None,
) -> FastAPI:
    """The API over an engine built by airspace_factory on first use (and again after a failed attempt).

    max_seconds ends each event stream after that long; None streams until the client disconnects.
    """
    app = FastAPI(title="Airspace", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=TOWER_ORIGINS,
        allow_methods=["GET", "POST"],
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

    def act(name: str, call: Callable[[], Any], reply: Callable[[Any], dict]) -> dict:
        """Run a control. The engine treats unknown or finished agents as a no-op; a refusal it raises is reported."""
        try:
            result = call()
        except (ValueError, KeyError) as e:
            log.warning("airspace: %s refused (%s: %s)", name, type(e).__name__, e)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return reply(result)

    @app.get("/api/state")
    def state() -> dict:
        return engine().state()

    @app.get("/api/radar")
    def radar() -> dict:
        return engine().radar()

    @app.get("/api/events")
    def events(since: float = 0.0) -> dict:
        return {"events": engine().events(since)}

    @app.get("/api/collisions/{collision_id}")
    def collision(collision_id: str):
        found = engine().collision(collision_id)
        if found is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return found

    @app.get("/api/insights")
    def insights() -> dict:
        return engine().insights()

    @app.post("/api/agents/{agent}/pause")
    def pause(agent: str) -> dict:
        return act("pause", lambda: engine().pause(agent), lambda _: {"ok": True})

    @app.post("/api/agents/{agent}/resume")
    def resume(agent: str) -> dict:
        return act("resume", lambda: engine().resume(agent), lambda _: {"ok": True})

    @app.post("/api/agents/{agent}/message")
    def message(agent: str, body: MessageBody) -> dict:
        return act(
            "message", lambda: engine().message(agent, body.text, sender="Tower"), lambda mid: {"ok": True, "id": mid}
        )

    @app.post("/api/collisions/{collision_id}/release")
    def release(collision_id: str) -> dict:
        return act("release", lambda: engine().release_collision(collision_id), lambda done: {"ok": bool(done)})

    @app.get("/api/events/stream")
    async def stream(request: Request, since: float = 0.0) -> StreamingResponse:
        airspace = await asyncio.to_thread(engine)
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

    return app


def default_app(root: Path) -> FastAPI:
    """The API for one repository on the configured FalkorDB."""
    return create_app(lambda: open_airspace(root))
