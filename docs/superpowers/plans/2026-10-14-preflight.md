# Pre-flight: plan parallel work on the graph before any agent starts

**Goal:** given the tasks you are about to hand to agents (each as the symbols it will change), say which can run in parallel and which must coordinate, and why, with the path in the code graph. Every answer comes from FalkorDB: Cypher traversals for impact cones, `shortestPath` for the explanation, `algo.WCC` for the groups, `algo.betweenness` for hot spots.

## Global constraints

- Deterministic: no model call. Same graph and tasks, same answer.
- Read-only on the code graph. Pre-flight writes its own temporary nodes (labels `Flight` and `FlightTask`), keyed by a unique plan id, and deletes them before it answers, also on error.
- Copy rules: no em or en dashes, sentence case, factual.
- Commits by the user only, no co-author lines.

## Engine `server/src/airspace/admission/preflight.py`

```python
def find_symbols(graph, query: str, limit: int = 12) -> list[dict]
    # {"qualname","kind","signature"} for symbols whose qualname contains query (case-insensitive),
    # non-test first, then shorter qualnames first. Empty query: [].

def resolve_symbol(graph, name: str) -> str
    # A qualname, or a unique suffix match ("url_for", "helpers.url_for", "Flask.route").
    # Raises PreflightError(f"No symbol named {name}.", suggestions=[...]) or
    # PreflightError(f"{name} matches several symbols.", suggestions=[...]).

def preflight(graph, tasks: list[dict], depth: int = 2) -> dict
    # tasks: [{"name": str, "symbols": [str, ...]}], 2 to 6 tasks, each 1 to 10 symbols, names unique.
```

Answer of `preflight`:

```json
{
  "tasks": [{"name": "...", "symbols": ["qualname", "..."], "cone": 14, "cone_sample": ["up to 8 qualnames"]}],
  "pairs": [
    {"a": "task name", "b": "task name",
     "kind": "same_symbol" | "calls" | "shared_dependents",
     "symbols": ["the symbols where they meet"],
     "path": ["qualname", "...", "qualname"],
     "shared": 3}
  ],
  "groups": [{"tasks": ["names"], "coordinate": true}],
  "hot": [{"qualname": "...", "betweenness": 12.5}],
  "summary": "Two groups. Rename flash categories and Error page must coordinate; the others can run in parallel."
}
```

- Cone of a task: symbols that reach one of its symbols over `CALLS|COVERS|INHERITS` in 1..depth hops (callers, tests, subclasses), excluding the task's own symbols.
- Pair kinds, strongest first, one entry per pair: `same_symbol` (both change a symbol), `calls` (one task's symbol is in the other's cone: the other changes something that calls it; `path` is the shortest path from the caller to the changed symbol), `shared_dependents` (cones intersect: `shared` is the count, `symbols` up to 5 of them, `path` empty). Pairs with nothing in common are left out.
- Groups: write `(:Flight {id})`, one `(:FlightTask {flight, name})` per task, and `(:FlightTask)-[:MEETS]->(:FlightTask)` for every pair with kind `same_symbol` or `calls`, then `algo.WCC` over FlightTask/MEETS, keeping only this flight's nodes. `coordinate` is true for groups of two or more. Shared dependents alone do not force coordination (they are listed as pairs so a reader can judge).
- Hot: `algo.betweenness` over Symbol/CALLS, restricted to symbols in the union of the tasks' symbols and cones, top 5 with score > 0.
- Summary: one or two plain sentences.

## API (on the demo server and every workspace)

| Method and path | Body or query | Answer |
| --- | --- | --- |
| `GET /api/preflight/repos` | none | `{"repos": [{"id": "flask", "name": "Flask", "symbols": 919}, {"id": "blog", "name": "Sample blog", "symbols": 17}]}`: the bundled demo repos that are indexed |
| `GET /api/preflight/symbols?repo=flask&q=url` | | `{"symbols": [...]}` from `find_symbols` |
| `POST /api/preflight` | `{"repo": "flask", "tasks": [...]}` | the `preflight` answer, or 422 `{"error", "suggestions"}` |
| `POST /api/w/{id}/preflight`, `GET /api/w/{id}/preflight/symbols?q=` | as above without `repo` | on the workspace graph, owner only, `X-Airspace: 1` on the POST |

- Demo repos: graph `demo_flask` from the repo at env `AIRSPACE_FLASK_REPO`, graph `demo_blog` from the bundled fixture. The server indexes each at startup when its path exists (skip quietly when it does not). Rate limit: 30 a minute per client address, like the playground.

## CLI and MCP

- `airspace preflight --root R --task "Name: sym1, sym2" --task "Other: sym3"` prints the summary, the groups, and each pair with its path. Remote-connected repos go through the RPC (`preflight` is added to the RPC allowlist as a graph method `graph.preflight` with args `[tasks, depth]`).
- MCP tool `preflight(tasks: list[{"name","symbols"}])` on the agent's repo graph, answering the same text as the CLI.

## Web `/preflight`

A page (nav item "Pre-flight") where you pick a repo (Flask by default), write two to six tasks (a name and symbols, with search-as-you-type on `/api/preflight/symbols`), and run the check. It shows the summary, the groups as lanes ("Can run in parallel" and "Must coordinate"), each meeting pair with its kind and path (qualnames in mono, arrows between them), each task's cone size, and the hot spots. It opens with a ready example on Flask that has one coordinate group and two parallel tasks, so a first visit shows the point without typing. Signed-in users can switch to one of their workspaces. The homepage "Why a graph" section links to it.
