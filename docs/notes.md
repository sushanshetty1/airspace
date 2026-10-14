# Cairn: pre-hackathon notes

These are ideas, notes and graph sketches only, which rule 8 allows before the event. Implementation starts Oct 15, 00:01 IST.
Submission deadline: **Oct 18, 23:59 IST.** Internal target is Oct 18, 18:00 IST.

## 1. Reading the brief

The sponsor's wording, and what it implies:

- *"The graph has to shape what the agent does, not sit on the side."* Every agent decision must come from a graph query or algorithm result, and the demo has to make that visible.
- *"Show the path behind an answer."* Explanation is data, not prose. Return paths and draw them.
- Rule 3: *"A visualisation drawn on top of ordinary storage does not qualify."* All state lives in FalkorDB, including agent memory and tasks. There is no side database.
- Rule 10 deliverables: public repo; README with the graph data model and the Cypher and algorithms used; demo video; live deployment or full setup instructions; tracks named.
- No judging criteria are published. Assume judges weigh how central the graph is, how well the demo works, explainability, technical depth and polish.

**Strategy:** one product that is a strong entry in all three tracks (rule 5 allows naming all of them), plus a blog post for the side prize.

## 2. What exists (research summary, 2026-10-14)

| Project | Strength | Gap we exploit |
|---|---|---|
| Graphiti (Apache-2.0, ~32k★) | Episodes, edges with two timelines, layered entity resolution, a FalkorDB driver with a graph per group | Brute-force cosine (ignores the vector index); label propagation in Python; no coordination between agents; no path UI; facts retired by unexplained LLM judgement |
| Cognee (Apache-2.0) | Supersession, provenance ledger, post-ingestion memory passes | Provenance kept in SQL, not the graph; in-memory ranking; no handoffs |
| GraphRAG-SDK (FalkorDB) | Native vector indexes, multi-path retrieval | No time model, no sessions, no agents, no algorithms |
| QueryWeaver (AGPL, read for ideas only) | Graph per user, `allShortestPaths` for join paths, Graphiti memory | Text-to-SQL only |
| FalkorDB code-graph (MIT) | Code structure plus MCP tools (`impact_analysis` = `CALLS*1..d`) | No people or ownership, no algorithms, no actions, no memory |
| gds-agent (MIT) | Algorithms as typed MCP tools | Neo4j only, no FalkorDB version |
| Cartography (Apache-2.0) | Each finding query paired with a query returning its explaining path | No agent, no triage, no actions |
| HolmesGPT | Incident RCA agent | No graph; its prompt forbids inferring blast radius |
| gbrain (MIT) | "Company brain" with temporal links | Recursive SQL instead of a native graph, no algorithms |

**No incumbent uses FalkorDB's built-in algorithms.** That is our clearest technical differentiator, and the sponsor will notice it.

Clichés to avoid as the headline: fraud rings, CVE graphs, generic GraphRAG chat, code-graph visualisers.

## 3. What makes Cairn different

1. **Algorithms as agent tools on FalkorDB**:
   - `algo.bfs` / variable-length `CALLS` for blast radius;
   - `algo.SPpaths` for the weighted shortest path to an expert;
   - `algo.betweenness` for bus factor and choke points;
   - `algo.WCC` for knowledge islands;
   - `algo.labelPropagation` to find the de-facto teams (compared with the official ones, a Conway's-law check);
   - `algo.pageRank` for service criticality.
2. **Explanation as data.** Each tool returns a `Trace` (the Cypher, nodes, edges and the source episode for each edge). Answers are `Answer` nodes that `CITE` the trace.
3. **Facts with two timelines and a deterministic reason for retirement.** `retired_by` points at the episode that contradicted the fact, so the UI can show "believed until X because of PR #N".
4. **Coordination lives in the graph.** `Task`, `Claim` (lease) and `Handoff` nodes, with atomic claims because FalkorDB serialises writes per graph. The UI shows an agent timeline.
5. **Procedural memory.** `Playbook` nodes record the tool sequence that answered an intent. They are recalled by vector similarity and reinforced by 👍/👎. Second-session demo: the same question takes fewer tool calls.
6. **Gated actions.** Sentinel drafts a GitHub issue or PR comment for the right owner and posts only after policy plus human approval, to our own sandbox repo, never to the OTel repo. Each action is written back to the graph.
7. **MCP server** exposing these typed tools, so Claude Desktop or Claude Code can use Cairn directly (Track 1: "tool selection through MCP").
8. **One graph per tenant** (OTel demo vs Online Boutique), with guards against queries crossing tenants.

## 4. Demo script (target 3 minutes)

1. **Incident (Track 1).** "checkout is throwing 5xx, what breaks and who do I page?"
   - Sentinel shows the blast-radius trail, the changes that recently touched that path, and the real expert ranked by recent activity, where CODEOWNERS only says `@demo-approvers`.
   - It hands off to Navigator for context and drafts an issue, which we approve and which posts to the sandbox repo.
2. **Memory (Track 2).** A new session the next day: "anything we learned about checkout?"
   - Cairn recalls the investigation and reuses the playbook. Show the tool-call count dropping and the shared task timeline across agents.
3. **Company brain (Track 3).** "Why does cart use Valkey?"
   - Decision chain from Valkey back to Redis, the PRs as evidence, and who decided.
   - Then the bus-factor and silo view.
4. Switch tenant to show isolation. Open FalkorDB Browser for 5 seconds to prove it's real.

## 5. Things to verify on Day 1 (before building on them)

- [ ] `algo.*` signatures and directions in the current FalkorDB image: whether `algo.bfs` is outgoing-only, and the `algo.betweenness` config keys.
- [ ] Concurrent writes to one graph are serialised, so the claim query is atomic.
- [ ] Vector index on relationships (fact edges), and `vecf32` with 384-dimensional fastembed vectors.
- [ ] `exp()` and datetime arithmetic in FalkorDB Cypher; otherwise use epoch seconds.
- [ ] GitHub API rate limits for about 3.4k PRs: ingest a window (last 18 months) plus every PR mentioning Valkey/Redis.
- [ ] How to parse `pb/demo.proto` + `compose.yaml` into service `CALLS` edges (env vars like `CART_ADDR`).

## 6. Four-day plan

| Day | Goal | Cut line if behind |
|---|---|---|
| **Oct 15** | FalkorDB schema and indexes; Scout ingestion (proto, compose, CODEOWNERS, PRs, issues, commits, CHANGELOG); fact writer with two timelines; algorithms checked against real data | Narrow the PR window |
| **Oct 16** | Graph tool layer returning Traces; Navigator and Sentinel on the Claude tool runner; MCP server | Drop `algo.SPpaths` expert path |
| **Oct 17** | Memory and coordination (sessions, tasks, claims, handoffs, playbooks, Curator); web UI trail view and agent timeline | Drop the second tenant; Curator runs on demand only |
| **Oct 18** | Polish; deploy (docker compose on the VPS); README queries finalised; demo video; blog post; **submit by 18:00 IST** | Local setup and video instead of live deploy |

## 7. Side prizes

- **Blog post (AirPods):** "Your agents keep forgetting why. Here's a graph that remembers", on dev.to or Hashnode, with real Cypher and trail screenshots, published Oct 18.
- **Top 50 t-shirts:** follow automatically from a complete, polished submission.
