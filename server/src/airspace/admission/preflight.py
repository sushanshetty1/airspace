"""Pre-flight: before any agent starts, which of the planned tasks can run in parallel and which must coordinate.

Each task is the symbols it will change. Its impact cone is what reaches those symbols over CALLS, COVERS and
INHERITS (callers, tests, subclasses). Two tasks meet when they change the same symbol, when one changes a symbol
in the other's cone (the path in the graph says why), or, more weakly, when their cones overlap. Groups are the
weakly connected components (algo.WCC) of the strong meetings, and hot spots are the symbols in play that the
most call paths run through (algo.betweenness).

Deterministic and read-only on the code graph: the only writes are this plan's own Flight and FlightTask nodes,
keyed by a unique plan id and deleted before the answer, also on error.
"""

import logging
import uuid
from typing import Any

from airspace.indexer.resolve import ALIAS_MARK

log = logging.getLogger("airspace.preflight")

# Edges along which a change to one symbol can break another, as in the engine: "dependent -> dependency".
_DEPENDS = "CALLS|COVERS|INHERITS"

MIN_TASKS, MAX_TASKS = 2, 6
MAX_SYMBOLS = 10
MAX_NAME = 60
MAX_QUERY = 200
MIN_DEPTH, MAX_DEPTH = 1, 4
SAMPLE = 8
SHARED_SAMPLE = 5
HOT = 5
SUGGESTIONS = 5

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}

_FIND = """
MATCH (s:Symbol) WHERE toLower(s.qualname) CONTAINS $q
RETURN s.qualname, s.kind, s.signature
ORDER BY CASE WHEN s.is_test THEN 1 ELSE 0 END, size(s.qualname), s.qualname
LIMIT $limit
"""

_BETWEENNESS = """
CALL algo.betweenness({nodeLabels: ['Symbol'], relationshipTypes: ['CALLS']}) YIELD node, score
WHERE score > 0
RETURN node.qualname, score
"""

_WCC = """
CALL algo.WCC({nodeLabels: ['FlightTask'], relationshipTypes: ['MEETS']}) YIELD node, componentId
WHERE node.flight = $flight
RETURN node.name, componentId
"""


