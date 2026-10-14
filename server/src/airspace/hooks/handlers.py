"""Claude Code PreToolUse, PostToolUse and Stop hook logic: payload in, hook JSON out (or None to stay silent).

Every handler fails open. If FalkorDB (or, for a connected repository, the Airspace server) is unreachable or
anything else goes wrong, it writes one line to stderr and returns None, so Claude Code carries on as if Airspace
were not installed.
"""

import hashlib
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from airspace.admission.text import BRANCH_NOTE, LOCAL_NOTE, NOT_HERE_NOTE, briefing_line, landing_hold, memory_block
from airspace.remote import RemoteError
from airspace.types import Briefing, CallSite, EditAnalysis, SignatureChange

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
UNAVAILABLE = "airspace: FalkorDB unavailable, edit not checked"
ANY_UNAVAILABLE = "airspace: FalkorDB unavailable, briefings not delivered"
STOP_UNAVAILABLE = "airspace: FalkorDB unavailable, landing not checked"

# How many remembered items one delivery carries. A Read gets fewer: it is the most frequent tool call.
MEMORY_ITEMS = 8
MEMORY_ITEMS_READ = 5

# The holding pattern. Inside the 300 s timeout install-hooks gives the Stop hook.
STOP_WAIT_SECONDS = 240.0
STOP_POLL_SECONDS = 2.0

# Hooks run on every edit; a stalled socket must not stall the agent.
_CONNECT_TIMEOUT = 2.0
_SOCKET_TIMEOUT = 10.0


def _calls_in_file(repo_root: Path, rel: str, known: set[str]) -> list[tuple[str, str, CallSite]]:
    from airspace.hooks.edit_analysis import calls_in_file

    return calls_in_file(repo_root, rel, known)


@dataclass
class Deps:
    airspace: Callable[[Path], Any]  # repo_root -> Airspace-like object (may raise if FalkorDB is down)
    analyze: Callable[[Path, str, dict, set[str]], EditAnalysis | None]
    known: Callable[[Path], set[str]]  # repo_root -> known qualnames
    reindex: Callable[[Path, str], list[SignatureChange]]  # (repo_root, rel_path) -> changes
    # (repo_root, rel_path, known) -> (caller, callee, site) for every call in the file as it is now
    calls: Callable[[Path, str, set[str]], list[tuple[str, str, CallSite]]] = _calls_in_file


