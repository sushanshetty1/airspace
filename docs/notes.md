# Airspace: pre-hackathon notes

These are ideas, notes and graph sketches only, which rule 8 allows before the event. Implementation starts Oct 15, 00:01 IST.
Submission deadline: **Oct 18, 23:59 IST.** Internal target is Oct 18, 18:00 IST.

## 1. Why we dropped the first idea ("Cairn", a company brain)

Every part of it had already been shown to these judges:

- The **FalkorDB Memory Meets Motion** event (Aug 2026) had Continuum (people, projects and decisions), Drift (a decision graph with contradiction flags and an approval gate) and Hopper (dependency blast radius, where no path means safe).
- The **WeMakeDevs × Cognee** event (Jun–Jul 2026, the same organiser, 1,200+ submissions) had:
  - Lethe, the grand winner: forgetting for on-call triage;
  - Rewind: a highlighted trail behind each answer;
  - MemOps: a blast-radius simulator;
  - MemoryScope: the blast radius of correcting a fact;
  - Smriti: incident memory.
- Commercial tools already cover it: Unblocked's Social Graph Builder (who knows what, bus factor), Edge Delta (time-aware blast radius), Atlassian Teamwork Graph, and Faulkner DB (an ADR graph on FalkorDB).

## 2. What wins (research across Neo4j, FalkorDB, WeMakeDevs and Anthropic events, 2025–26)

1. **One hero feature, not a platform.** Setups with a cast of named agents placed as standouts, not winners.
2. **A measured before/after against a baseline.** Korca went from 72% to 93.4% and placed third at Neo4j; GroundTruth scored 0/20 against a baseline's 18/20; Lethe was blind-judged against RAG.
3. **The graph does what a table or vector search can't**, shown explicitly:
   - Atrium's two-hop misconception query (FalkorDB first place);
   - Hopper's "no path = safe".
4. **Real data and a live reveal.**
5. **Guardrails that don't depend on the LLM:** deterministic writers, approval gates, read-only query paths.
6. **WeMakeDevs specifics:**
   - Criteria are usually six, equally weighted: Impact, Creativity, Technical Excellence, Best Use of Sponsor, UX, Presentation.
   - "The demo is scored as hard as the code."
   - A sponsor feature must appear **in the video** to count.
   - Commit steadily; one giant commit looks suspicious.
   - A live URL plus a YouTube demo is the norm.
   - Solo builders win often.
   - The README should read like an engineering document: architecture diagram, benchmark, an "Honest limits" section, a stack table with reasons, an AI disclosure.
7. **FalkorDB specifics:**
   - Their recaps praise source tracing, read-only guards on generated queries, idempotent imports and honest failure.
   - They're pushing: FalkorDB 6.0 (Rust core, MVCC, Sep 29); shortest paths at any distance (CCH, Dijkstra, A*; Oct 5 and Oct 12); `algo.maxFlow`, `algo.harmonicCentrality`; `graph.traverse` in UDFs; multi-graph.

## 3. Why Airspace

- **A problem every judge has hit in 2026:** running parallel Claude Code or Codex sessions and getting a broken `main` after a clean merge.
- **The graph is the whole product.** A collision is literally two impact cones intersecting in the call graph. Vectors and tables can't express it.
- **A measurable baseline exists:**
  - The *Passes Alone, Fails Together* method (arXiv 2609.25396): 97% interference on constructed Django tasks, and a broadcast message recovers 82%.
  - Our target: higher recovery than broadcast while keeping more parallelism than full serialisation (Claim Plane serialised all 6 of its 6 pairs).
- **Deterministic guardrail:** the clearance decision is Cypher plus rules, never the LLM, enforced by a Claude Code `PreToolUse` hook that fails closed.
- **Track 2 at its core:** shared state between agents, handoffs, high-concurrency reads and writes (FalkorDB 6.0 MVCC), memory across sessions (hot zones), one graph per repo.
- **Track 1:** agents act on what the graph shows (hold, brief, re-plan), algorithms as tools, tool selection through MCP.
- **Not seen at any event we checked.** Nearest prior art: the Claim Plane paper (no graph, 6-pair feasibility check), Aura (commercial, description only), codegraph (single agent).