class PreflightError(ValueError):
    """Input pre-flight cannot plan. The message is short and factual; suggestions are qualnames to try instead."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.suggestions = list(suggestions or [])


def _rows(graph, cypher: str, params: dict | None = None) -> list[list]:
    return graph.query(cypher, params or {}).result_set


def _words(n: int) -> str:
    return _WORDS.get(n, str(n))


# Symbols


def find_symbols(graph, query: str, limit: int = 12) -> list[dict]:
    """Symbols whose qualname contains `query`, ignoring case: non-test first, then the shorter qualnames."""
    query = (query or "").strip().lower()[:MAX_QUERY] if isinstance(query, str) else ""
    if not query:
        return []
    limit = max(1, min(50, int(limit)))
    return [
        {"qualname": q, "kind": kind, "signature": sig}
        for q, kind, sig in _rows(graph, _FIND, {"q": query, "limit": limit})
    ]


def _exists(graph, qualname: str) -> bool:
    return bool(_rows(graph, "MATCH (s:Symbol {qualname: $q}) RETURN s.qualname LIMIT 1", {"q": qualname}))


def _reexport(graph, name: str) -> str | None:
    """The symbol a package re-exports under `name` (flask.Flask -> flask.app.Flask), if it is in the graph."""
    rows = _rows(graph, "MATCH (f:File) WHERE size(coalesce(f.exports, [])) > 0 RETURN f.exports")
    for (exported,) in rows:
        for item in exported:
            public, mark, defined = item.partition(ALIAS_MARK)
            if mark and public == name and _exists(graph, defined):
                return defined
    return None


def resolve_symbol(graph, name: str) -> str:
    """A qualname for `name`: the qualname itself, a package re-export, or the one qualname ending in ".<name>".

    People write "url_for" or "Flask.route", not full qualnames, so a unique suffix is enough. Anything else
    raises PreflightError with the qualnames that come closest.
    """
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise PreflightError("A symbol name is empty.")
    if len(name) > MAX_QUERY:
        raise PreflightError(f"A symbol name is longer than {MAX_QUERY} characters.")
    if _exists(graph, name):
        return name
    exported = _reexport(graph, name)
    if exported:
        return exported
    rows = _rows(
        graph,
        """MATCH (s:Symbol) WHERE s.qualname ENDS WITH $suffix
        RETURN s.qualname ORDER BY CASE WHEN s.is_test THEN 1 ELSE 0 END, size(s.qualname), s.qualname""",
        {"suffix": "." + name},
    )
    if len(rows) == 1:
        return rows[0][0]
    if rows:
        raise PreflightError(f"{name} matches several symbols.", [r[0] for r in rows[:SUGGESTIONS * 2]])
    raise PreflightError(f"No symbol named {name}.", _near(graph, name))


def _near(graph, name: str) -> list[str]:
    """Qualnames close to a name that matched nothing: its last segment, then shorter prefixes of it (a typo
    is usually near the end), down to three characters."""
    last = name.rsplit(".", 1)[-1]
    for end in range(len(last), max(2, len(last) - 8), -1):
        found = find_symbols(graph, last[:end], SUGGESTIONS)
        if found:
            return [s["qualname"] for s in found]
    return []


# Input


def _depth(depth: Any) -> int:
    # Interpolated into variable-length patterns (Cypher cannot parameterise them), so force an int and clamp it.
    if isinstance(depth, bool):
        raise PreflightError("The depth must be a whole number from 1 to 4.")
    try:
        value = int(depth)
    except (TypeError, ValueError):
        raise PreflightError("The depth must be a whole number from 1 to 4.") from None
    return max(MIN_DEPTH, min(MAX_DEPTH, value))


def _validate(tasks: Any) -> list[tuple[str, list[str]]]:
    """(name, symbols as written) per task, checked for shape before any lookup."""
    if not isinstance(tasks, list):
        raise PreflightError("Tasks must be a list, each with a name and symbols.")
    if not MIN_TASKS <= len(tasks) <= MAX_TASKS:
        raise PreflightError(f"Pre-flight takes {MIN_TASKS} to {MAX_TASKS} tasks, not {len(tasks)}.")
    out: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for i, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            raise PreflightError(f"Task {i} must have a name and symbols.")
        name = task.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            raise PreflightError(f"Task {i} has no name.")
        if len(name) > MAX_NAME:
            raise PreflightError(f"Task {i} has a name longer than {MAX_NAME} characters.")
        if any(ord(c) < 32 for c in name):
            raise PreflightError(f"Task {i} has a name that does not fit on one line.")
        if name in seen:
            raise PreflightError(f"Two tasks are named {name}.")
        seen.add(name)
        symbols = task.get("symbols")
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise PreflightError(f"{name} needs a list of symbols.")
        symbols = [s.strip() for s in symbols if s.strip()]
        if not 1 <= len(symbols) <= MAX_SYMBOLS:
            raise PreflightError(f"{name} needs 1 to {MAX_SYMBOLS} symbols, not {len(symbols)}.")
        out.append((name, symbols))
    return out


# Graph reads


def _cone(graph, symbols: list[str], depth: int) -> dict[str, tuple[int, bool]]:
    """{qualname: (hops to the nearest of `symbols`, is a test)} for what reaches them, the symbols excluded."""
    rows = _rows(
        graph,
        f"""MATCH p = (d:Symbol)-[:{_DEPENDS}*1..{depth}]->(s:Symbol)
        WHERE s.qualname IN $qs AND NOT d.qualname IN $qs
        RETURN d.qualname, coalesce(d.is_test, false), min(length(p))""",
        {"qs": symbols},
    )
    return {q: (int(hops), bool(is_test)) for q, is_test, hops in rows}


def _nearest(cone: dict[str, tuple[int, bool]]) -> list[str]:
    """Qualnames nearest first, code before tests, then by name: the order a reader takes in a cone."""
    return sorted(cone, key=lambda q: (cone[q][0], cone[q][1], q))


def _shortest(graph, callers: list[str], targets: list[str], depth: int) -> list[str]:
    """The shortest dependency path from one of `callers` to one of `targets`, ties broken by name."""
    # shortestPath is only allowed inside WITH or RETURN in FalkorDB.
    rows = _rows(
        graph,
        f"""MATCH (a:Symbol) WHERE a.qualname IN $callers
        MATCH (b:Symbol) WHERE b.qualname IN $targets
        WITH a, b, shortestPath((a)-[:{_DEPENDS}*1..{depth}]->(b)) AS p
        WHERE p IS NOT NULL
        RETURN [n IN nodes(p) | n.qualname], length(p), a.qualname, b.qualname""",
        {"callers": callers, "targets": targets},
    )
    if not rows:
        return []
    best = min(rows, key=lambda r: (r[1], r[2], r[3]))
    return list(best[0])


def _pair(graph, a: dict, b: dict, depth: int) -> dict | None:
    """How tasks a and b meet, strongest kind first, or None when they have nothing in common."""
    own_a, own_b = set(a["symbols"]), set(b["symbols"])
    cone_a, cone_b = a["_cone"], b["_cone"]
    shared = set(cone_a) & set(cone_b)
    base = {"a": a["name"], "b": b["name"], "shared": len(shared)}

    same = own_a & own_b
    if same:
        first = sorted(same)
        return {**base, "kind": "same_symbol", "symbols": first, "path": [first[0]]}

    # a's symbol sits in b's cone: changing it touches a caller, test or subclass of what b changes. Either way round.
    paths = []
    for callers, targets in ((own_a & set(cone_b), own_b), (own_b & set(cone_a), own_a)):
        if callers:
            path = _shortest(graph, sorted(callers), sorted(targets), depth)
            if path:
                paths.append(path)
    if paths:
        path = min(paths, key=lambda p: (len(p), p))
        return {**base, "kind": "calls", "symbols": [path[0], path[-1]], "path": path}

    if shared:
        both = {q: min(cone_a[q], cone_b[q]) for q in shared}
        return {**base, "kind": "shared_dependents", "symbols": _nearest(both)[:SHARED_SAMPLE], "path": []}
    return None


def _groups(graph, names: list[str], meets: list[tuple[str, str]]) -> list[list[str]]:
    """Components of the MEETS graph between this plan's tasks, by algo.WCC on temporary Flight nodes."""
    flight = uuid.uuid4().hex
    try:
        _rows(graph, "CREATE (:Flight {id: $flight})", {"flight": flight})
        _rows(graph, "UNWIND $names AS n CREATE (:FlightTask {flight: $flight, name: n})",
              {"flight": flight, "names": names})
        if meets:
            _rows(
                graph,
                """UNWIND $meets AS m
                MATCH (x:FlightTask {flight: $flight, name: m[0]}), (y:FlightTask {flight: $flight, name: m[1]})
                CREATE (x)-[:MEETS]->(y)""",
                {"flight": flight, "meets": [list(m) for m in meets]},
            )
        # algo.WCC fails on fewer than two nodes; a lone task is its own group.
        rows = _rows(graph, _WCC, {"flight": flight}) if len(names) >= 2 else [[n, i] for i, n in enumerate(names)]
    finally:
        try:
            _rows(graph, "MATCH (t:FlightTask {flight: $flight}) DETACH DELETE t", {"flight": flight})
            _rows(graph, "MATCH (f:Flight {id: $flight}) DETACH DELETE f", {"flight": flight})
        except Exception as e:  # never hide the error that brought us here
            log.warning("airspace: pre-flight %s not cleaned up (%s)", flight, e)
    component = {name: comp for name, comp in rows}
    by_component: dict[Any, list[str]] = {}
    for name in names:  # input order, inside and across groups
        by_component.setdefault(component.get(name, ("alone", name)), []).append(name)
    return list(by_component.values())


