<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/banner-dark.png">
    <img alt="Airspace. Air-traffic control for coding agents." src="assets/readme/banner-light.png" width="100%">
  </picture>
</p>

<p align="center">
  <img alt="Status: pre-hackathon" src="https://img.shields.io/badge/status-pre--hackathon-ff5a1f?style=flat-square&labelColor=111112">
  <img alt="Built on FalkorDB" src="https://img.shields.io/badge/built%20on-FalkorDB-111112?style=flat-square">
  <img alt="Works with Claude Code" src="https://img.shields.io/badge/works%20with-Claude%20Code-d97757?style=flat-square&labelColor=111112">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-server-111112?style=flat-square">
  <a href="LICENSE"><img alt="Apache-2.0 licence" src="https://img.shields.io/badge/license-Apache--2.0-111112?style=flat-square"></a>
</p>

<!-- hero.gif: four agents, one collision on the radar, a held edit, a briefing, a green merge. Recorded on Oct 18. -->

**Airspace is air-traffic control for parallel coding agents.** Split a feature across four Claude Code sessions and each one passes its tests on its own. Merge them, and `main` is red: one agent changed a function that another was busy calling. Airspace keeps a live graph of how your code connects. It checks every edit against that graph before the edit is written, and holds the one that would collide.

Built for two kinds of people:

- **Developers** who run several agents at once and are tired of clean merges that break the build.
- **Tool builders** who orchestrate fleets of agents and need a shared, queryable picture of who is touching what.

## How it works

1. **File a flight plan.** When an agent starts a task, Airspace marks the symbols it means to change. It then computes the task's **impact cone**: everything that calls, imports, overrides or tests those symbols, a few hops out.
2. **Ask before every write.** A Claude Code `PreToolUse` hook checks each `Edit` and `Write` with Airspace. The answer is a graph query and a few rules, never a model call:
   - **cleared** when the edit stays in the agent's own airspace;
   - **hold** when it enters another agent's cone;
   - **briefed** when it depends on a contract someone else is changing.
3. **Brief, don't surprise.** When one agent changes a signature, every agent whose cone reaches it gets a briefing on its next tool call. The briefing gives the new signature and the exact path that connects the two pieces of work.

This is what an agent sees:

```text
● Edit(blog/views.py)
  ⏸ Airspace · HOLD
    utils.text.slugify is changing in agent-a
    new   slugify(value, *, unicode=False)
    path  blog.views.render_post ─CALLS→ utils.text.slugify
    Use the new signature, or wait for agent-a to land.

● Edit(blog/views.py)   slugify(post.title, unicode=True)
  ✓ Airspace · cleared
```

### Why a graph

| | |
| --- | --- |
| **Collisions are paths** | Two agents collide when their impact cones meet. That is a traversal over `CALLS`, `IMPORTS`, `INHERITS` and `COVERS`, not a text match. |
| **Every hold explains itself** | `algo.SPpaths` returns the shortest path between the two pieces of work, and the agent and the radar both show it. |
| **Parallel by default** | `algo.WCC` over the conflict graph splits tasks into groups. Groups run at the same time; only tasks inside a group wait for each other. |
| **It remembers** | Holds, briefings and contract changes stay in the graph. Next session, the planner already knows the hot zones and splits work around them. |

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/architecture-dark.png">
    <img alt="Architecture: your coding agents ask airspace/hooks before every edit. airspace/admission checks the FalkorDB graph with Cypher and graph algorithms and returns cleared, held or briefed. airspace/indexer re-indexes the code graph on save. The radar shows cones, collisions and paths live." src="assets/readme/architecture-light.png" width="100%">
  </picture>
</p>

## The graph

