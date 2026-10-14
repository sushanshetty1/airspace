# Airspace Implementation Plan (three phases)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Airspace end to end. It keeps a live FalkorDB graph of a Python codebase and of the coding agents working on it, and it holds any edit that would break another agent's work before the edit is written.

**Architecture:** One Python server package (`server/src/airspace`) owns everything:
- the graph (FalkorDB, one graph per repo);
- the indexer (`ast` to symbols and calls);
- the admission engine (flight plans, cones, clearance, leases, contract changes, briefings);
- the Claude Code hooks;
- a CLI.

Phase 2 adds the MCP server, an HTTP and live-events API, Tower (the web app in `web/`) and memory. Phase 3 adds the benchmark, replay and playground, deployment, the video and the write-up.

**Tech stack:** Python 3.12, uv, `falkordb` 1.7, FalkorDB 6.x in Docker, pytest. Later: FastAPI, `mcp`, Vite, React, TypeScript (the existing `web/`).

**Spec:** `README.md` (graph model and Cypher), `docs/notes.md` (strategy, benchmark, demo), `docs/website-notes.md`.

## Global Constraints

- FalkorDB is the only store. No SQLite, JSON state files or in-memory registries that outlive one process (hackathon rule 3).
- The clearance decision is deterministic Cypher plus rules. No LLM call anywhere in `admission/` or `hooks/`.
- Hook messages are factual statements, not imperatives. Claude Code treats imperative hook text as possible prompt injection.
- One graph per repo, named `airspace_<12 hex chars of sha1(realpath(repo_root))>`.
- `shortestPath` must appear inside `WITH` or `RETURN`, never in `MATCH`. This is a FalkorDB limitation, verified on 2026-10-14.
- An aggregation followed by `MATCH` loses rows in FalkorDB. Match every node you need **before** the `WITH ... count(...)`. This is verified; see the lease query in Task 3.
- No em dashes or en dashes in user-facing strings.
- Commits are authored by the repo owner only. No `Co-Authored-By` or AI attribution lines.
- Tests never open windows or play sound. They need FalkorDB on `localhost:6379` (`docker compose up -d falkordb`), and every test uses its own uniquely named graph and deletes it afterwards.

## Review Focus

1. **An edit to a file the indexer has never seen** (a new file): it is cleared, the file is indexed afterwards, and nothing crashes. *Owner: Task 4; test `test_pre_hook_new_file_is_cleared`.*
2. **Syntax errors mid-edit**: agents often write half-finished code. The parse fails, the edit is cleared with a note, and the graph is unchanged. *Owner: Task 2 (`test_parse_syntax_error_returns_none`) and Task 4 (`test_pre_hook_syntax_error_is_cleared`).*
3. **The same agent editing its own claimed symbol repeatedly**: always cleared, and the lease is renewed, not stacked. *Owner: Task 3; test `test_own_claim_is_cleared_and_renewed`.*
4. **An expired lease from a crashed agent**: it must not block others forever. *Owner: Task 3; test `test_expired_claim_does_not_hold`.*
5. **FalkorDB is down**: the hook must fail open with a clear stderr note, not hang Claude Code. *Owner: Task 4; test `test_pre_hook_fails_open_when_db_down`.*

---

## The three phases

| Phase | Outcome | Done when |
|---|---|---|
| **1. Core engine** (now) | The graph, the indexer, the admission engine, Claude Code hooks and a CLI work on a real repo | The end-to-end test passes: agent-a changes `slugify`; agent-b's edit adding `slugify(post.title, True)` is held with the path and briefing; agent-b's retry is cleared. Plus `airspace install-hooks` works in a real Claude Code session. |
| **2. Tower, MCP, memory** | Humans see and steer; agents plan through MCP; the graph remembers | Tower shows real live data from FalkorDB. Release, pause, message and approve from Tower are enforced by the hooks. MCP tools work from Claude Code. Hot zones (`algo.betweenness`) and parallel groups (`algo.WCC`) feed the planner. |
| **3. Proof and ship** | Measured results, a live demo, the submission | The benchmark runs three conditions on constructed tasks. Replay mode and the playground are live on the VPS. The video is recorded, README numbers are filled in, the blog post is published, and the submission is made. |

