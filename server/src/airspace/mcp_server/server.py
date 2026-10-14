"""The Airspace MCP server: planning tools for an agent, over stdio.

The tools are plain functions of (airspace, agent, task, ...) so they can be called directly; build_server binds them
to the engine for one repository. Text is factual and short, for an agent to read.
"""

import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from airspace.admission.text import briefing_line

DEFAULT_AGENT = "agent-mcp"

INSTRUCTIONS = (
    "Airspace coordinates parallel coding agents on one repository. These tools file a flight plan for symbols, "
    "report which symbols other agents claim, deliver contract briefings and messages, explain the dependency path "
    "between two symbols and list the hot zones where agents have collided."
)


def _join(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def _claims_by_agent(state: dict) -> dict[str, list[str]]:
    return {a["id"]: list(a.get("claims") or []) for a in state.get("agents") or []}


def _owners(state: dict, symbol: str, agent: str) -> list[str]:
    return sorted(a for a, claims in _claims_by_agent(state).items() if a != agent and symbol in claims)


def _contract_changers(state: dict, symbol: str, agent: str) -> list[str]:
    return sorted(
        {
            c["owner_agent"]
            for c in state.get("collisions") or []
            if c.get("kind") == "contract"
            and c.get("resolution") == "held"
            and c.get("symbol") == symbol
            and c.get("owner_agent")
            and c.get("owner_agent") != agent
        }
    )


# Tools


def file_flight_plan(airspace: Any, agent: str, task: str, symbols: list[str], intent: str = "") -> str:
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return "No symbols given, so no flight plan was filed."
    airspace.ensure_task(agent, task, intent)
    cone = airspace.file_plan(agent, task, intent, symbols)
    state = airspace.state()
    mine = set(_claims_by_agent(state).get(agent, []))
    claimed = [s for s in symbols if s in mine]
    noun = "symbol" if len(symbols) == 1 else "symbols"
    lines = [f"Flight plan filed for {agent} on {len(symbols)} {noun}, {len(claimed)} claimed."]
    lines.append(f"Claimed: {_join(claimed)}")
    for s in symbols:
        if s in mine:
            continue
        owners = _owners(state, s, agent)
        if owners:
            lines.append(f"{s}: claimed by {_join(owners)}, so edits to it are held while that claim is live.")
        else:
            lines.append(f"{s}: not claimed, it is not in the code graph.")
    lines.append(f"Impact cone ({len(cone)}): {_join(list(cone))}")
    return "\n".join(lines)


def check_symbols(airspace: Any, agent: str, symbols: list[str]) -> str:
    state = airspace.state()
    mine = set(_claims_by_agent(state).get(agent, []))
    lines = []
    for s in dict.fromkeys(symbols):
        parts = []
        owners = _owners(state, s, agent)
        if owners:
            parts.append(f"claimed by {_join(owners)}")
        elif s in mine:
            parts.append(f"claimed by this agent ({agent})")
        parts.extend(f"{a} is changing its contract" for a in _contract_changers(state, s, agent))
        lines.append(f"{s}: {'; '.join(parts) or 'free'}")
    return "\n".join(lines) or "No symbols given."


def briefings(airspace: Any, agent: str, task: str) -> str:
    lines =[f"Airspace briefing: {briefing_line(b)}" for b in airspace.pending_briefings(task)]
    lines.extend(f"Airspace message: {m}" for m in airspace.pending_messages(agent))
    return "\n".join(lines) or "No pending briefings or messages."


def explain(airspace: Any, from_symbol: str, to_symbol: str) -> str:
    path = airspace.explain(from_symbol, to_symbol)
    if not path:
        return f"No dependency path from {from_symbol} to {to_symbol} in the code graph."
    return f"Path: {' -> '.join(path)} (each symbol depends on the next)."


def hot_zones(airspace: Any) -> str:
    zones = airspace.insights().get("hot_zones") or []
    if not zones:
        return "No hot zones recorded yet."
    lines = []
    for z in zones:
        n = z.get("collisions", 0)
        lines.append(f"{z['qualname']}: {n} collision{'' if n == 1 else 's'}, betweenness {z.get('betweenness', 0)}")
    return "\n".join(lines)


# Server


def build_server(
    root: Path,
    env: Mapping[str, str] = os.environ,
    airspace_factory: Callable[[Path], Any] | None = None,
) -> MCPServer:
    """An MCP server whose tools act for agent AIRSPACE_AGENT (default agent-mcp) as task <agent>:mcp.

    The engine opens on the first tool call, so the server starts even while FalkorDB is down.
    """
    if airspace_factory is None:
        from airspace.api.app import open_airspace

        airspace_factory = open_airspace
    agent = env.get("AIRSPACE_AGENT") or DEFAULT_AGENT
    task = f"{agent}:mcp"
    lock = threading.Lock()
    built: list[Any] = []

    def engine() -> Any:
        with lock:
            if not built:
                built.append(airspace_factory(root))
            return built[0]

    def file_flight_plan_tool(symbols: list[str], intent: str = "") -> str:
        """Files a flight plan that claims these symbols (qualnames) for this agent. Reports which were claimed,
        which another agent holds, and the impact cone of symbols that depend on them."""
        return file_flight_plan(engine(), agent, task, symbols, intent)

    def check_symbols_tool(symbols: list[str]) -> str:
        """For each symbol (qualname), whether another agent claims it or is changing its contract, or free."""
        return check_symbols(engine(), agent, symbols)

    def briefings_tool() -> str:
        """Pending contract briefings and Tower messages for this agent. Each is delivered once."""
        return briefings(engine(), agent, task)

    def explain_tool(from_symbol: str, to_symbol: str) -> str:
        """The shortest dependency path (calls, coverage, inheritance) from one symbol to another."""
        return explain(engine(), from_symbol, to_symbol)

    def hot_zones_tool() -> str:
        """Symbols where agents collide most, with collision counts and call-graph betweenness."""
        return hot_zones(engine())

    server = MCPServer("airspace", instructions=INSTRUCTIONS)
    for name, fn in (
        ("file_flight_plan", file_flight_plan_tool),
        ("check_symbols", check_symbols_tool),
        ("briefings", briefings_tool),
        ("explain", explain_tool),
        ("hot_zones", hot_zones_tool),
    ):
        server.add_tool(fn, name=name)
    return server


def run_stdio(root: Path) -> None:
    build_server(root).run("stdio")