Each repo gets its own graph in FalkorDB. It has two layers: the code, and the agents working on it.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/graph-model-dark.png">
    <img alt="Graph model. Airspace layer: Agent FLYING Task; Collision BETWEEN Task; ContractChange BRIEFED Task. Task CLAIMS (mode, lease, fence) and CONE (depth) point down to Symbol in the code layer. Code layer: File DEFINES and IMPORTS Symbol; Symbol CALLS and INHERITS Symbol; Test COVERS Symbol; ContractChange ON Symbol; Collision AT Symbol." src="assets/readme/graph-model-light.png" width="100%">
  </picture>
</p>

<details>
<summary>The same model as text</summary>

```text
(:File {path})-[:DEFINES]->(:Symbol {qualname, kind, signature, sig_hash})
(:Symbol)-[:CALLS]->(:Symbol)
(:File)-[:IMPORTS]->(:Symbol)
(:Symbol)-[:INHERITS]->(:Symbol)
(:Test)-[:COVERS]->(:Symbol)

(:Agent {id, harness})-[:FLYING]->(:Task {intent, status, base_commit})
(:Task)-[:CLAIMS {mode, lease_until, fence}]->(:Symbol)
(:Task)-[:CONE {depth}]->(:Symbol)
(:Collision {at, resolution})-[:BETWEEN]->(:Task)
(:Collision)-[:AT]->(:Symbol)
(:ContractChange {old_sig, new_sig, at})-[:ON]->(:Symbol)
(:ContractChange)-[:BRIEFED]->(:Task)
```

</details>

The queries the product depends on (sketches, finalised during the event):

```cypher
// Impact cone: everything that depends on what a task claims, up to 3 hops
MATCH (t:Task {id: $task})-[:CLAIMS]->(s:Symbol)
MATCH (dep)-[:CALLS|IMPORTS|INHERITS|COVERS*1..3]->(s)
MERGE (t)-[:CONE]->(dep)
```

```cypher
// Clearance: does this edit land in another active task's airspace?
MATCH (target:Symbol {qualname: $qualname})
MATCH (other:Task {status: 'active'})-[:CONE|CLAIMS]->(target)
WHERE other.id <> $task
RETURN other.id, other.intent
```

```cypher
// Why: the shortest path between my work and theirs
MATCH (a:Symbol {qualname: $mine}), (b:Symbol {qualname: $theirs})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['CALLS', 'IMPORTS', 'INHERITS'], maxLen: 4})
YIELD path
RETURN path
```

```cypher
// Lease a symbol atomically (writes to one graph are serialised)
MATCH (s:Symbol {qualname: $qualname})
OPTIONAL MATCH (other:Task)-[c:CLAIMS]->(s) WHERE other.id <> $task AND c.lease_until > $now
WITH s, count(c) AS held WHERE held = 0
MATCH (t:Task {id: $task})
MERGE (t)-[c:CLAIMS]->(s)
SET c.mode = $mode, c.lease_until = $now + $ttl, c.fence = coalesce(c.fence, 0) + 1
RETURN c.fence
```

## Does it work?