### Open-source work we learn from, and what we do better

| Project | What we take (ideas, not code) | Our own touch |
|---|---|---|
| FalkorDB/code-graph (MIT) | One analyzer pass per file; definitions, then calls; a graph per repo | We use the standard-library `ast` with import-table resolution, keep a signature hash per symbol, and re-index one file per edit inside a hook |
| CodeGraphContext (MIT) | `CONTAINS`/`CALLS`/`INHERITS` schema shape | We add agents, tasks, leases and contract changes to the same graph |
| Claim Plane (arXiv 2607.21909) | Admission before write, fencing tokens, dynamic scope promotion | Scope comes from the graph (impact cones), not from agents declaring resources. Edits outside the plan auto-claim if free. |
| Passes Alone, Fails Together (arXiv 2609.25396) | The merged-versus-alone grading method, broadcast baseline | Phase 3 benchmark against graph-targeted briefings |
| Graphiti (Apache-2.0) | Facts with time, never deleting history | Contract changes and collisions are append-only nodes; Phase 2 hot-zone memory reads them |

---

## Phase 1 file structure

```
server/
  pyproject.toml                       # Task 1: deps (pytest), script entry point
  src/airspace/
    config.py                          # Task 1: settings from env
    types.py                           # Task 1: shared dataclasses (the contract between modules)
    graph/db.py                        # Task 1: connect, repo_graph, ensure_schema
    indexer/parse.py                   # Task 2: ast -> ModuleFacts
    indexer/resolve.py                 # Task 2: raw call names -> qualnames
    indexer/writer.py                  # Task 2: ModuleFacts -> graph; index_repo; reindex_file
    admission/engine.py                # Task 3: Airspace class (plans, cones, clearance, briefings)
    admission/text.py                  # Task 3: hold and briefing messages
    hooks/edit_analysis.py             # Task 4: Claude Code tool_input -> EditAnalysis
    hooks/handlers.py                  # Task 4: pre/post hook logic, JSON in and out
    cli.py                             # Task 4: airspace index | hook pre | hook post | install-hooks | status
  tests/
    conftest.py                        # Task 1: FalkorDB fixture, fixture repo path
    fixtures/blog/...                  # Task 1: the Django-like repo from the website story
    helpers.py                         # Task 1: seed_blog_graph(graph) via Cypher (no indexer needed)
    test_db.py                         # Task 1
    test_parse.py test_resolve.py test_writer.py   # Task 2
    test_engine.py                     # Task 3
    test_edit_analysis.py test_hooks.py test_cli.py  # Task 4
    test_e2e.py                        # Task 5
```

Ownership is disjoint. Tasks 2, 3 and 4 run **in parallel** after Task 1 lands, each in its own git worktree, and only touch their own files. Task 5 runs after all three are merged.

---

### Task 1: Foundation (shared types, DB layer, fixture repo, test harness)

Done by the lead before the fan-out. It defines the interfaces every other task codes against.

**Files:** `server/pyproject.toml`, `src/airspace/{config,types}.py`, `src/airspace/graph/db.py`, `tests/{conftest,helpers,test_db}.py`, `tests/fixtures/blog/**`.

**Interfaces produced:**

