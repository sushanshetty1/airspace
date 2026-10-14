"""The airspace command: index | hook pre|post|any|stop | install-hooks | status | serve | mcp | insights | preflight |
connect | disconnect."""

import argparse
import os
import json
import re
import shlex
import sys
import time
from pathlib import Path

from airspace.hooks.handlers import (
    Deps,
    default_deps,
    handle_any,
    handle_post,
    handle_pre,
    handle_prompt,
    handle_reconcile,
    handle_stop,
)

MATCHER = "Edit|Write|MultiEdit"
# Every other tool an agent uses between edits, so a briefing reaches an agent that only runs tests or reads.
ANY_MATCHER = "Bash|Read|Grep|Glob|Task|WebFetch|WebSearch|NotebookEdit"
# Seconds Claude Code gives the Stop hook. The holding pattern waits up to 240 s inside it.
STOP_TIMEOUT = 300
# (Claude Code hook event, airspace hook, matcher or None, timeout or None)
_HOOKS = [
    ("PreToolUse", "pre", MATCHER, None),
    ("PreToolUse", "any", ANY_MATCHER, None),
    ("PostToolUse", "post", MATCHER, None),
    ("PostToolUse", "reconcile", "Bash", None),
    ("Stop", "stop", None, STOP_TIMEOUT),
    ("UserPromptSubmit", "prompt", None, None),
]
_HANDLERS = {"pre": handle_pre, "post": handle_post, "any": handle_any, "stop": handle_stop, "prompt": handle_prompt,
             "reconcile": handle_reconcile}


# Providers. Module level so tests can swap them.


def _deps() -> Deps:
    return default_deps()


def _graph(root: Path):
    from airspace.graph.db import connect, ensure_schema, repo_graph

    db = connect()
    db.connection.ping()
    graph = repo_graph(db, root)
    ensure_schema(graph)
    return graph


def _index_repo(graph, root: Path):
    from airspace.indexer.writer import index_repo

    return index_repo(graph, root)


def _remote(root: Path):
    """The RPC client when the repository is connected to a hosted server, else None (FalkorDB on this machine)."""
    from airspace.remote import client_for, remote_for

    found = remote_for(root)
    return client_for(found) if found is not None else None


def _client(server: str, key: str):
    from airspace.remote import RpcClient

    return RpcClient(server, key)


def _remote_airspace(client):
    from airspace.remote import RemoteAirspace, seen_dir

    return RemoteAirspace(client, seen_dir())


def _airspace(root: Path):
    client = _remote(root)
    if client is not None:
        return _remote_airspace(client)

    from airspace.api.app import open_airspace

    return open_airspace(root)


def _serve(root: Path, host: str, port: int) -> None:
    import uvicorn

    from airspace.api.app import default_app

    # Behind a reverse proxy (Caddy in production), trust its forwarded headers so rate limits see real client IPs.
    forwarded = os.environ.get("AIRSPACE_FORWARDED_IPS", "127.0.0.1")
    uvicorn.run(default_app(root), host=host, port=port, proxy_headers=True, forwarded_allow_ips=forwarded)


def _mcp(root: Path) -> None:
    from airspace.mcp_server.server import build_server, run_stdio

    client = _remote(root)
    if client is None:
        run_stdio(root)
        return
    build_server(root, airspace_factory=lambda _root: _remote_airspace(client)).run("stdio")


# Commands.


def _server_down(e: Exception) -> int:
    print(f"airspace: Airspace server unavailable ({e})", file=sys.stderr)
    return 1


def _cmd_index(root: Path) -> int:
    try:
        client = _remote(root)
    except Exception as e:
        return _server_down(e)
    if client is not None:
        from airspace.remote import remote_index

        try:
            stats = remote_index(client, root)
        except Exception as e:
            return _server_down(e)
    else:
        try:
            graph = _graph(root)
        except Exception as e:
            print(f"airspace: FalkorDB unavailable ({e})", file=sys.stderr)
            return 1
        stats = _index_repo(graph, root)
    print(f"Indexed {stats.files} files, {stats.symbols} symbols, {stats.calls} calls ({stats.unresolved} unresolved)")
    return 0


