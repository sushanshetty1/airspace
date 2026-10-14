"""The playground: one clearance check by the real engine, on the fixture repo, without agents.

POST /api/playground/check takes what agent-a changes and what agent-b writes:

    {"change": {"symbol": "utils.text.slugify", "new_signature": "slugify(value, *, unicode=False)"},
     "edit": {"caller": "blog.views.render_post", "call": "slugify(post.title, True)"}}

Each request indexes the bundled fixture repo into its own scratch graph (playground_<uuid>, deleted afterwards),
lets agent-a record the signature change, then runs agent-b's check_edit on the caller with the call as a new call.
It answers with the verdict, the reason, the path and the radar of the scratch graph. This is a public demo
endpoint, so it is rate limited per client and runs a few checks at a time.
"""

import ast
import inspect
import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from airspace.types import SignatureChange

log = logging.getLogger("airspace.api")

# server/tests/fixtures/blog, next to the package in a checkout. AIRSPACE_PLAYGROUND_REPO overrides it.
FIXTURE_REPO = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "blog"
AGENT_A, AGENT_B = "agent-a", "agent-b"
TASK_A, TASK_B = "agent-a:playground", "agent-b:playground"
MAX_TEXT = 200
SLUG_EXAMPLE = {"symbol": "utils.text.slugify", "caller": "blog.views.render_post"}
_CONCURRENT = 4
_CONNECT_TIMEOUT = 2.0
_SOCKET_TIMEOUT = 10.0


class Invalid(ValueError):
    """Input the playground cannot check. The message is shown to the visitor."""


# Request bodies. Fields default to "" so a missing one gets the same clear message as an empty one.


class Change(BaseModel):
    symbol: str = ""
    new_signature: str = ""


class Edit(BaseModel):
    caller: str = ""
    call: str = ""


class CheckBody(BaseModel):
    change: Change = Change()
    edit: Edit = Edit()


# Parsing


def _text(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        raise Invalid(f"The {what} is required.")
    if len(value) > MAX_TEXT:
        raise Invalid(f"The {what} is longer than {MAX_TEXT} characters.")
    if "\n" in value or "\r" in value:
        raise Invalid(f"The {what} must fit on one line.")
    return value


def parse_signature(sig: str) -> ast.FunctionDef:
    """`sig` as the function it declares. It must read as `def <sig>: pass` and nothing more."""
    sig = _text(sig, "new signature")
    try:
        tree = ast.parse(f"def {sig}: pass")
    except SyntaxError:
        raise Invalid(f"The new signature does not parse as def {sig}: pass") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise Invalid("The new signature must be one function signature, such as slugify(value, *, unicode=False).")
    fn = tree.body[0]
    if len(fn.body) != 1 or not isinstance(fn.body[0], ast.Pass) or fn.decorator_list:
        raise Invalid("The new signature must be one function signature, such as slugify(value, *, unicode=False).")
    return fn


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Call):
        base = _dotted(node.func)
        return f"{base}()" if base else None
    return None


def parse_call(call: str) -> tuple[str, int, tuple[str, ...], bool]:
    """(callee as written, positional arguments, keyword names, unpacks *args or **kwargs) for one call expression."""
    call = _text(call, "call")
    try:
        tree = ast.parse(call, mode="eval")
    except SyntaxError:
        raise Invalid(f"The call does not parse as Python: {call}") from None
    node = tree.body
    if not isinstance(node, ast.Call):
        raise Invalid("The call must be a single call expression, such as slugify(post.title, True).")
    callee = _dotted(node.func)
    if callee is None:
        raise Invalid("The call must call a name or a dotted name, such as slugify(...) or post.save().")
    star = any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords)
    nargs = sum(1 for a in node.args if not isinstance(a, ast.Starred))
    kwargs = tuple(k.arg for k in node.keywords if k.arg is not None)
    return callee, nargs, kwargs, star


def _params(sig: str) -> str | None:
    """The parameter list, normalised, or None when `sig` is not a def signature."""
    try:
        fn = ast.parse(f"def {sig}: pass").body[0]
    except (SyntaxError, IndexError):
        return None
    return ast.unparse(fn.args) if isinstance(fn, ast.FunctionDef) else None