We run the same parallel workload three ways, using the grading method from [*Passes Alone, Fails Together*](https://arxiv.org/abs/2609.25396). Tests run on each agent's patch alone and on the merge, and only failures caused by the merge count.

| Condition | Interference | Parallelism kept | Wall-clock | Tokens |
| --- | --- | --- | --- | --- |
| Worktrees only | | | | |
| Broadcast (each agent is told what the others changed) | | | | |
| Airspace | | | | |

The table fills in once the runs are done. We won't publish a number we haven't measured.

**Honest limits.** The paper found interference in 97% of runs on constructed Django tasks, but in only 1 of 417 pairs of real merged PRs. Constructed tasks show whether a coordination method works; they don't show how often the problem happens in practice. Airspace's code graph is built from Python `ast`, so dynamic dispatch and string imports can hide edges, and unresolved calls are reported, not guessed.

## What's in this repo

| Path | What it is |
| --- | --- |
| [`server/src/airspace/indexer`](server/src/airspace/indexer) | Python `ast` → symbols, calls, imports, inheritance and test coverage, re-indexed per file |
| [`server/src/airspace/graph`](server/src/airspace/graph) | FalkorDB connection, schema, indexes and the Cypher above |
| [`server/src/airspace/admission`](server/src/airspace/admission) | Flight plans, cones, clearance, leases, briefings |
| [`server/src/airspace/hooks`](server/src/airspace/hooks) | Claude Code `PreToolUse` / `PostToolUse` hooks |
| [`server/src/airspace/mcp_server`](server/src/airspace/mcp_server) | MCP tools: `file_flight_plan`, `request_clearance`, `report_change`, `briefings`, `radar` |
| [`server/src/airspace/api`](server/src/airspace/api) | HTTP and live updates for the radar |
| [`server/src/airspace/bench`](server/src/airspace/bench) | The three-condition benchmark harness |
| [`web`](web) | The radar (Vite, React, sigma.js) |
| [`docs/notes.md`](docs/notes.md) | Research, plan and decisions |

## Quick start

```sh
cp .env.example .env            # ANTHROPIC_API_KEY, for the benchmark agents only
docker compose up -d falkordb   # FalkorDB on :6379, Browser on :3000
cd server && uv sync
cd ../web && npm install
```

Indexing, hook install and radar commands land here as they're built.

## Open decisions

- [x] **Where the decision lives.** Clearance is Cypher plus rules, enforced by a hook that fails closed. No model is asked whether an edit is safe.
- [x] **First language.** Python, through the standard-library `ast`. Other languages come later through tree-sitter.
- [x] **First harness.** Claude Code, through `PreToolUse` and `PostToolUse` hooks. Any MCP client can use the same tools.
- [x] **Storage.** Everything (code graph, flight plans, leases, history) lives in FalkorDB, one graph per repo. No side database.
- [ ] **Benchmark repo.** Django, to match the paper's constructed tasks, or a smaller library if Django's test suite is too slow for many runs.
- [ ] **Cone depth.** Three hops by default; tune it against hold rate and parallelism in the benchmark.

## Roadmap

- [ ] Indexer and code graph, with incremental re-index on save
- [ ] Cones, clearance, leases and collision paths
- [ ] Claude Code hooks and the MCP server
- [ ] Briefings on contract changes
- [ ] The radar
- [ ] Hot-zone memory across sessions
- [ ] Benchmark: worktrees vs broadcast vs Airspace
- [ ] Live deployment, demo video and write-up

## Prior art

- [*Passes Alone, Fails Together*](https://arxiv.org/abs/2609.25396) (Xia, Wu, Park, 2026): the benchmark method and the broadcast baseline.
- [*Claim Plane*](https://arxiv.org/abs/2607.21909) (Nikolaev, 2026): admitting change intents before any write.
  - Airspace works out scope from a live graph instead of asking agents to declare every resource.
- [FalkorDB code-graph](https://github.com/FalkorDB/code-graph) and [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext): code graphs as tools for a single agent.
  - We studied their schemas. Airspace's indexer is our own.

## FalkorDB Hackathon

Built for the [FalkorDB Hackathon](https://www.wemakedevs.org/hackathons/falkordb) (Oct 15–18, 2026), entering **Track 02 · Agent Memory and Coordination** and **Track 01 · Agents That Act on Connected Data**.

All product code is written during the event. Before it, this repo held only notes, diagrams and empty scaffolding.

We use AI coding assistants (Claude Code) for research, scaffolding and pair programming, and say so here as rule 11 requires. We can explain every part of the graph model, the queries and the design.

## Creators

<table>
  <tr>
    <td align="center" width="160">
      <a href="https://github.com/sushanshetty1"><img src="https://github.com/sushanshetty1.png?size=160" width="80" alt="Sushan Shetty"><br><b>Sushan Shetty</b></a><br><sub>@sushanshetty1</sub>
    </td>
  </tr>
</table>

## License

[Apache-2.0](LICENSE).
