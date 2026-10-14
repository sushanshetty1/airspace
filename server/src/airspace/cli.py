"""The airspace command: index | hook pre|post|any | install-hooks | status | serve | mcp | insights."""

import argparse
import os
import json
import re
import shlex
import sys
import time
from pathlib import Path

from airspace.hooks.handlers import Deps, default_deps, handle_any, handle_post, handle_pre

MATCHER = "Edit|Write|MultiEdit"
# Every other tool an agent uses between edits, so a briefing reaches an agent that only runs tests or reads.
ANY_MATCHER = "Bash|Read|Grep|Glob|Task|WebFetch|WebSearch|NotebookEdit"
# (Claude Code hook event, airspace hook, matcher)
_HOOKS = [("PreToolUse", "pre", MATCHER), ("PreToolUse", "any", ANY_MATCHER), ("PostToolUse", "post", MATCHER)]
_HANDLERS = {"pre": handle_pre, "post": handle_post, "any": handle_any}


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


def _airspace(root: Path):
    from airspace.api.app import open_airspace

    return open_airspace(root)


def _serve(root: Path, host: str, port: int) -> None:
    import uvicorn

    from airspace.api.app import default_app

    # Behind a reverse proxy (Caddy in production), trust its forwarded headers so rate limits see real client IPs.
    forwarded = os.environ.get("AIRSPACE_FORWARDED_IPS", "127.0.0.1")
    uvicorn.run(default_app(root), host=host, port=port, proxy_headers=True, forwarded_allow_ips=forwarded)


def _mcp(root: Path) -> None:
    from airspace.mcp_server.server import run_stdio

    run_stdio(root)


# Commands.


def _cmd_index(root: Path) -> int:
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
    for hook_event, event, matcher in _HOOKS:
        entries = hooks.setdefault(hook_event, [])
        if _has_airspace_hook(entries, event):
            report.append(f"  {hook_event}: airspace hook {event} already present")
            continue
        command = _hook_command(event)
        entries.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
        report.append(f"  {hook_event} ({matcher}): {command}")
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


def _cmd_status(root: Path) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="airspace", description="Air-traffic control for parallel coding agents.")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("index", "index a Python repo into FalkorDB"),
        ("install-hooks", "add the Airspace hooks to <root>/.claude/settings.json"),
        ("status", "show active tasks, their claims and recent collisions"),
        ("mcp", "run the Airspace MCP server over stdio"),
        ("insights", "show hot zones and the groups of agents that can fly in parallel"),
        ("serve", "run the HTTP API for Tower"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")

    serve = sub.choices["serve"]
    serve.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8787, help="port to listen on (default: 8787)")

    hook = sub.add_parser("hook", help="run a Claude Code hook (reads the hook JSON on stdin)")
    hook.add_argument("event", choices=["pre", "post", "any"])

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
    return _cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