## 4. Demo video (≤3 minutes)

1. **Cold open (20 s).** Four Claude Code terminals, one feature split four ways, all green. Merge, and `main` is red. "Passes alone, fails together."
2. **Same run with Airspace (60 s).**
   - The radar shows four coloured cones on the code graph.
   - Agent A's edit to `slugify` is flagged as a contract change.
   - The radar flashes, showing the shortest path from B's new call site to A's change.
   - B's next tool call receives the briefing and adapts.
   - Merge: green.
3. **The graph is real (20 s).** FalkorDB Browser on the same graph; one `algo.WCC` query shows which tasks could safely run in parallel.
4. **Numbers (30 s).** Bar chart of interference rate and parallelism kept for worktrees only, broadcast and Airspace across N task sets.
5. **Memory (20 s).** Next session, the planner avoids the hot zone, and the collision never happens.
6. **Close (10 s).** One-line install: the MCP server plus the Claude Code hook.

## 5. Benchmark plan

- **Target repo:** a real, well-tested Python repo with dense internal call graphs. First choice is Django, matching the paper's helpers. Fallback is a smaller library (e.g. `httpx` or `rich`) if Django's test suite is too slow.
- **Task sets:** N sets of 2–4 parallel tasks, each built around a real helper whose interface one task must change while the others add callers. This follows the paper's constructed tier. Add a few "natural" sets: one real feature request split by a planner.
- **Conditions:** worktrees only / broadcast / Airspace.
- **Grading:** run each patch alone and the merged result; count only failures caused by merging.
- **Agents:** Claude Code headless, the same model and effort in every condition.
- **Report:** interference rate, parallelism kept, wall-clock time, tokens.
- **Budget:** cap API spend. Start with about 10 sets × 3 conditions and scale only if time allows.
- **Honest limits for the README:** the paper's mined real-world Django pairs showed interference in only 1 of 417, so constructed rates don't estimate how often this happens in practice. Say so plainly.

## 6. Things to verify on Day 1

- [ ] `algo.bfs` direction and `algo.SPpaths` config keys in the current image. Does `relTypes` take a list?
- [ ] That writes to a graph are serialised, so the lease query is atomic. Find the MVCC semantics in 6.0.
- [ ] `graph.traverse` UDF availability, as a possible way to compute cones.
- [ ] Claude Code hook contract: `PreToolUse` deny with a reason, and injecting `additionalContext` for briefings.
- [ ] Python `ast` call resolution quality on the target repo (imports, methods, aliases). Measure unresolved call sites.
- [ ] Whether the paper's code or tasks are public. Otherwise rebuild the constructed tier from its description.

## 7. Four-day plan

| Day | Goal | Cut line if behind |
|---|---|---|
| **Oct 15** | Indexer (Python `ast` to FalkorDB, incremental re-index per file); cone, clearance, lease and explain queries tested on the target repo; algorithm checks | Index only the target package, not tests |
| **Oct 16** | Admission service + MCP server + Claude Code hooks; two live agents colliding and being briefed end to end | Briefing delivered at the next prompt, not the next tool call |
| **Oct 17** | Benchmark harness and runs; radar UI (cones, collisions, explaining path, timeline); hot-zone memory | Fewer task sets; static radar replay instead of live |
| **Oct 18** | Numbers into the README; deploy the radar plus a demo replay; record the video; blog post; **submit by 18:00 IST** | Local setup and video instead of a live deploy |

## 8. Side prizes

- **Blog post (AirPods):** "Your coding agents pass alone and fail together", with the benchmark chart and real Cypher. Publish on dev.to or Hashnode on Oct 18.
- **Top 50:** follows from a complete, polished submission.