def _cmd_hook(event: str) -> int:
    """Always exits 0: a hook must never break the agent's tool call."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except ValueError as e:
        print(f"airspace: hook input is not a JSON object ({e})", file=sys.stderr)
        return 0
    try:
        out = _HANDLERS[event](payload, _deps())
    except Exception as e:
        print(f"airspace: hook failed, edit not checked ({type(e).__name__}: {e})", file=sys.stderr)
        return 0
    if out is not None:
        print(json.dumps(out))
    return 0


def _hook_command(event: str) -> str:
    return f"{shlex.quote(sys.executable)} -m airspace.cli hook {event}"


def _has_airspace_hook(entries: list, event: str) -> bool:
    pattern = re.compile(rf"airspace(\.cli)?\s+hook\s+{event}\b")
    for entry in entries:
        for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if isinstance(hook, dict) and pattern.search(str(hook.get("command", ""))):
                return True
    return False


def _cmd_install_hooks(root: Path) -> int:
    path = root / ".claude" / "settings.json"
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text() or "{}")
        except ValueError as e:
            print(f"airspace: {path} is not valid JSON ({e}); nothing written", file=sys.stderr)
            return 1
    hooks = settings.setdefault("hooks", {})
    report = []
    for hook_event, event, matcher, timeout in _HOOKS:
        entries = hooks.setdefault(hook_event, [])
        if _has_airspace_hook(entries, event):
            report.append(f"  {hook_event}: airspace hook {event} already present")
            continue
        command = _hook_command(event)
        hook: dict = {"type": "command", "command": command}
        if timeout is not None:
            hook["timeout"] = timeout
        entries.append({"matcher": matcher, "hooks": [hook]} if matcher else {"hooks": [hook]})
        report.append(f"  {hook_event} ({matcher or 'no matcher'}): {command}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"Wrote {path}")
    print("\n".join(report))
    return 0


_TASKS = """
MATCH (t:Task) WHERE coalesce(t.status, 'active') = 'active'
OPTIONAL MATCH (a:Agent)-[:FLYING]->(t)
OPTIONAL MATCH (t)-[c:CLAIMS]->(s:Symbol) WHERE c.lease_until > $now
RETURN t.id, a.id, collect(s.qualname)
ORDER BY t.id
"""

_COLLISIONS = """
MATCH (c:Collision)
OPTIONAL MATCH (c)-[:AT]->(s:Symbol)
OPTIONAL MATCH (c)-[:BETWEEN]->(t:Task)
OPTIONAL MATCH (a:Agent)-[:FLYING]->(t)
RETURN c.id, c.at, s.qualname, collect(coalesce(a.id, '?') + ' (' + t.id + ')')
ORDER BY c.at DESC
LIMIT 10
"""


def _when(at) -> str:
    if isinstance(at, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))
    return str(at) if at is not None else "?"


def _cmd_remote_status(client) -> int:
    """A connected repository: the agents and recent collisions from the workspace's engine."""
    try:
        state = _remote_airspace(client).state()
    except Exception as e:
        return _server_down(e)
    print(f"Workspace {client.workspace or '?'} on {client.server}")
    agents = [a for a in state.get("agents") or [] if a.get("status") != "released"]
    print(f"Agents flying ({len(agents)})")
    for a in agents:
        claimed = ", ".join(a.get("claims") or []) or "none"
        flags = "".join(f", {f}" for f in ("paused", "held") if a.get(f))
        print(f"  {a['id']}  {a.get('status')}{flags}  claims: {claimed}")
    collisions = state.get("collisions") or []
    print(f"Recent collisions ({len(collisions)})")
    for c in collisions:
        between = ", ".join(x for x in (c.get("held_agent"), c.get("owner_agent")) if x) or "?"
        print(f"  {c.get('id')}  {_when(c.get('at'))}  at {c.get('symbol') or '?'}  between {between}")
    return 0