def identity(payload: dict, env: Mapping[str, str]) -> tuple[Path, str, str]:
    """(repo_root, agent_id, task_id) for a hook payload."""
    session = str(payload.get("session_id") or "")
    root = Path(env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    agent = env.get("AIRSPACE_AGENT") or f"agent-{session[:4]}"
    return root, agent, session


def _rel_path(repo_root: Path, file_path: str) -> str | None:
    """Repo-relative POSIX path, or None if the file is outside the repo."""
    p = Path(file_path)
    if not p.is_absolute():
        p = repo_root / p
    try:
        return p.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def _target(payload: dict, env: Mapping[str, str]) -> tuple[Path, str, str, str] | None:
    """(repo_root, agent_id, task_id, rel_path) when this payload is a Python edit inside the repo."""
    if payload.get("tool_name") not in EDIT_TOOLS:
        return None
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return None
    root, agent, task = identity(payload, env)
    rel = _rel_path(root, file_path)
    if rel is None:
        return None
    return root, agent, task, rel


def _note(line: str) -> None:
    print(line, file=sys.stderr)


def _unavailable(line: str, exc: Exception) -> None:
    """The one line for an engine that cannot be opened. A hosted server says why: down, or the key refused."""
    if isinstance(exc, RemoteError):
        detail = " ".join(str(exc).split())
        status = f"{exc.status} " if exc.status else ""
        line = line.replace("FalkorDB unavailable", f"Airspace server unavailable ({status}{detail})")
    _note(line)


def _failed(exc: Exception, what: str = "edit not checked") -> None:
    detail = " ".join(str(exc).split()) or type(exc).__name__
    _note(f"airspace: {type(exc).__name__} ({detail}), {what}")


def briefing_context(briefings: list[Briefing]) -> str:
    """Factual text describing contract changes made by other agents."""
    return "\n".join(f"Airspace briefing: {briefing_line(b)}" for b in briefings)


def message_context(messages: list[str]) -> str:
    """Messages sent from Tower, one per line."""
    return "\n".join(f"Message from Tower: {m}" for m in messages)


def _messages(airspace, agent: str, task: str) -> list[str]:
    # A failed lookup must not cost a hold its deny, so it is noted and skipped on its own.
    try:
        return list(airspace.pending_messages(agent, task))
    except Exception as e:
        detail = " ".join(str(e).split()) or type(e).__name__
        _note(f"airspace: {type(e).__name__} ({detail}), messages not delivered")
        return []


def _memory(airspace, task: str, names: list[str], limit: int = MEMORY_ITEMS) -> str:
    """The memory block for these symbols or files: what the graph remembers that this task has not heard yet.

    Like messages, a failure is noted and skipped: memory never costs a hold its deny or changes a verdict.
    """
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return ""
    try:
        return memory_block(list(airspace.memory_for_task(task, names, limit)))
    except Exception as e:
        detail = " ".join(str(e).split()) or type(e).__name__
        _note(f"airspace: {type(e).__name__} ({detail}), memory not delivered")
        return ""


def _on_disk(root: Path, qualname: str, new_sig: str) -> bool:
    """Whether this working copy already has a contract change: the new signature, or the symbol gone if removed."""
    from airspace.indexer.parse import parse_module

    parts = qualname.split(".")
    for i in range(len(parts) - 1, 0, -1):
        for rel in ("/".join(parts[:i]) + ".py", "/".join(parts[:i]) + "/__init__.py"):
            path = root / rel
            if not path.is_file():
                continue
            facts = parse_module(rel, path.read_text(encoding="utf-8", errors="replace"))
            if facts is None:
                return False
            signatures = {sym.qualname: sym.signature for sym in facts.symbols}
            return qualname not in signatures if not new_sig else signatures.get(qualname) == new_sig
    return False


def _localize(text: str, root: Path, changes: list[tuple[str, str]]) -> str:
    """Replace the generic working-copy note with the fact for this agent's own working copy."""
    if BRANCH_NOTE not in text or not changes:
        return text
    try:
        here = all(_on_disk(root, q, sig) for q, sig in changes)
    except Exception:
        return text
    return text.replace(BRANCH_NOTE, LOCAL_NOTE if here else NOT_HERE_NOTE)


def _rename_hint(text: str, airspace, symbols: list[str]) -> str:
    """When a removal was a rename, say what it was renamed to."""
    if "renamed or removed" not in text or not symbols:
        return text
    try:
        renames = airspace.renamed(sorted(set(symbols)))
    except Exception:
        return text
    hints = [f"{old} was renamed to {new} ({sig})." for old, (new, sig) in sorted(renames.items())]
    return text + ("\n" + " ".join(hints) if hints else "")


def _context(event: str, briefings: list[Briefing], messages: list[str], memory: str = "") -> dict | None:
    parts = [p for p in (briefing_context(briefings), message_context(messages), memory) if p]
    if not parts:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(parts)}}