def _hot(graph, in_play: set[str]) -> list[dict]:
    # algo.betweenness fails on fewer than two nodes, where every score would be 0 anyway.
    if _rows(graph, "MATCH (s:Symbol) RETURN count(s)")[0][0] < 2:
        return []
    scores = [(q, float(score)) for q, score in _rows(graph, _BETWEENNESS) if q in in_play]
    scores.sort(key=lambda x: (-x[1], x[0]))
    return [{"qualname": q, "betweenness": round(s, 2)} for q, s in scores[:HOT]]


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _summary(groups: list[dict], n_tasks: int) -> str:
    coordinate = [g["tasks"] for g in groups if g["coordinate"]]
    alone = [g["tasks"][0] for g in groups if not g["coordinate"]]
    if not coordinate:
        if n_tasks == 2:
            return "Both tasks can run in parallel. Neither changes or calls what the other changes."
        return f"All {_words(n_tasks)} tasks can run in parallel. None changes or calls what another changes."
    count = len(groups)
    head = f"{_words(count).capitalize()} group{'' if count == 1 else 's'}."
    parts = [f"{_and(names)} must coordinate" for names in coordinate]
    if len(alone) == 1:
        parts.append(f"{alone[0]} can run in parallel")
    elif alone:
        parts.append("the others can run in parallel")
    return f"{head} {'; '.join(parts)}."