```python
# airspace/types.py
SymbolKind = Literal["function", "method", "class"]

@dataclass(frozen=True)
class SymbolFact:
    qualname: str          # "utils.text.slugify", "blog.models.Post.save"
    name: str              # "slugify", "save"
    kind: SymbolKind
    file: str              # repo-relative POSIX path, "utils/text.py"
    lineno: int
    end_lineno: int
    signature: str         # "slugify(value, *, unicode=False)" (no 'def', no annotations' quotes changes)
    sig_hash: str          # sha1(signature)[:12]
    is_test: bool          # file under tests/ or name starts with "test_"

@dataclass(frozen=True)
class CallFact:
    caller: str            # qualname of the enclosing function or method
    target: str            # dotted name as written: "slugify", "text.slugify", "self.save", "Post"
    lineno: int

@dataclass
class ModuleFacts:
    module: str            # "utils.text"
    file: str              # "utils/text.py"
    symbols: list[SymbolFact]
    calls: list[CallFact]
    imports: dict[str, str]          # local name -> dotted target ("slugify" -> "utils.text.slugify", "text" -> "utils.text")
    bases: list[tuple[str, str]]     # (class qualname, base name as written)

@dataclass(frozen=True)
class SignatureChange:
    qualname: str
    old_signature: str
    new_signature: str

@dataclass(frozen=True)
class Briefing:
    id: str
    symbol: str            # qualname
    old_signature: str
    new_signature: str
    from_agent: str

VerdictKind = Literal["cleared", "hold"]

@dataclass
class Verdict:
    kind: VerdictKind
    reason: str                              # factual text shown to the agent
    path: list[str] = field(default_factory=list)          # qualnames, dependent -> dependency
    other_agent: str | None = None
    collision_id: str | None = None
    briefings: list[Briefing] = field(default_factory=list)

@dataclass
class EditAnalysis:
    file: str                  # repo-relative
    touched: list[str]         # qualnames whose body the edit changes (in the new source)
    new_calls: list[tuple[str, str]]   # (caller qualname, resolved callee qualname) added by the edit
    parse_ok: bool
```

```python
# airspace/graph/db.py
def connect(host: str | None = None, port: int | None = None) -> FalkorDB
def graph_name(repo_root: str | Path) -> str          # "airspace_" + sha1(realpath)[:12]
def repo_graph(db: FalkorDB, repo_root: str | Path) -> Graph
def ensure_schema(graph: Graph) -> None               # idempotent range indexes
```

```python
# tests/helpers.py
def seed_blog_graph(graph) -> None   # writes the fixture repo's code graph directly with Cypher
```

The fixture repo, `tests/fixtures/blog`, mirrors the website story:
- `utils/text.py` defines `slugify(value, allow_unicode=False)` and `truncate_words`.
- `blog/models.py` defines `Post.save` (calls slugify) and `Post.get_absolute_url`.
- `blog/views.py` defines `render_post` (calls `get_absolute_url`) and `post_list` (calls render_post).
- `blog/feeds.py` defines `LatestPosts.item_description` (calls render_post and truncate_words).
- `tags/models.py` defines `Tag.save` (calls slugify).
- `tags/views.py` defines `tag_create` (calls `Tag.save` via `Tag(...).save()`).
- `tests/test_text.py`, `tests/test_models.py` and `tests/test_views.py` hold the tests.

- [x] Write `tests/test_db.py`:
  - `graph_name` is stable and starts with `airspace_`;
  - `ensure_schema` can run twice;
  - `seed_blog_graph` creates 17 `Symbol` nodes and `CALLS` from `blog.models.Post.save` to `utils.text.slugify`.
- [x] Implement until green: `cd server && uv run pytest tests/test_db.py -q`.
- [x] Commit `Phase 1 foundation: types, db layer, fixture repo, test harness`.

---

### Task 2: Indexer (parallel agent A)

**Files:** create `indexer/parse.py`, `indexer/resolve.py`, `indexer/writer.py`, `tests/test_parse.py`, `tests/test_resolve.py`, `tests/test_writer.py`. Touch nothing else.

**Interfaces:**
- Consumes: `types.SymbolFact, CallFact, ModuleFacts, SignatureChange`; `graph.db.ensure_schema`.
- Produces:

```python
# indexer/parse.py
def module_name(rel_path: str) -> str                         # "blog/views.py" -> "blog.views"; "pkg/__init__.py" -> "pkg"
def parse_module(rel_path: str, source: str) -> ModuleFacts | None   # None on SyntaxError

# indexer/resolve.py
def resolve_target(target: str, facts: ModuleFacts, caller: str, known: set[str]) -> str | None
def resolve_calls(facts: ModuleFacts, known: set[str]) -> list[tuple[str, str]]   # (caller, callee) qualnames, deduped

# indexer/writer.py
@dataclass
class IndexStats: files: int; symbols: int; calls: int; unresolved: int
def index_repo(graph, repo_root: Path) -> IndexStats
def reindex_file(graph, repo_root: Path, rel_path: str) -> list[SignatureChange]
def known_qualnames(graph) -> set[str]
```

**Rules:**

*Parsing:*
- Functions, async functions, classes and methods (one nesting level) become symbols.
- The signature is `f"{name}({ast.unparse(node.args)})"`.
- Call targets are the dotted text of `ast.Call.func` (`Name`, or `Attribute` chains rooted at a `Name`).
- For `Tag(...).save()`, record `Tag` and `Tag.save`.
- Imports: `from utils.text import slugify` maps to `slugify -> utils.text.slugify`. `import utils.text as text` maps to `text -> utils.text`. Relative imports resolve against the module's package.

*Resolution order:*
1. `self.x`/`cls.x` → `<caller class>.x`
2. A local module-level name → `<module>.name`
3. An imported alias, expanded
4. An exact match in `known`

Return `None` otherwise. That counts as unresolved and is never guessed.

*Writer:*
- `MERGE` `File`, `Symbol`, `DEFINES`, `CALLS` (or `COVERS` when the caller `is_test`) and `INHERITS`, all idempotent.
- `reindex_file` deletes the file's old symbols that no longer exist (`DETACH DELETE`) and rewrites its edges.
- It returns a `SignatureChange` for every symbol whose `sig_hash` changed.

- [ ] **Tests (write first):**
  - `test_parse_slugify_signature`: the fixture `utils/text.py` gives `signature == "slugify(value, allow_unicode=False)"`.
  - `test_parse_syntax_error_returns_none`.
  - `test_parse_records_calls_and_imports`: `blog/views.py` imports and calls are recorded.
  - `test_resolve_imported_function`: `slugify` → `utils.text.slugify`.
  - `test_resolve_self_method`.
  - `test_resolve_unknown_returns_none`.
  - `test_index_repo_counts`: 12 symbols, and `CALLS` from `blog.models.Post.save` to `utils.text.slugify`.
  - `test_index_repo_is_idempotent`: running it twice gives the same counts.
  - `test_reindex_detects_signature_change`: write a temp copy of the fixture, change the `slugify` signature, call `reindex_file`, and get one `SignatureChange` with the new signature `slugify(value, *, unicode=False)`.
  - `test_reindex_removes_deleted_symbol`.
- [ ] Implement until `uv run pytest tests/test_parse.py tests/test_resolve.py tests/test_writer.py -q` is green.
- [ ] Commit `Indexer: ast parse, import resolution, idempotent writer, signature changes`.

---

### Task 3: Admission engine (parallel agent B)

**Files:** create `admission/engine.py`, `admission/text.py`, `tests/test_engine.py`. Touch nothing else. Use `tests/helpers.seed_blog_graph` for the code graph; do not import the indexer.

**Interfaces:**
- Consumes: `types.*`; `graph.db.ensure_schema`.
- Produces:

```python
class Airspace:
    def __init__(self, graph, lease_seconds: int = 900, cone_depth: int = 2, clock: Callable[[], float] = time.time): ...
    def ensure_task(self, agent_id: str, task_id: str, intent: str = "") -> None
    def claim(self, task_id: str, qualnames: list[str]) -> list[str]           # returns the qualnames now held by this task
    def file_plan(self, agent_id: str, task_id: str, intent: str, qualnames: list[str]) -> list[str]  # ensure_task + claim + refresh_cone; returns cone qualnames
    def refresh_cone(self, task_id: str) -> list[str]
    def check_edit(self, task_id: str, touched: list[str], new_calls: list[tuple[str, str]]) -> Verdict
    def record_changes(self, task_id: str, changes: list[SignatureChange]) -> list[str]   # ContractChange ids
    def pending_briefings(self, task_id: str) -> list[Briefing]        # not yet delivered; marks them delivered
    def explain(self, from_q: str, to_q: str) -> list[str]
    def release(self, task_id: str) -> None
    def agent_of(self, task_id: str) -> str | None
```