def _resolve(callee: str, symbols: dict[str, dict], prefer: str) -> tuple[str, bool]:
    """(qualname, bound) for the callee as written: matched against known qualnames by its last segment."""
    written = callee.replace("()", "")
    name = written.rsplit(".", 1)[-1]
    candidates = sorted(q for q in symbols if q.rsplit(".", 1)[-1] == name)
    if not candidates:
        raise Invalid(f"{name} is not a function, method or class in the fixture repo.")
    by_suffix = [q for q in candidates if ("." + q).endswith("." + written)]
    preferred = [q for q in candidates if q == prefer or f"{q}.__init__" == prefer]
    if len(by_suffix) == 1:
        target = by_suffix[0]
    elif preferred:
        target = preferred[0]
    elif len(candidates) == 1:
        target = candidates[0]
    else:
        raise Invalid(f"{name} matches several symbols ({', '.join(candidates)}). Write it with its class or module.")
    receiver = callee.rsplit(".", 1)[0] if "." in callee else None
    owner = target.rsplit(".", 2)[-2] if target.count(".") >= 2 else None
    # post.save() fills self; Post.save(post) does not.
    bound = symbols[target]["kind"] == "method" and receiver is not None and receiver.rsplit(".", 1)[-1] != owner
    return target, bound


def _call_site(caller: str, nargs: int, kwargs: tuple[str, ...], star: bool, bound: bool):
    from airspace import types

    cls = types.CallSite  # present once the engine checks call shapes
    values = {"caller": caller, "nargs": nargs, "kwargs": kwargs, "star": star, "bound": bound}
    return cls(**{f.name: values[f.name] for f in fields(cls) if f.name in values})


def checks_call_shapes(airspace: Any) -> bool:
    return "call_shapes" in inspect.signature(airspace.check_edit).parameters


# The rate limit: a token bucket per client address.