def _cmd_status(root: Path) -> int:
    try:
        client = _remote(root)
    except Exception as e:
        return _server_down(e)
    if client is not None:
        return _cmd_remote_status(client)
    try:
        graph = _graph(root)
    except Exception as e:
        print(f"airspace: FalkorDB unavailable ({e})", file=sys.stderr)
        return 1
    tasks = graph.query(_TASKS, {"now": time.time()}).result_set
    print(f"Active tasks ({len(tasks)})")
    for task_id, agent_id, claims in tasks:
        claimed = ", ".join(sorted(claims)) or "none"
        print(f"  {task_id}  {agent_id or '?'}  claims: {claimed}")
    collisions = graph.query(_COLLISIONS).result_set
    print(f"Recent collisions ({len(collisions)})")
    for col_id, at, symbol, between in collisions:
        print(f"  {col_id}  {_when(at)}  at {symbol or '?'}  between {', '.join(sorted(between)) or '?'}")
    return 0


def _cmd_insights(root: Path) -> int:
    try:
        insights = _airspace(root).insights()
    except Exception as e:
        print(f"airspace: FalkorDB unavailable ({e})", file=sys.stderr)
        return 1
    zones = insights.get("hot_zones") or []
    print(f"Hot zones ({len(zones)})")
    for z in zones:
        n = z.get("collisions", 0)
        print(f"  {z['qualname']}  {n} collision{'' if n == 1 else 's'}, betweenness {z.get('betweenness', 0)}")
    groups = insights.get("parallel_groups") or []
    print(f"Parallel groups ({len(groups)})")
    for g in groups:
        note = "in conflict" if g.get("conflict") else "no conflicts"
        print(f"  {', '.join(g.get('agents') or [])}  ({note})")
    return 0


def _parse_task(text: str) -> dict:
    """A "Name: sym1, sym2" argument as {"name", "symbols"}. Qualnames hold no colon, so the last one ends the name."""
    name, colon, symbols = text.rpartition(":")
    if not colon or not name.strip():
        raise ValueError(f'Write each task as "Name: symbol, symbol", not {text!r}.')
    return {"name": name.strip(), "symbols": [s.strip() for s in symbols.split(",") if s.strip()]}


def _cmd_preflight(root: Path, task_texts: list[str], depth: int) -> int:
    """Which tasks can run in parallel and which must coordinate, on the local graph or the connected workspace."""
    from airspace.admission.preflight import PreflightError, as_text, preflight

    try:
        tasks = [_parse_task(t) for t in task_texts]
    except ValueError as e:
        print(f"airspace: {e}", file=sys.stderr)
        return 1
    try:
        client = _remote(root)
    except Exception as e:
        return _server_down(e)
    if client is not None:
        from airspace.remote import remote_preflight

        def plan() -> dict:
            return remote_preflight(client, tasks, depth)
    else:
        try:
            graph = _graph(root)
        except Exception as e:
            return _db_down(e)

        def plan() -> dict:
            return preflight(graph, tasks, depth)
    try:
        answer = plan()
    except PreflightError as e:
        print(f"airspace: {e.message}", file=sys.stderr)
        if e.suggestions:
            print("Did you mean:", file=sys.stderr)
            for s in e.suggestions:
                print(f"  {s}", file=sys.stderr)
        return 1
    except Exception as e:
        return _server_down(e) if client is not None else _db_down(e)
    print(as_text(answer))
    return 0


def _db_down(e: Exception) -> int:
    print(f"airspace: FalkorDB unavailable ({e})", file=sys.stderr)
    return 1


