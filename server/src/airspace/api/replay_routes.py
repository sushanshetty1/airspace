"""Replay routes: the recorded run Tower plays back, and whether Tower should play it or show live data.

AIRSPACE_REPLAY names the replay file (written by `python -m airspace.replay watch`). Tower asks /api/mode first:
a deployed Tower with no agents flying plays the recording, and switches to live data once an agent flies.
"""

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("airspace.api")

ENV = "AIRSPACE_REPLAY"


def router(engine: Callable[[], Any]) -> APIRouter:
    """`engine` returns the live Airspace, or raises when FalkorDB is down."""
    r = APIRouter()
    lock = threading.Lock()
    # (path, mtime, size) -> the file's bytes, so a large replay is read once, not on every visit.
    cache: dict[tuple[str, float, int], bytes] = {}

    def replay_path() -> Path | None:
        value = os.environ.get(ENV, "").strip()
        return Path(value) if value else None

    @r.get("/api/replay")
    def replay():
        path = replay_path()
        if path is None:
            return JSONResponse(status_code=404, content={"error": f"No replay is configured ({ENV} is not set)."})
        try:
            st = path.stat()
        except OSError:
            return JSONResponse(status_code=404, content={"error": f"The replay file {path.name} does not exist."})
        key = (str(path), st.st_mtime, st.st_size)
        with lock:
            body = cache.get(key)
            if body is None:
                try:
                    raw = path.read_bytes()
                    json.loads(raw)
                except (OSError, ValueError) as e:
                    log.warning("airspace: replay %s unreadable (%s)", path, e)
                    return JSONResponse(status_code=500, content={"error": f"The replay file {path.name} is not valid JSON."})
                cache.clear()
                cache[key] = body = raw
        return Response(content=body, media_type="application/json")

    @r.get("/api/mode")
    def mode() -> dict:
        if replay_path() is None:
            return {"mode": "live"}
        try:
            agents = engine().state().get("agents") or []
        except Exception as e:  # FalkorDB down: the recording is all there is to show
            log.warning("airspace: live state unavailable for /api/mode (%s)", type(e).__name__)
            return {"mode": "replay"}
        flying = any(a.get("status") == "active" for a in agents)
        return {"mode": "live" if flying else "replay"}

    return r