**Clearance rules, in order (deterministic):**
1. For each `(caller, callee)` in `new_calls`: if some **other** active task has an undelivered-to-me `ContractChange` `ON` `callee`:
   - return **hold**;
   - include the briefing (old and new signature) and `path = [caller, callee]`;
   - mark that briefing delivered to me;
   - write a `Collision` (`BETWEEN` both tasks, `AT` callee).
2. For each `touched` symbol: if another active task holds a live claim (`lease_until > now`) on it, return **hold** with `path = [symbol]` and a `Collision`.
3. Otherwise **cleared**: claim (dynamic scope) every touched symbol not held by others, renew own leases, and `refresh_cone`.

A `ContractChange` that was already delivered to me never holds me again. That's "brief, don't surprise": the retry after a briefing is cleared.

**Lease query (verified to work on FalkorDB):**

```cypher
MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
OPTIONAL MATCH (o:Task)-[c:CLAIMS]->(s) WHERE o.id <> $task AND c.lease_until > $now
WITH t, s, count(c) AS held
WHERE held = 0
MERGE (t)-[k:CLAIMS]->(s)
SET k.lease_until = $now + $ttl, k.fence = coalesce(k.fence, 0) + 1
RETURN k.fence
```

**Cone:**

```cypher
MATCH (t:Task {id: $task})-[:CLAIMS]->(s:Symbol)
MATCH (d:Symbol)-[:CALLS|COVERS|INHERITS*1..2]->(s)
MERGE (t)-[:CONE]->(d)
```

Clear the old cone first.

**Explain path:**

```cypher
MATCH (a:Symbol {qualname: $a}), (b:Symbol {qualname: $b})
WITH shortestPath((a)-[:CALLS|COVERS|INHERITS*..6]->(b)) AS p
RETURN [n IN nodes(p) | n.qualname]
```

Return `[]` when there is no path.

**Hold text** (`admission/text.py`) is factual, for example:

> Airspace hold: utils.text.slugify is being changed by agent-a. New signature: slugify(value, *, unicode=False) (was slugify(value, allow_unicode=False)). This edit adds a call to it from blog.views.render_post. Path: blog.views.render_post -> utils.text.slugify. A retry with a call that matches the new signature will be cleared.

- [ ] **Tests (write first)**, each on a fresh seeded graph:
  - `test_file_plan_builds_cone`: claiming `slugify` gives a cone containing `blog.models.Post.save`, `tags.models.Tag.save`, `tests.test_text.test_slugify`, `tests.test_models.test_post_save` and `tags.views.tag_create`.
  - `test_own_claim_is_cleared_and_renewed`: the fence goes from 1 to 2, and there is exactly one CLAIMS edge.
  - `test_other_live_claim_holds`.
  - `test_expired_claim_does_not_hold`: inject the clock.
  - `test_new_call_into_changed_contract_holds_then_clears`:
    - agent-a's task claims `slugify` and records `SignatureChange`;
    - agent-b's `check_edit(new_calls=[("blog.views.render_post","utils.text.slugify")])` is a hold with a briefing and path;
    - the same call again is cleared.
  - `test_collision_node_written_on_hold`.
  - `test_explain_returns_path_and_empty_when_none`.
  - `test_pending_briefings_for_dependents`: after agent-a changes `slugify`, a task whose cone contains `blog.models.Post.save` gets one pending briefing, then zero.
  - `test_release_frees_claims`.
- [ ] Implement until `uv run pytest tests/test_engine.py -q` is green.
- [ ] Commit `Admission engine: leases, cones, deterministic clearance, briefings, collisions`.

---

### Task 4: Hooks and CLI (parallel agent C)