def handle_pre(payload: dict, deps: Deps, env: Mapping[str, str] = os.environ) -> dict | None:
    target = _target(payload, env)
    if target is None:
        return None
    root, agent, task, _ = target
    try:
        airspace = deps.airspace(root)
        known = deps.known(root)
    except Exception as e:
        _unavailable(UNAVAILABLE, e)
        return None
    try:
        analysis = deps.analyze(root, payload["tool_name"], payload.get("tool_input") or {}, known)
        if analysis is None or not analysis.parse_ok:
            return None
        changes = analysis.signature_changes
        if not analysis.touched and not analysis.new_calls and not changes:
            return None
        # A removed symbol is gone from the new source, so it is not touched there, but removing it is an edit to it.
        removed = [c.qualname for c in changes if not c.new_signature and c.qualname not in analysis.touched]
        airspace.ensure_task(agent, task)
        verdict = airspace.check_edit(task, analysis.touched + removed, analysis.new_calls, analysis.call_shapes)
        if verdict.kind == "cleared" and changes:
            # Recorded before the file is written, so a concurrent agent sees the change at once.
            # The post hook reports it again and record_changes skips the repeat.
            airspace.record_changes(task, changes)
        # What the graph remembers about the code this edit touches and calls, after the briefings it was given.
        about = analysis.touched + removed + [callee for _, callee in analysis.new_calls]
        if verdict.kind == "hold":
            # A message sent while the agent is held reaches it in this deny reason, not only on a later clear.
            messages = message_context(_messages(airspace, agent, task))
            memory = _memory(airspace, task, about)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _rename_hint(
                        _localize(verdict.reason, root, [(b.symbol, b.new_signature) for b in verdict.briefings]),
                        airspace, [b.symbol for b in verdict.briefings] + verdict.path[-1:],
                    )
                    + ("\n" + messages if messages else "")
                    + ("\n" + memory if memory else ""),
                }
            }
        briefings = airspace.pending_briefings(task)
        messages = _messages(airspace, agent, task)
        return _context("PreToolUse", briefings, messages, _memory(airspace, task, about))
    except Exception as e:
        _failed(e)
        return None


def reindex_own(airspace, deps: Deps, root: Path, task: str, rel: str) -> list[SignatureChange]:
    """Re-index a file and return the signature changes that are this task's own.

    The graph is shared, and this working copy may predate another agent's change to a symbol in the same file.
    A difference on a symbol this task never touched is that stale copy, not a change: the graph keeps the
    newer signature, and nothing is recorded against this task.
    """
    changes = deps.reindex(root, rel)
    if not changes:
        return []
    own = set(airspace.owned(task, [c.qualname for c in changes]))
    stale = [(c.qualname, c.old_signature) for c in changes if c.qualname not in own and c.old_signature]
    if stale:
        airspace.restore_signatures(stale)
    return [c for c in changes if c.qualname in own]


def handle_post(payload: dict, deps: Deps, env: Mapping[str, str] = os.environ) -> dict | None:
    target = _target(payload, env)
    if target is None:
        return None
    root, agent, task, rel = target
    try:
        airspace = deps.airspace(root)
    except Exception as e:
        _unavailable(UNAVAILABLE, e)
        return None
    try:
        changes = reindex_own(airspace, deps, root, task, rel)
        # Symbols the edit created exist now, so the task can claim them; a caller-first change then finds it.
        airspace.claim_pending(task)
        if changes:
            airspace.ensure_task(agent, task)
            airspace.record_changes(task, changes)
        # The Stop hook checks the calls in every file the task edited.
        airspace.record_edited_file(task, rel)
        _note_seen(airspace, root, rel)
        return _context("PostToolUse", airspace.pending_briefings(task), _messages(airspace, agent, task))
    except Exception as e:
        _failed(e)
        return None


def handle_any(payload: dict, deps: Deps, env: Mapping[str, str] = os.environ) -> dict | None:
    """PreToolUse for every other tool (Bash, Read, Grep, ...): deliver pending briefings and messages.

    An agent that only runs tests after a contract it calls was changed still hears about it. No indexing and one
    engine construction, so it stays fast; it fails open like the edit hooks.
    """
    if payload.get("tool_name") in EDIT_TOOLS:
        return None  # the edit hooks deliver for edits
    root, agent, task = identity(payload, env)
    try:
        airspace = deps.airspace(root)
    except Exception as e:
        _unavailable(ANY_UNAVAILABLE, e)
        return None
    read = None
    if payload.get("tool_name") == "Read":
        rel = _rel_path(root, str((payload.get("tool_input") or {}).get("file_path") or ""))
        if rel and rel.endswith(".py"):
            try:
                airspace.note_reading(agent, task, rel)
                read = rel
            except Exception as e:
                _failed(e)
    try:
        briefings = airspace.pending_briefings(task)
    except Exception as e:
        detail = " ".join(str(e).split()) or type(e).__name__
        _note(f"airspace: {type(e).__name__} ({detail}), briefings not delivered")
        briefings = []
    messages = _messages(airspace, agent, task)
    # Reading a file: what the graph remembers about the symbols it defines.
    memory = _memory(airspace, task, [read], MEMORY_ITEMS_READ) if read else ""
    return _context("PreToolUse", briefings, messages, memory)


