# Phase 3: Proof and ship

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:**
- Measure Airspace against today's alternatives with real Claude Code agents.
- Make every claim on the website and in the README come from that measurement or from a real run.
- Ship a live demo (replay, playground) and the submission.

**Architecture:**
- Coordination gaps found while designing the benchmark are closed first.
- A benchmark harness drives headless Claude Code sessions in git worktrees under three conditions and grades the merged result.
- A recorder turns a real run into a replay that Tower can play back.
- A playground endpoint runs the real engine on the indexed fixture repo without agents.
- Everything ships as Docker Compose.

**Tech stack:** Python 3.12, FalkorDB, FastAPI, Claude Code CLI (`claude -p`), git worktrees, React and Vite (`web/`), Docker Compose.

**Spec:**
- `docs/notes.md` (benchmark plan, demo script)
- Phase 1 and 2 plans
- *Passes Alone, Fails Together* (arXiv 2609.25396): the grading method

## Global Constraints

- **Numbers:** every number published on the site or in the README comes from a committed results file produced by the harness. Nothing is estimated or rounded up.
- **Scope of claims:** we report what the runs show. The honest-limits text stays: constructed tasks show whether coordination works, not how often the problem happens in practice.
- **Storage and clearance:** FalkorDB only. Deterministic clearance.
- **Text:** factual hook text, no em or en dashes, design rules from `memory: design-no-ai-tells`.
- **Commits:** authored by the owner only. No AI attribution.

## Review Focus

1. **The caller lands before the contract change.** agent-b adds `slugify(post.title, True)` first, then agent-a changes the signature. *Expected: agent-b is briefed on its next tool call of any kind, not only its next edit. Owner: T1; test `test_caller_first_then_change_briefs_on_next_tool`.*
2. **Agents in separate worktrees of one repo.** *Expected: they share one graph through `AIRSPACE_GRAPH`, so they see each other. Owner: T1; test `test_graph_override_shares_graph_across_worktrees`.*
3. **A benchmark agent times out or crashes.** *Expected: the run is recorded as `error` and excluded from rates, with the count reported. It never hangs the harness. Owner: T2.*
4. **A textual merge conflict between the two patches.** *Expected: it is recorded as `conflict` (git caught it), counted separately from semantic interference. Owner: T2.*
5. **The deployed Tower with no live agents.** *Expected: replay mode starts automatically with a clear "Replay of a real run" note. Owner: T3.*

---

### T1: Close the coordination gaps (lead, before the benchmark)

**Files:**
- `graph/db.py`: `AIRSPACE_GRAPH` overrides the graph name.
- `types.py`: `EditAnalysis.signature_changes: list[SignatureChange]`, defaulting to empty.
- `hooks/edit_analysis.py`: compare the old and new signatures of touched symbols.
- `hooks/handlers.py`:
  - On a cleared pre check, call `record_changes` with the signature changes immediately. Concurrent agents see the change before the file is even written; the post hook's `reindex` then finds no new change and records nothing twice.
  - Add a lightweight `handle_any` for every other tool: deliver pending briefings and messages as `additionalContext`, otherwise exit silently in under 100 ms.
- `cli.py`: `hook any`; `install-hooks` adds `PreToolUse` with matcher `Bash|Read|Grep|Glob|Task|WebFetch` running `hook any`.
- Tests: `test_graph_override_shares_graph_across_worktrees`, `test_pre_records_signature_change_before_write`, `test_post_does_not_double_record`, `test_caller_first_then_change_briefs_on_next_tool`, `test_install_hooks_adds_any_hook`.

### T2: Benchmark harness

**Files:** `server/src/airspace/bench/{tasks.py,runner.py,grade.py,report.py}`, `bench/tasks/*.json`, `bench/results/*.json` (committed), `tests/test_bench_grade.py`.

**Task sets.** Six task sets on the fixture repo, constructed the way the paper's constructed tier is. In each set, one task changes a helper's interface and the other adds a caller that a natural reading of the current code would write with the old interface:
1. `slugify` gets keyword-only `unicode`, while a caller adds a unicode slug in `render_post`.
2. `truncate_words` gets keyword-only `limit`, while a caller truncates tag names in `tag_create`.
3. `Post.get_absolute_url` is renamed to `Post.url`, while a caller adds permalinks in `LatestPosts.item_description`.
4. `render_post` gets a required `request` argument, while a caller adds an index page that calls `render_post(post)`.
5. `Tag.save` returns `None` instead of `self`, while a caller chains `Tag(name).save().slug`.
6. `slugify` uses underscores instead of hyphens, while a caller adds a test that asserts the hyphen form.

Each set carries hidden acceptance tests for both tasks.

**Conditions:**
- `worktrees`: no coordination.
- `broadcast`: each prompt includes the other task's description, as a plan-sharing baseline.
- `airspace`: hooks installed in both worktrees, sharing one graph via `AIRSPACE_GRAPH`, with the repo indexed first.

The two agents run **concurrently**, using `claude -p --permission-mode acceptEdits --output-format json --max-turns 25`, with a 10-minute timeout each.

**Grading (`grade.py`, pure and tested):**
1. Apply A alone and B alone.
2. Merge B into A.
3. Run the fixture tests plus both hidden test files in each state.
4. Classify the outcome:
   - `interference`: both alone pass, merged fails;
   - `clean`: everything passes;
   - `conflict`: git merge conflict;
   - `task_failed`: a patch fails alone;
   - `error`.
5. Record wall-clock time, cost (from the JSON output) and hold/brief counts (from the graph events).

**Report (`report.py`):** writes `bench/results/summary.json` and a markdown table:
- interference rate per condition;
- wall-clock;
- cost;
- holds per run.

**Scale:** 6 sets × 3 conditions = 18 paired runs (36 Claude sessions). Run the harness once, commit the raw results and the summary.

### T3: Replay and playground

**Replay:**
- `airspace replay record --root DIR --out demo/replay.json` captures the events, radar snapshots per event and collision details from a real run, such as the live run used for the video.
- `GET /api/replay` serves it.
- Tower `?replay=1` (and the deployed default when the API reports `mode: replay`) plays the events back on a timeline with play, pause and scrub controls.

**Playground:**
- `POST /api/playground/check` takes `{change: {symbol, new_signature}, edit: {caller, call}}`.
- It runs the real engine on a scratch copy of the indexed fixture graph (a unique graph that is deleted after use) and returns the verdict, the reason and the path.
- The `/playground` page has two short forms, prefilled with the story, and shows the verdict with the airspace lens.

### T4: Ship

- `Dockerfile` for the API (uv), a static web build served by the API at `/`, and `docker-compose.prod.yml` (FalkorDB, API with a replay snapshot, healthchecks).
- Deploy to the owner's VPS after confirming the target. Put an HTTPS URL in the README and on the site.

### T5: Final testing and real data everywhere

- Full suite, web build, the end-to-end test, and one more live two-session run recorded as the replay.
- **README:**
  - the Results table from `summary.json`;
  - real screenshots of Tower from the live run;
  - Quick start, Tower, MCP and benchmark instructions;
  - graph model and Cypher (rule 10 requirement);
  - an accurate roadmap and the AI disclosure.
- **Website:**
  - the Results section uses `summary.json`, with no "Measuring" placeholders;
  - "See it run" goes to Tower replay;
  - install commands match the real CLI;
  - the hero activity text matches real event texts.
- Write the demo video script and the blog post draft in `docs/`.