class Buckets:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic, max_clients: int = 10000):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self.max_clients = max_clients
        self.lock = threading.Lock()
        self.buckets: dict[str, tuple[float, float]] = {}

    def take(self, client: str) -> float:
        """0 when the request may go ahead, else the seconds until it may."""
        now = self.clock()
        with self.lock:
            tokens, last = self.buckets.get(client, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.buckets[client] = (tokens, now)
                return (1 - tokens) / self.rate
            self.buckets[client] = (tokens - 1, now)
            if len(self.buckets) > self.max_clients:
                full = [k for k, (t, at) in self.buckets.items() if t + (now - at) * self.rate >= self.capacity]
                for k in full:
                    del self.buckets[k]
            return 0.0


# The check


def _default_connect():
    from falkordb import FalkorDB

    from airspace.config import settings

    s = settings()
    db = FalkorDB(host=s.falkordb_host, port=s.falkordb_port, socket_connect_timeout=_CONNECT_TIMEOUT,
                  socket_timeout=_SOCKET_TIMEOUT)
    db.connection.ping()
    return db


def run_check(db, repo: Path, body: CheckBody) -> dict:
    """Validates, indexes `repo` into a scratch graph, runs the engine and deletes the graph. Raises Invalid."""
    from airspace.admission.engine import Airspace
    from airspace.config import settings
    from airspace.indexer.writer import index_repo

    symbol = _text(body.change.symbol, "symbol")
    fn = parse_signature(body.change.new_signature)
    new_sig = body.change.new_signature.strip()
    caller = _text(body.edit.caller, "caller")
    callee_text, nargs, kwargs, star = parse_call(body.edit.call)

    graph = db.select_graph(f"playground_{uuid.uuid4().hex}")
    try:
        index_repo(graph, repo)
        symbols = {
            q: {"kind": kind, "signature": sig}
            for q, kind, sig in graph.query("MATCH (s:Symbol) RETURN s.qualname, s.kind, s.signature").result_set
        }
        for q, what in ((symbol, "symbol"), (caller, "caller")):
            if q not in symbols:
                raise Invalid(f"The {what} {q} is not in the fixture repo. Use a qualname such as {SLUG_EXAMPLE[what]}.")
        old_sig = symbols[symbol]["signature"] or ""
        renamed = fn.name != symbol.rsplit(".", 1)[-1]
        if not renamed and _params(old_sig) == _params(new_sig):
            raise Invalid(f"The new signature is the same as the current one, {old_sig}.")
        callee, bound = _resolve(callee_text, symbols, symbol)

        s = settings()
        air = Airspace(graph, lease_seconds=s.lease_seconds, cone_depth=s.cone_depth)
        shapes = checks_call_shapes(air)
        # The call sites, as the hooks see them: a call to a class is also a call to its __init__, with self filled.
        sites = [(callee, bound)]
        if symbols[callee]["kind"] == "class" and f"{callee}.__init__" in symbols:
            sites.append((f"{callee}.__init__", True))
        new_calls = [(caller, q) for q, _ in sites]

        air.file_plan(AGENT_A, TASK_A, f"change {symbol}", [symbol])
        air.file_plan(AGENT_B, TASK_B, f"edit {caller}", [caller])
        air.check_edit(TASK_A, [symbol], [])
        # A rename removes the old name; the engine reads an empty new signature as "renamed or removed".
        recorded = "" if renamed and shapes else new_sig
        air.record_changes(TASK_A, [SignatureChange(symbol, old_sig, recorded)])
        if shapes:
            call_shapes = {q: [_call_site(caller, nargs, kwargs, star, b)] for q, b in sites}
            verdict = air.check_edit(TASK_B, [caller], new_calls, call_shapes=call_shapes)
        else:
            verdict = air.check_edit(TASK_B, [caller], new_calls)

        hits_change = symbol in (q for q, _ in sites)
        target = symbol if hits_change else callee
        if verdict.kind == "hold":
            reason = verdict.reason
        elif hits_change:
            reason = f"Airspace cleared: the call {caller} makes to {symbol} fits the new signature {new_sig}."
        else:
            reason = f"Airspace cleared: {caller} calls {callee}, which {AGENT_A} is not changing."
        return {
            "verdict": verdict.kind,
            "reason": reason,
            "path": verdict.path or [caller, target],
            "callee": callee,
            "old_signature": old_sig,
            "checks_arguments": shapes,
            "radar": air.radar(),
        }
    finally:
        try:
            graph.delete()
        except Exception as e:
            log.warning("airspace: scratch graph %s not deleted (%s)", graph.name, e)


def router(connect: Callable[[], Any] | None = None, per_minute: int = 20, repo: Path | None = None) -> APIRouter:
    r = APIRouter()
    connect = connect or _default_connect
    buckets = Buckets(per_minute)
    slots = threading.BoundedSemaphore(_CONCURRENT)

    def error(status: int, text: str, headers: dict | None = None) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": text}, headers=headers)

    @r.post("/api/playground/check")
    def check(body: CheckBody, request: Request):
        client = request.client.host if request.client else "unknown"
        wait = buckets.take(client)
        if wait > 0:
            return error(429, "Too many checks from this address. Try again in a minute.",
                         {"Retry-After": str(max(1, math.ceil(wait)))})
        try:
            # Everything that needs no database is checked first, so bad input never costs a graph.
            parse_signature(body.change.new_signature)
            parse_call(body.edit.call)
            _text(body.change.symbol, "symbol")
            _text(body.edit.caller, "caller")
        except Invalid as e:
            return error(422, str(e))
        fixture = repo or Path(os.environ.get("AIRSPACE_PLAYGROUND_REPO") or FIXTURE_REPO)
        if not fixture.is_dir():
            log.warning("airspace: playground repo %s not found", fixture)
            return error(503, "The playground repo is not installed on this server.")
        if not slots.acquire(timeout=10):
            return error(503, "The playground is busy. Try again in a few seconds.")
        try:
            try:
                db = connect()
            except Exception as e:
                detail = " ".join(str(e).split()) or type(e).__name__
                return error(503, f"FalkorDB unavailable ({detail})")
            try:
                return run_check(db, fixture, body)
            except Invalid as e:
                return error(422, str(e))
        finally:
            slots.release()

    return r