**Files:** create `hooks/edit_analysis.py`, `hooks/handlers.py`, `cli.py`, `tests/test_edit_analysis.py`, `tests/test_hooks.py`, `tests/test_cli.py`. Add `[project.scripts] airspace = "airspace.cli:main"` to `pyproject.toml`; this is the only shared-file edit.

**Interfaces:**
- Consumes the exact signatures from Tasks 2 and 3 above. While those land in parallel, code against them as written. In unit tests, use small fakes (a `FakeAirspace` with `check_edit`/`record_changes`/`pending_briefings`, and a `parse_module` stub only where needed). The real wiring is proven in Task 5.
- Produces:

```python
# hooks/edit_analysis.py
def apply_tool_input(tool_name: str, tool_input: dict, current: str | None) -> str | None   # new file content; None if not applicable
def analyze_edit(repo_root: Path, tool_name: str, tool_input: dict, known: set[str]) -> EditAnalysis | None

# hooks/handlers.py
def handle_pre(payload: dict, *, airspace_factory, known_loader) -> dict | None   # JSON to print, or None (allow silently)
def handle_post(payload: dict, *, airspace_factory, reindex) -> dict | None

# cli.py
def main(argv: list[str] | None = None) -> int
```

**Claude Code contract** (verified from code.claude.com/docs/en/hooks):
- stdin JSON has `session_id`, `cwd`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`.
- `tool_input` shapes:
  - `Edit`: `{file_path, old_string, new_string, replace_all?}`
  - `Write`: `{file_path, content}`
  - `MultiEdit`: `{file_path, edits: [{old_string, new_string, replace_all?}]}`
- To block, print `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<factual text>"}}` and exit 0.
- To inform, print `{"hookSpecificOutput": {"hookEventName": "PostToolUse" | "PreToolUse", "additionalContext": "<text>"}}`.
- Exit 0 with no output means no decision.

**Behaviour:**
- **Identity:**
  - `task_id` is the `session_id`.
  - `agent_id` is env `AIRSPACE_AGENT`, or else `agent-` plus the first 4 characters of `session_id`.
  - `repo_root` is env `CLAUDE_PROJECT_DIR`, or else `cwd`.
- **pre:**
  - Ignore non-`.py` files: return None.
  - `analyze_edit` computes old and new content, parses both, diffs the line ranges, and sets `touched` to symbols in the new source overlapping changed lines.
  - `new_calls` are resolved calls inside touched symbols that are absent from the old source.
  - If the parse fails, or the file is new or unknown, return None (cleared).
  - Otherwise call `airspace.ensure_task` then `check_edit`.
  - On hold, return the deny JSON with `verdict.reason`.
  - On cleared, if `pending_briefings` is non-empty, return additionalContext with the briefing text.
- **post:** call `reindex(file)` to get changes, then `record_changes`. Return additionalContext summarising pending briefings for this task (if any).
- **Fail open:** any exception connecting to FalkorDB prints one line to stderr (`airspace: FalkorDB unavailable, edit not checked`) and returns None.
- **CLI:**
  - `airspace index [--root DIR]` prints `IndexStats`.
  - `airspace hook pre|post` reads stdin and prints JSON.
  - `airspace install-hooks [--root DIR]` merges into `.claude/settings.json` without deleting existing hooks:
    - matcher `Edit|Write|MultiEdit`;
    - commands `airspace hook pre` and `airspace hook post`.
  - `airspace status [--root DIR]` prints active tasks, claims and the last 10 collisions.

- [ ] **Tests (write first):**
  - `test_apply_edit_replaces_first_occurrence`
  - `test_apply_multiedit_sequential`
  - `test_apply_write_returns_content`
  - `test_analyze_edit_finds_touched_and_new_call` (fixture repo copy, edit `render_post` to add `slugify(post.title, True)`, known includes `utils.text.slugify`)
  - `test_pre_hook_ignores_non_python`
  - `test_pre_hook_new_file_is_cleared`
  - `test_pre_hook_syntax_error_is_cleared`
  - `test_pre_hook_hold_prints_deny_json` (FakeAirspace returns hold)
  - `test_pre_hook_fails_open_when_db_down` (factory raises ConnectionError: returns None, stderr note)
  - `test_post_hook_records_changes`
  - `test_install_hooks_merges_existing_settings` (keeps an existing unrelated hook)
  - `test_cli_hook_pre_roundtrip` (subprocess with stdin JSON and a fake via env `AIRSPACE_FAKE=hold`, which is test-only)