def _note_seen(airspace, root: Path, rel: str) -> None:
    """The file as this edit left it, so a later shell write is told apart from the edit tools' own."""
    from airspace.hooks.reconcile import scope_of

    path = root / rel
    if path.is_file():
        airspace.note_seen(scope_of(root), rel, path.read_text(encoding="utf-8"))


def _reconcile(root: Path, agent: str, task: str, airspace, deps: Deps) -> list[str]:
    from airspace.hooks.reconcile import reconcile

    return reconcile(root, agent, task, airspace, deps, time.time())


def handle_reconcile(payload: dict, deps: Deps, env: Mapping[str, str] = os.environ) -> dict | None:
    """PostToolUse for Bash: files the command wrote are brought into the graph as edits by this task."""
    root, agent, task = identity(payload, env)
    try:
        airspace = deps.airspace(root)
    except Exception as e:
        _unavailable(UNAVAILABLE, e)
        return None
    try:
        reasons = _reconcile(root, agent, task, airspace, deps)
        briefings = airspace.pending_briefings(task) if airspace.agent_of(task) else []
        out = _context("PostToolUse", briefings, _messages(airspace, agent, task))
        if reasons:
            text = "\n".join(reasons)
            if out:
                text += "\n" + out["hookSpecificOutput"]["additionalContext"]
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}
        return out
    except Exception as e:
        _failed(e)
        return None


