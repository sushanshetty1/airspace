"""POST /api/rpc: the engine and graph calls remote hooks make, against the workspace their key opens.

    request  {"method": "check_edit", "args": [...], "kwargs": {...}}   values in wire form (airspace.wire)
    answer   200 {"ok": true, "result": <wire>}   or 4xx {"ok": false, "error": "<text>"}

Only the methods in ENGINE_METHODS and GRAPH_METHODS can be called. Everything else on the engine (Tower controls,
seen_source, private helpers) stays out of reach of a key: a key lets hooks fly agents, not run Tower. Parsing
happens on the developer's machine, so graph writes arrive as ModuleFacts and whole files never travel.
"""

import asyncio
import dataclasses
import inspect
import json
import logging
import math

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from airspace import wire
from airspace.api.app import EngineUnavailable
from airspace.api.playground import Buckets
from airspace.types import ModuleFacts

log = logging.getLogger("airspace.cloud")

ENGINE_METHODS = frozenset({
    "ensure_task", "agent_of", "check_edit", "record_changes", "renamed", "claim_pending", "claim", "file_plan",
    "release", "pending_briefings", "record_edited_file", "edited_files", "note_touched", "started_at", "stop_check",
    "holding", "land", "block_landing", "last_block", "note_reading", "note_interest_from_text", "pending_messages",
    "state", "explain", "insights",
})
GRAPH_METHODS = frozenset({"graph.known", "graph.write_file", "graph.index"})
WORKSPACE_HEADER = "X-Airspace-Workspace"
# FalkorDB went away mid-call (the client is redis-py underneath): the caller should retry, not report a bug.
_DOWN = (ConnectionError, TimeoutError, RedisConnectionError, RedisTimeoutError)


class RpcError(Exception):
    """A call the server refuses. The text goes back to the client as the error."""

    def __init__(self, text: str, status: int = 400):
        super().__init__(text)
        self.status = status
        self.text = text


def _bind(fn, method: str, args: list, kwargs: dict) -> None:
    try:
        inspect.signature(fn).bind(*args, **kwargs)
    except TypeError as e:
        raise RpcError(f"Bad arguments for {method}: {e}.") from None


def _graph_call(graph, method: str, args: list, kwargs: dict):
    from airspace.admission.engine import removed_qualnames
    from airspace.indexer.writer import index_facts, known_qualnames, reindex_facts

    if method == "graph.known":
        _bind(lambda: None, method, args, kwargs)
        return sorted(known_qualnames(graph) | removed_qualnames(graph))

    if method == "graph.write_file":
        def write_file(rel, facts):
            return rel, facts

        _bind(write_file, method, args, kwargs)
        rel, facts = write_file(*args, **kwargs)
        if not isinstance(rel, str) or not rel:
            raise RpcError("graph.write_file needs a file path.")
        if facts is not None and not isinstance(facts, ModuleFacts):
            raise RpcError("graph.write_file needs ModuleFacts or null.")
        if facts is not None and facts.file != rel:
            raise RpcError(f"The facts are for {facts.file}, not {rel}.")
        return reindex_facts(graph, rel, facts)

    def index(facts_list, reset=False):
        return facts_list, reset

    _bind(index, method, args, kwargs)
    facts_list, reset = index(*args, **kwargs)
    if not isinstance(facts_list, list) or not all(isinstance(f, ModuleFacts) for f in facts_list):
        raise RpcError("graph.index needs a list of ModuleFacts.")
    if not isinstance(reset, bool):
        raise RpcError("graph.index needs reset to be true or false.")
    return dataclasses.asdict(index_facts(graph, facts_list, reset=reset))


def dispatch(airspace, graph, method: str, args: list, kwargs: dict):
    """Run one allowed call with wire-form arguments and return its result in wire form. Raises RpcError."""
    if not isinstance(method, str) or (method not in ENGINE_METHODS and method not in GRAPH_METHODS):
        raise RpcError(f"Unknown method {method}.")
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise RpcError("args must be a list and kwargs an object.")
    try:
        args, kwargs = wire.decode(args), wire.decode(kwargs)
    except (ValueError, TypeError) as e:
        raise RpcError(f"The arguments do not decode: {e}.") from None
    if not isinstance(kwargs, dict):
        raise RpcError("kwargs must be a plain object.")
    if method in GRAPH_METHODS:
        result = _graph_call(graph, method, args, kwargs)
    else:
        fn = getattr(airspace, method)
        _bind(fn, method, args, kwargs)
        try:
            result = fn(*args, **kwargs)
        except (ValueError, KeyError) as e:
            raise RpcError(f"{method} refused: {type(e).__name__}: {e}") from None
    return wire.encode(result)


async def _read_body(request: Request, limit: int) -> bytes | None:
    """The body, or None once it passes `limit` bytes. Read in chunks so a huge body is never held whole."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def router(cloud) -> APIRouter:
    r = APIRouter()
    buckets = Buckets(cloud.rpc_per_minute)
    too_large = f"The body is larger than {cloud.rpc_max_bytes // (1024 * 1024)} MB."

    def fail(status: int, text: str, headers: dict | None = None) -> JSONResponse:
        return JSONResponse(status_code=status, content={"ok": False, "error": text}, headers=headers)

    @r.post("/api/rpc")
    async def rpc(request: Request):
        auth = request.headers.get("authorization", "")
        scheme, _, key = auth.partition(" ")
        if scheme.lower() != "bearer" or not key.strip():
            return fail(401, "Send the workspace key as Authorization: Bearer ask_...")
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > cloud.rpc_max_bytes:
            return fail(413, too_large)
        try:
            workspace = await asyncio.to_thread(lambda: cloud.accounts().workspace_for_key(key.strip()))
        except EngineUnavailable as e:
            return fail(503, str(e))
        except _DOWN as e:
            log.warning("airspace: rpc key lookup lost FalkorDB (%s)", type(e).__name__)
            return fail(503, "FalkorDB is unavailable. Try again.")
        if workspace is None:
            return fail(401, "The key is not valid. It may have been rotated or its workspace deleted.")
        wid = workspace["id"]
        headers = {WORKSPACE_HEADER: wid}
        wait = buckets.take(wid)
        if wait > 0:
            return fail(429, "Too many calls for this key. Try again in a minute.",
                        {**headers, "Retry-After": str(max(1, math.ceil(wait)))})
        raw = await _read_body(request, cloud.rpc_max_bytes)
        if raw is None:
            return fail(413, too_large, headers)
        try:
            body = json.loads(raw)
        except ValueError:
            return fail(400, "The body is not valid JSON.", headers)
        if not isinstance(body, dict):
            return fail(400, "The body must be an object with a method.", headers)
        method = body.get("method")

        def call():
            airspace = cloud.engine(wid)
            return dispatch(airspace, airspace.graph, method, body.get("args", []), body.get("kwargs", {}))

        try:
            result = await asyncio.to_thread(call)
        except RpcError as e:
            return fail(e.status, e.text, headers)
        except EngineUnavailable as e:
            return fail(503, str(e), headers)
        except _DOWN as e:
            log.warning("airspace: rpc %s for %s lost FalkorDB (%s)", method, wid, type(e).__name__)
            return fail(503, "FalkorDB is unavailable. Try again.", headers)
        except Exception:
            log.exception("airspace: rpc %s for %s failed", method, wid)
            return fail(500, f"{method} failed on the server.", headers)
        return JSONResponse({"ok": True, "result": result}, headers=headers)

    return r