def _past(graph, planned: list[dict]) -> tuple[list[dict], str]:
    """Each task's history over its symbols and cone, and one sentence naming the symbol in play that collided most
    before (ties to the earlier task, then the name), or "" when nothing in play has collided."""
    from airspace.admission import memory

    histories = []
    worst: tuple[int, int, str, str] | None = None  # (-collisions, task index, qualname, task name)
    for i, t in enumerate(planned):
        qs = [*t["symbols"], *t["_cone"]]
        found = memory.history(graph, qs)
        histories.append({k: found[k] for k in ("collisions", "notes", "changes")})
        for q, n in memory.collision_counts(graph, qs).items():
            key = (-n, i, q, t["name"])
            if n > 0 and (worst is None or key < worst):
                worst = key
    if worst is None:
        return histories, ""
    return histories, f"{worst[3]} touches {worst[2]}, which collided {_times(-worst[0])} before."


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def preflight(graph, tasks: list[dict], depth: int = 2) -> dict:
    """Plan `tasks` ([{"name", "symbols"}], 2 to 6, each 1 to 10 symbols) on the code graph. Raises PreflightError.

    Pairs: same_symbol, calls (with the shortest path from the caller to the changed symbol) or shared_dependents
    (with how many dependents both cones reach); `shared` is the cone overlap for every kind. Groups come from the
    first two kinds only: shared dependents alone do not force coordination, they are listed for a reader to judge.
    """
    depth = _depth(depth)
    planned = []
    for name, written in _validate(tasks):
        symbols = list(dict.fromkeys(resolve_symbol(graph, s) for s in written))
        cone = _cone(graph, symbols, depth)
        planned.append({"name": name, "symbols": symbols, "_cone": cone})

    pairs = []
    for i, a in enumerate(planned):
        for b in planned[i + 1:]:
            met = _pair(graph, a, b, depth)
            if met is not None:
                pairs.append({k: met[k] for k in ("a", "b", "kind", "symbols", "path", "shared")})
    meets = [(p["a"], p["b"]) for p in pairs if p["kind"] in ("same_symbol", "calls")]
    names = [t["name"] for t in planned]
    groups = [{"tasks": g, "coordinate": len(g) > 1} for g in _groups(graph, names, meets)]

    in_play = {q for t in planned for q in (*t["symbols"], *t["_cone"])}
    histories, past = _past(graph, planned)
    summary = _summary(groups, len(planned))
    return {
        "tasks": [
            {"name": t["name"], "symbols": t["symbols"], "cone": len(t["_cone"]),
             "cone_sample": _nearest(t["_cone"])[:SAMPLE], "history": h}
            for t, h in zip(planned, histories)
        ],
        "pairs": pairs,
        "groups": groups,
        "hot": _hot(graph, in_play),
        "summary": f"{summary} {past}" if past else summary,
    }


# One answer for every front end


def plan_for(engine: Any, tasks: list[dict], depth: int = 2) -> dict:
    """The answer for an engine: a remote one (RemoteAirspace) asks its server, a local Airspace reads its graph."""
    remote = getattr(engine, "preflight", None)
    if callable(remote):
        return remote(tasks, depth)
    return preflight(engine.graph, tasks, depth)


def as_text(answer: dict) -> str:
    """The answer as plain lines, for the CLI and for an agent reading the MCP tool."""
    lines = [answer["summary"], ""]
    coordinate = [g["tasks"] for g in answer["groups"] if g["coordinate"]]
    parallel = [name for g in answer["groups"] if not g["coordinate"] for name in g["tasks"]]
    if coordinate:
        lines.append("Must coordinate")
        lines.extend(f"  {', '.join(names)}" for names in coordinate)
    if parallel:
        lines.append("Can run in parallel")
        lines.extend(f"  {name}" for name in parallel)
    lines.append("")
    lines.append("Tasks")
    for t in answer["tasks"]:
        lines.append(f"  {t['name']}: {', '.join(t['symbols'])} (cone {t['cone']}){_earlier(t.get('history'))}")
    lines.append("")
    lines.append(f"Pairs ({len(answer['pairs'])})")
    for p in answer["pairs"]:
        if p["kind"] == "same_symbol":
            detail = f"both change {', '.join(p['symbols'])}"
        elif p["kind"] == "calls":
            detail = " -> ".join(p["path"])
        else:
            detail = f"{p['shared']} shared, such as {', '.join(p['symbols'])}"
        lines.append(f"  {p['a']} and {p['b']}: {p['kind']}, {detail}")
    lines.append("")
    lines.append(f"Hot spots ({len(answer['hot'])})")
    for h in answer["hot"]:
        lines.append(f"  {h['qualname']}  betweenness {h['betweenness']}")
    return "\n".join(lines)


def _earlier(history: dict | None) -> str:
    """", from earlier sessions: 3 collisions, 2 notes" for a task with a past, else ""."""
    if not history:
        return ""
    names = {"collisions": ("collision", "collisions"), "notes": ("note", "notes"), "changes": ("change", "changes")}
    parts = [f"{history[k]} {names[k][history[k] != 1]}" for k in names if history.get(k)]
    return f", from earlier sessions: {', '.join(parts)}" if parts else ""


def error_text(e: PreflightError) -> str:
    if not e.suggestions:
        return e.message
    return f"{e.message} Did you mean: {', '.join(e.suggestions)}?"
