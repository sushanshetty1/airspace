# Airspace

**Air-traffic control for parallel coding agents.**

Run four coding agents at once and each one passes its tests on its own. Merge them, and the build breaks. Airspace sees the collision coming before the code is written, because it knows how your code connects.

> **Status:** pre-hackathon. This repo holds only design notes, the graph model sketch and empty scaffolding.
> All FalkorDB and agent code gets written during the [FalkorDB Hackathon](https://www.wemakedevs.org/hackathons/falkordb)
> (Oct 15–18, 2026 IST), per rule 8.

**Tracks:** Track 02 (Agent Memory and Coordination) · Track 01 (Agents That Act on Connected Data)

---

## The problem: passes alone, fails together

Developers in 2026 split a feature across several Claude Code or Codex sessions, each in its own git worktree. Worktrees stop agents overwriting each other's files. They don't stop this:

- Agent A changes `slugify(value, allow_unicode=False)` to `slugify(value, *, unicode=False)`.
- At the same moment, agent B adds three new calls to `slugify(title, True)` in another package.
- Both branches pass their tests, and git merges them without a conflict.
- `main` is broken.

Git sees lines. It doesn't see that B's new code depends on the function A is rewriting, across files, through imports and calls. The 2026 benchmark [*Passes Alone, Fails Together*](https://arxiv.org/abs/2609.25396) found this interference in **97%** of runs on constructed Django tasks. A [study of 33,596 agent pull requests](https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/) puts the merge-conflict rate for agent PRs at **27.67%**, and says the semantic layer is the part nobody measures.

## What Airspace does

Airspace keeps a **live code graph in FalkorDB** (symbols, calls, imports, inheritance, test coverage) and puts every agent's work into the same graph:

1. **File a flight plan.** When an agent starts a task, it declares the symbols it intends to change. Airspace computes the task's **impact cone**: everything that calls, imports, overrides or tests those symbols, several hops out.
2. **Clearance before every write.** A Claude Code `PreToolUse` hook asks Airspace before each `Edit` or `Write`. The check is deterministic, with no LLM in the decision:
   - **cleared** when the edit stays inside the agent's airspace;
   - **hold** when it enters another agent's cone;
   - **contract change** when it alters a signature others depend on.
3. **Handoffs, not surprises.** When agent A changes a contract, Airspace finds every active agent whose cone reaches it. It delivers a briefing into their next tool call, with the exact path that connects their work to the change.
4. **Memory across sessions.** Leases, collisions and contract changes stay in the graph. Next time, the planner knows which symbols are hot zones and splits work around them.

The **radar** UI shows the code graph with each agent's cone as a coloured region. Collisions flash, and each one comes with the shortest path that explains it.

## Why this needs a graph

The questions are about connections: "Can A and B work at the same time?" really means "do their cones overlap?"

| Question | Graph work |
|---|---|
| What does this edit affect? | Reverse traversal over `CALLS`, `IMPORTS`, `INHERITS` and `COVERS`, or `algo.bfs` |
| Do two agents collide, and why? | Intersection of their cones, plus `algo.SPpaths` for the explaining path |
| Which tasks can run in parallel? | `algo.WCC` over the conflict graph; each component is serialised, components run concurrently |
| Which symbols are risky to touch? | `algo.betweenness` / `algo.pageRank` on the call graph, plus collision history |
| Who has to hear about this contract change? | Active `CLAIMS` whose cone reaches the changed symbol |

FalkorDB features in use:

- **6.0 MVCC**, so many agents read while admission writes;
- **one graph per repo** (multi-graph);
- built-in **`algo.*`** procedures;
- vector index over symbol docstrings for planning;
- full-text index over symbol names.

## Graph data model (draft)

**Code graph:**

```
(:Repo)-[:HAS]->(:File {path})-[:DEFINES]->(:Symbol {qualname, kind, signature, sig_hash})
(:Symbol)-[:CALLS]->(:Symbol)
(:File)-[:IMPORTS]->(:Symbol)
(:Symbol)-[:INHERITS]->(:Symbol)
(:Test)-[:COVERS]->(:Symbol)
```

**Airspace layer (coordination and memory):**

```
(:Agent {id, harness})-[:FLYING]->(:Task {intent, status, base_commit})
(:Task)-[:CLAIMS {mode: 'write'|'contract', lease_until, fence}]->(:Symbol)
(:Task)-[:CONE {depth}]->(:Symbol)
(:Collision {at, resolution})-[:BETWEEN]->(:Task)
(:Collision)-[:AT]->(:Symbol)
(:ContractChange {old_sig, new_sig, at})-[:ON]->(:Symbol)
(:ContractChange)-[:BRIEFED]->(:Task)
(:Session)-[:RAN]->(:Task)
(:Symbol).collision_count            // hot-zone memory across sessions
```

## Key Cypher (sketches, verified and finalised during the event)

```cypher
// Impact cone: everything that depends on the symbols a task claims, up to 3 hops
MATCH (t:Task {id: $task})-[:CLAIMS]->(s:Symbol)
MATCH (dep)-[:CALLS|IMPORTS|INHERITS|COVERS*1..3]->(s)
MERGE (t)-[:CONE]->(dep)
```

```cypher
// Clearance: does this edit land inside another active task's cone?
MATCH (target:Symbol {qualname: $qualname})
MATCH (other:Task {status: 'active'})-[:CONE|CLAIMS]->(target)
WHERE other.id <> $task
RETURN other.id, other.intent
```

```cypher
// Explain a collision: shortest path from my claimed symbol to theirs
MATCH (a:Symbol {qualname: $mine}), (b:Symbol {qualname: $theirs})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['CALLS', 'IMPORTS', 'INHERITS'], maxLen: 4})
YIELD path
RETURN path
```

```cypher
// Atomic lease (writes to a graph are serialised)
MATCH (s:Symbol {qualname: $qualname})
OPTIONAL MATCH (other:Task)-[c:CLAIMS]->(s) WHERE other.id <> $task AND c.lease_until > $now
WITH s, count(c) AS held WHERE held = 0
MATCH (t:Task {id: $task})
MERGE (t)-[c:CLAIMS]->(s)
SET c.mode = $mode, c.lease_until = $now + $ttl, c.fence = coalesce(c.fence, 0) + 1
RETURN c.fence
```

## How we'll prove it works

We'll run the same parallel-agent workload under three conditions, using the benchmark method from *Passes Alone, Fails Together*:

1. **Worktrees only** (today's default).
2. **Broadcast:** each agent is told what the others changed. The paper reports this recovers 82%.
3. **Airspace:** graph-scoped clearance plus targeted briefings.

Metrics:

- **interference rate:** tests pass on each patch alone, fail when merged;
- **parallelism kept**, compared with running every task one after another;
- **wall-clock time**;
- **tokens**.

The results table goes here once it's measured. We won't publish numbers we haven't run.

## Integrations

- **Claude Code:** `PreToolUse` and `PostToolUse` hooks give deterministic clearance and re-index after edits.
- **Any MCP client:** tools `file_flight_plan`, `request_clearance`, `report_change`, `briefings`, `radar`.

## Stack

- **Graph:** FalkorDB (Docker), FalkorDB Browser.
- **Backend:** Python 3.12, FastAPI, the `falkordb` client, `mcp`. The code graph is built from Python `ast`.
- **Agents under test:** Claude Code (headless), using the Anthropic API.
- **Web:** Vite, React, TypeScript, with the radar drawn by sigma.js.

## Running locally

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up -d falkordb   # FalkorDB on :6379, Browser on :3000
cd server && uv sync
cd ../web && npm install
```

Indexing, hook install and radar commands get added here as they're built.

## Prior art

- [*Passes Alone, Fails Together*](https://arxiv.org/abs/2609.25396) (Xia, Wu, Park, 2026): the benchmark method and the broadcast baseline.
- [*Claim Plane*](https://arxiv.org/abs/2607.21909) (Nikolaev, 2026): admitting change intents before any write.
  - Airspace computes scope from a live graph instead of making agents declare every resource.
- [FalkorDB code-graph](https://github.com/FalkorDB/code-graph) (MIT) and [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext) (MIT): code graphs as agent tools.
  - Both serve a single agent. We studied their schemas; Airspace's indexer is our own.
- [Aura agent collision detection](https://auravcs.com/learn/agent-collision-detection): a description of file, symbol and dependency-level collision detection.

## AI assistance disclosure

We use AI coding assistants (Claude Code) for research, scaffolding and pair programming, as required by rule 11. We can explain and defend the graph model, the queries, the architecture and every technical decision.

## License

Apache-2.0