def _cmd_connect(root: Path, server: str, key: str) -> int:
    """Check the key, store it for this repository, index the repository into the workspace and say what is next."""
    from airspace.remote import Remote, RemoteError, remote_index, remotes_path, set_remote

    server = server.rstrip("/")
    client = _client(server, key)
    try:
        client.call("graph.known")
    except RemoteError as e:
        if e.status == 401:
            print(f"airspace: {server} did not accept this key ({e}). Nothing was saved.", file=sys.stderr)
        else:
            print(f"airspace: cannot connect to {server} ({e}). Nothing was saved.", file=sys.stderr)
        return 1
    workspace = client.workspace
    if not workspace:
        print(f"airspace: {server} did not name a workspace for this key. Nothing was saved.", file=sys.stderr)
        return 1
    try:
        set_remote(root, Remote(server=server, key=key, workspace=workspace))
    except (OSError, RemoteError) as e:
        print(f"airspace: cannot save {remotes_path()} ({e})", file=sys.stderr)
        return 1
    print(f"Connected {root} to workspace {workspace} on {server}")
    try:
        stats = remote_index(client, root)
    except Exception as e:
        print(f"airspace: the first index did not finish ({e}). Run airspace index --root {shlex.quote(str(root))} "
              "to try again.", file=sys.stderr)
        return 1
    print(f"Indexed {stats.files} files, {stats.symbols} symbols, {stats.calls} calls ({stats.unresolved} unresolved)")
    print(f"Tower: {server}/w/{workspace}")
    print(f"Next: airspace install-hooks --root {shlex.quote(str(root))}")
    return 0


def _cmd_disconnect(root: Path) -> int:
    from airspace.remote import RemoteError, remove_remote

    try:
        removed = remove_remote(root)
    except (OSError, RemoteError) as e:
        print(f"airspace: {e}", file=sys.stderr)
        return 1
    if removed:
        print(f"Disconnected {root}. Its hooks use FalkorDB on this machine again.")
    else:
        print(f"{root} was not connected.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="airspace", description="Air-traffic control for parallel coding agents.")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("index", "index a Python repo into FalkorDB"),
        ("install-hooks", "add the Airspace hooks to <root>/.claude/settings.json"),
        ("status", "show active tasks, their claims and recent collisions"),
        ("mcp", "run the Airspace MCP server over stdio"),
        ("insights", "show hot zones and the groups of agents that can fly in parallel"),
        ("preflight", "before agents start: which planned tasks can run in parallel and which must coordinate"),
        ("serve", "run the HTTP API for Tower"),
        ("connect", "send this repository's hooks to a hosted Airspace workspace"),
        ("disconnect", "send this repository's hooks to FalkorDB on this machine again"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")

    serve = sub.choices["serve"]
    serve.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8787, help="port to listen on (default: 8787)")

    connect = sub.choices["connect"]
    connect.add_argument("--server", required=True, help="the Airspace server, such as https://airspace.sushans.dev")
    connect.add_argument("--key", required=True, help="the workspace key (ask_...)")

    pre = sub.choices["preflight"]
    pre.add_argument("--task", action="append", required=True, metavar='"NAME: SYMBOL, SYMBOL"',
                     help="a task and the symbols it will change; give 2 to 6")
    pre.add_argument("--depth", type=int, default=2, help="hops of callers, tests and subclasses in a cone (1 to 4)")

    hook = sub.add_parser("hook", help="run a Claude Code hook (reads the hook JSON on stdin)")
    hook.add_argument("event", choices=list(_HANDLERS))

    replay = sub.add_parser("replay", help="record or summarize a Tower replay of a real run")
    replay.add_argument("rest", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command == "hook":
        return _cmd_hook(args.event)
    if args.command == "replay":
        from airspace.replay import main as replay_main

        return replay_main(args.rest)
    root = args.root.resolve()
    if args.command == "index":
        return _cmd_index(root)
    if args.command == "install-hooks":
        return _cmd_install_hooks(root)
    if args.command == "serve":
        _serve(root, args.host, args.port)
        return 0
    if args.command == "mcp":
        _mcp(root)
        return 0
    if args.command == "insights":
        return _cmd_insights(root)
    if args.command == "preflight":
        return _cmd_preflight(root, args.task, args.depth)
    if args.command == "connect":
        return _cmd_connect(root, args.server, args.key)
    if args.command == "disconnect":
        return _cmd_disconnect(root)
    return _cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