- [ ] Implement until `uv run pytest tests/test_edit_analysis.py tests/test_hooks.py tests/test_cli.py -q` is green.
- [ ] Commit `Claude Code hooks and CLI: edit analysis, pre/post handlers, install-hooks`.

---

### Task 5: Integration and end-to-end proof (lead, after merging 2, 3, 4)

**Files:** `tests/test_e2e.py`, wiring fixes only where interfaces drifted, README "Running locally".

- [ ] Write `test_e2e.py`:
  - Copy the fixture repo to `tmp_path` and run `airspace index`.
  - **agent-a**: send a pre hook (Edit `utils/text.py` changing the slugify signature); expect no output (cleared). Apply the edit to disk, then send a post hook; one ContractChange is recorded.
  - **agent-b**: send a pre hook (Edit `blog/views.py` adding `slug = slugify(post.title, True)` in `render_post`). Expect deny JSON whose reason contains `utils.text.slugify`, `agent-a` and `slugify(value, *, unicode=False)`.
  - **agent-b**: send the same pre hook again with `slugify(post.title, unicode=True)`; expect cleared.
  - `airspace status` lists one collision.
- [ ] Run the whole suite: `uv run pytest -q`. All tests pass.
- [ ] Manual check in a real Claude Code session on the fixture repo, with two sessions and `install-hooks`. Record the outcome in the commit message.
- [ ] Commit `Phase 1 complete: end-to-end hold, brief, clear through the real hooks`.

---

## Phase 2 outline (own plan, written when Phase 1 is green)

1. **API:** FastAPI `airspace serve`:
   - `GET /api/agents`, `/api/tasks`, `/api/collisions/{id}`, `/api/graph` (radar subgraph);
   - `POST /api/actions/{release|pause|message|approve}`;
   - SSE `/api/events`, driven by an `Event` node log in FalkorDB.
2. **Controller actions in the graph:** `Pause` (task property), `Message` (`Briefing` from controller) and `Approve` (a gate on ContractChange). The hooks read them, so Tower decisions are enforced on the next tool call.
3. **MCP server** (`mcp` FastMCP): `file_flight_plan`, `request_clearance`, `report_change`, `briefings`, `radar`.
4. **Memory:**
   - Hot zones: `Collision` counts plus `algo.betweenness` on the call graph.
   - Parallel groups: `algo.WCC` over the task conflict graph.
   - `airspace plan-split` suggests task groupings.
5. **Tower web app** (`web/`, routes `/tower`, `/tower/collisions/:id`):
   - the real `Scope` fed from `/api/graph`;
   - agents, activity, collision detail, actions;
   - the marketing site stays at `/`.
6. **Tests:** API contract tests and action enforcement tests through the hooks.

## Phase 3 outline (own plan)

1. **Benchmark:**
   - Constructed task sets on the fixture repo plus one real library; 3 conditions × N sets.
   - Grading: merged versus alone.
   - Claude Code headless (`claude -p`) per agent, in worktrees.
   - Results JSON, then README table and site Results section.
2. **Replay:** record events from a real run; `airspace replay` loads them into a graph for the live demo.
3. **Playground:** a `/playground` page plus `POST /api/playground/check`, which runs real clearance on the indexed fixture repo with no agents.
4. **Deploy:** Docker Compose (FalkorDB, API, web) on the VPS, behind HTTPS.
5. **Submission:**
   - demo video (script in `docs/notes.md`);
   - blog post;
   - README final pass (graph model, Cypher, AI disclosure);
   - make the repo public;
   - submit both tracks.
