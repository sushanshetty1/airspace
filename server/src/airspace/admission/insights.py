"""Memory the graph keeps across flights: hot zones and safe parallel groups.

Both are computed with FalkorDB's built-in algorithms. Hot zones combine collision history with betweenness
centrality over the call graph (a symbol many call paths run through is risky to change). Parallel groups are the
weakly connected components of a CONFLICTS graph between agents: agents in different components can fly at once.
"""

_BETWEENNESS = """
CALL algo.betweenness({nodeLabels: ['Symbol'], relationshipTypes: ['CALLS']}) YIELD node, score
WHERE score > 0
RETURN node.qualname, score
"""

_WCC = """
CALL algo.WCC({nodeLabels: ['Agent'], relationshipTypes: ['CONFLICTS']}) YIELD node, componentId
RETURN node.id, componentId
"""

# Pairs of agents where one agent's live claim sits in the other's claims or impact cone.
_OVERLAPS = """
MATCH (a:Agent)-[:FLYING]->(:Task {status: 'active'})-[c:CLAIMS]->(s:Symbol)
WHERE c.lease_until > $now
MATCH (b:Agent)-[:FLYING]->(:Task {status: 'active'})-[r:CLAIMS|CONE]->(s)
WHERE a.id <> b.id AND (type(r) = 'CONE' OR r.lease_until > $now)
RETURN DISTINCT a.id, b.id
"""


def _rows(graph, cypher: str, params: dict | None = None) -> list[list]:
    return graph.query(cypher, params or {}).result_set


def _count(graph, label: str) -> int:
    return _rows(graph, f"MATCH (n:{label}) RETURN count(n)")[0][0]


def hot_zones(graph, limit: int = 10) -> list[dict]:
    """Symbols ranked by collisions, then betweenness. Symbols with neither are left out."""
    counts = {
        q: n for q, n in _rows(graph, "MATCH (x:Collision)-[:AT]->(s:Symbol) RETURN s.qualname, count(x)")
    }
    scores: dict[str, float] = {}
    # algo.betweenness fails on fewer than two nodes, where every score would be 0 anyway.
    if _count(graph, "Symbol") >= 2:
        scores = {q: float(score) for q, score in _rows(graph, _BETWEENNESS)}
    zones = [
        {"qualname": q, "collisions": int(counts.get(q, 0)), "betweenness": scores.get(q, 0.0)}
        for q in set(counts) | set(scores)
    ]
    zones.sort(key=lambda z: (-z["collisions"], -z["betweenness"], z["qualname"]))
    return zones[:limit]


def active_agents(graph) -> list[str]:
    rows = _rows(graph, "MATCH (a:Agent)-[:FLYING]->(:Task {status: 'active'}) RETURN DISTINCT a.id ORDER BY a.id")
    return [r[0] for r in rows]


def refresh_conflicts(graph, now: float) -> set[tuple[str, str]]:
    """Rewrite the CONFLICTS edges between active agents. Returns the pairs, lower id first."""
    _rows(graph, "MATCH (:Agent)-[k:CONFLICTS]->(:Agent) DELETE k")
    active = set(active_agents(graph))
    pairs = {tuple(sorted(r)) for r in _rows(graph, _OVERLAPS, {"now": now})}
    held = _rows(graph, "MATCH (x:Collision {resolution: 'held'}) RETURN DISTINCT x.held_agent, x.owner_agent")
    pairs |= {tuple(sorted(r)) for r in held if r[0] and r[1] and r[0] != r[1]}
    pairs = {p for p in pairs if p[0] in active and p[1] in active}
    if pairs:
        _rows(
            graph,
            """UNWIND $pairs AS p
            MATCH (x:Agent {id: p[0]}), (y:Agent {id: p[1]})
            MERGE (x)-[:CONFLICTS]->(y)""",
            {"pairs": [list(p) for p in sorted(pairs)]},
        )
    return pairs


def parallel_groups(graph, now: float) -> list[dict]:
    """Active agents grouped by WCC component. A group of more than one agent has a conflict inside it."""
    refresh_conflicts(graph, now)
    active = set(active_agents(graph))
    if not active:
        return []
    groups: dict[int, list[str]] = {}
    # algo.WCC fails on a single node; a lone agent is its own component.
    rows = _rows(graph, _WCC) if _count(graph, "Agent") >= 2 else [[a, 0] for a in active]
    for agent, component in rows:
        if agent in active:
            groups.setdefault(component, []).append(agent)
    out = [{"agents": sorted(g), "conflict": len(g) > 1} for g in groups.values()]
    out.sort(key=lambda g: (-len(g["agents"]), g["agents"]))
    return out