def handle_prompt(payload: dict, deps: Deps, env: Mapping[str, str] = os.environ) -> dict | None:
    """UserPromptSubmit: note the files the task names as interest, so agents landing early wait for this one, and
    tell the agent what the graph remembers about that code before it starts."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    root, agent, task = identity(payload, env)
    try:
        airspace = deps.airspace(root)
    except Exception as e:
        _unavailable(UNAVAILABLE.replace("edit not checked", "task not noted"), e)
        return None
    try:
        files = list(airspace.note_interest_from_text(agent, task, prompt))
    except Exception as e:
        _failed(e, "task not noted")
        return None
    return _context("UserPromptSubmit", [], [], _memory(airspace, task, files))


def _fingerprint(violations: list[dict]) -> str:
    keys = sorted(f"{v['caller']}|{v['symbol']}|{v['new_sig']}|{v['call']}" for v in violations)
    return hashlib.sha1("\n".join(keys).encode()).hexdigest()[:12]


def handle_stop(
    payload: dict,
    deps: Deps,
    env: Mapping[str, str] = os.environ,
    wait_seconds: float = STOP_WAIT_SECONDS,
    poll_seconds: float = STOP_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """Stop: the holding pattern on landing.

    An agent that finishes before another agent changes a contract it calls makes no further tool call, so a
    briefing never reaches it. Here the calls in the files the task edited are checked against every contract
    change by another agent. While an active agent still claims a callee, the task holds (up to `wait_seconds`).
    A call that no longer fits blocks the stop with the change, once per distinct set of broken calls: a
    continuation (stop_hook_active) that reports the same set again lands, so a call the agent could not fix
    does not use up Claude Code's continuation cap. Otherwise the task lands.
    """
    root, agent, task = identity(payload, env)
    try:
        airspace = deps.airspace(root)
    except Exception as e:
        _unavailable(STOP_UNAVAILABLE, e)
        return None
    try:
        # Files written outside the edit tools count before the landing check, so none of them escapes it.
        try:
            conflicts = _reconcile(root, agent, task, airspace, deps)
        except Exception as e:
            _failed(e, "shell writes not checked")
            conflicts = []
        if airspace.agent_of(task) is None:
            return None  # nothing edited through Airspace
        if conflicts:
            fingerprint = hashlib.sha1("\n".join(conflicts).encode()).hexdigest()[:12]
            if not (payload.get("stop_hook_active") and airspace.last_block(task) == fingerprint):
                airspace.block_landing(task, fingerprint, "")
                return {"decision": "block", "reason": "\n".join(conflicts)}
        deadline = clock() + wait_seconds
        while True:
            # Known names are read again each round: a rename made meanwhile keeps the old name resolvable.
            known = deps.known(root)
            calls = [c for rel in airspace.edited_files(task) for c in deps.calls(root, rel, known)]
            violations, waiting_on = airspace.stop_check(task, calls)
            if not waiting_on or clock() >= deadline:
                break
            airspace.holding(task, waiting_on[0])
            sleep(poll_seconds)
        if violations:
            fingerprint = _fingerprint(violations)
            if not (payload.get("stop_hook_active") and airspace.last_block(task) == fingerprint):
                airspace.block_landing(task, fingerprint, violations[0]["caller"])
                messages = message_context(_messages(airspace, agent, task))
                reason = _localize(landing_hold(violations), root, [(v["symbol"], v["new_sig"]) for v in violations])
                reason = _rename_hint(reason, airspace, [v["symbol"] for v in violations])
                return {"decision": "block", "reason": reason + ("\n" + messages if messages else "")}
        airspace.land(task)
        return _context("Stop", airspace.pending_briefings(task), _messages(airspace, agent, task))
    except Exception as e:
        _failed(e, "landing not checked")
        return None


def default_deps() -> Deps:
    """The real indexer and engine. Imports happen on first use, so this module loads without them.

    A repository connected to a hosted server (`airspace connect`) sends engine calls and parsed facts there over RPC.
    Any other repository uses FalkorDB on this machine.
    """
    graphs: dict[str, Any] = {}
    remotes: dict[str, Any] = {}

    def remote(root: Path):
        """The RPC client for a connected repository, or None. remotes.json is read once per repository."""
        key = os.path.realpath(root)
        if key not in remotes:
            from airspace.remote import client_for, remote_for

            found = remote_for(root)
            remotes[key] = client_for(found) if found is not None else None
        return remotes[key]

    def graph(root: Path):
        key = os.path.realpath(root)
        if key not in graphs:
            from falkordb import FalkorDB

            from airspace.config import settings
            from airspace.graph.db import repo_graph

            s = settings()
            db = FalkorDB(
                host=s.falkordb_host,
                port=s.falkordb_port,
                socket_connect_timeout=_CONNECT_TIMEOUT,
                socket_timeout=_SOCKET_TIMEOUT,
            )
            db.connection.ping()
            graphs[key] = repo_graph(db, root)
        return graphs[key]

    def airspace(root: Path):
        client = remote(root)
        if client is not None:
            from airspace.remote import RemoteAirspace, seen_dir

            engine = RemoteAirspace(client, seen_dir())
            # The ping: a server that is down or refuses the key fails here, as one line, like FalkorDB down does.
            engine.agent_of("")
            return engine

        from airspace.admission.engine import Airspace
        from airspace.config import settings

        s = settings()
        return Airspace(graph(root), lease_seconds=s.lease_seconds, cone_depth=s.cone_depth)

    def analyze(root: Path, tool_name: str, tool_input: dict, known: set[str]) -> EditAnalysis | None:
        from airspace.hooks.edit_analysis import analyze_edit

        return analyze_edit(root, tool_name, tool_input, known)

    def known(root: Path) -> set[str]:
        client = remote(root)
        if client is not None:
            from airspace.remote import remote_known

            return remote_known(client)

        from airspace.admission.engine import removed_qualnames
        from airspace.indexer.writer import known_qualnames

        # Renamed or removed symbols stay known to clearance, so a new call to the old name is still caught.
        g = graph(root)
        return known_qualnames(g) | removed_qualnames(g)

    def reindex(root: Path, rel_path: str) -> list[SignatureChange]:
        client = remote(root)
        if client is not None:
            from airspace.remote import remote_reindex

            return remote_reindex(client, root, rel_path)

        from airspace.indexer.writer import reindex_file

        return reindex_file(graph(root), root, rel_path)

    return Deps(airspace=airspace, analyze=analyze, known=known, reindex=reindex)
