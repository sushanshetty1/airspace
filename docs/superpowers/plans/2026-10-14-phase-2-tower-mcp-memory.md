# Phase 2: Tower, MCP, memory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:**
- People watch and steer every agent from Tower (the web app) with real data.
- Agents plan through MCP.
- The graph remembers hot zones and computes safe parallel groups with FalkorDB's built-in algorithms.

**Architecture:**
- The admission engine gains controller state (pause, release, message), an append-only `Event` log and read models (`state`, `radar`, `collision`, `insights`). All of it lives in FalkorDB.
- A FastAPI server (`airspace serve`) exposes those read models, actions and a server-sent-events stream.
- An MCP server (`airspace mcp`) exposes planning tools.
- Tower in `web/` renders the live state at `/tower`, using the same visual language as the marketing site.

**Tech stack:** Python 3.12, FalkorDB 6.x, FastAPI, uvicorn, `mcp` (FastMCP), React 19, Vite, Tailwind v4, motion.

**Spec:** `README.md`, `docs/notes.md`, `docs/superpowers/plans/2026-10-14-airspace-three-phases.md` (Phase 2 outline), and this file's contracts.

## Global Constraints

- Everything lives in FalkorDB: controller state, events, messages, passes. There is no side store (hackathon rule 3).
- Clearance stays deterministic: no model calls in the engine, hooks, API or MCP.
- FalkorDB quirks:
  - `shortestPath` appears only in `WITH` or `RETURN`.
  - A `MATCH` after `WITH ... count()` loses rows, so match every node before aggregating.
- Hook and MCP text is factual, never imperative.
- There are no em or en dashes in user-facing strings.
- The web follows `memory: design-no-ai-tells`:
  - Schibsted Grotesk, sentence case, mono only for code.
  - No uppercase letter-spaced labels and no figure captions.
- Commits are authored by the repo owner only. No Co-Authored-By or AI attribution.
- Tests use the `graph` fixture: a unique graph per test on the shared FalkorDB.

## Review Focus

1. **Several tasks for one agent.** The hooks use the Claude session id and MCP uses `<agent>:mcp`. An agent must never collide with itself. *Owner: engine; test `test_same_agent_tasks_never_collide`.*
2. **Tower acting on an agent that has already finished**, for example pausing a released agent. *Expected: a 200 with no effect, not a 500. Owner: API; test `test_pause_unknown_or_released_agent_is_noop`.*
3. **No agents flying** (an empty graph). *Expected: `/api/state` and `/api/radar` return empty lists, and Tower shows an empty state with the install command. Owners: API and web.*
4. **The SSE client reconnecting.** *Expected: no duplicated events, because events are fetched with `since`. Owner: web; covered by using `since=lastEventAt`.*
5. **A message sent while the agent's edit is held.** *Expected: the message reaches the agent within the same deny reason, not only on a later cleared edit. Owner: engine and handlers; test `test_message_is_included_in_hold_reason`.*

---

## Contracts (fixed before the fan-out)

### Engine additions (`admission/engine.py`, owner P)

- **Agents are the unit of conflict.** "Another task" now means a task whose agent differs. An agent's own tasks never collide.
- **Controls are per agent:**

```python
def pause(self, agent_id: str) -> None
def resume(self, agent_id: str) -> None
def message(self, agent_id: str, text: str, sender: str = "Tower") -> str      # Message id
def pending_messages(self, agent_id: str) -> list[str]                          # undelivered text, marks delivered
def release_collision(self, collision_id: str) -> bool                          # False if unknown or not held
def events(self, since: float = 0.0, limit: int = 200) -> list[dict]           # ascending by at
def state(self) -> dict
def radar(self) -> dict
def collision(self, collision_id: str) -> dict | None
def insights(self) -> dict
```

**Graph additions:**
- `(:Agent {id, paused: bool})`
- `(:Message {id, text, sender, at})-[:TO]->(:Agent)`
- Delivery: `(:Message)-[:DELIVERED {at}]->(:Task)`
- `(:Task)-[:PASS {until}]->(:Symbol)`: a one-time pass created by releasing a claim collision.
- `(:Event {id, at, kind, agent, task, text, code})`, with kind one of `plan | cleared | hold | briefed | contract | paused | resumed | released | message | resolved`.
- `Collision` gains:
  - `held_agent`, `held_task`, `owner_agent`, `owner_task`, `symbol`, `caller`;
  - `old_sig` and `new_sig` (contract collisions only);
  - `resolution`: `held | released | resolved`.

**Rules added to `check_edit`:**
- A paused agent is held with *"Airspace hold: agent-x is paused from Tower. Its edits are held until it is resumed."*
- An unexpired PASS on a touched symbol skips the claim rule once, and is deleted when used.
- When a check is cleared, any of this task's collisions with resolution `held` whose symbol is now among its touched symbols or new-call callees become `resolved`, and a `resolved` event is written.
- Every verdict writes an Event: `cleared` (only when something was touched), `hold`, and `briefed` when a briefing is delivered by a hold.
- A first claim on a task writes `plan`, and `record_changes` writes `contract`.

**`events` text examples** (the web shows them as "`<agent>` `<text>` `<code>`"):

| kind | text | code |
|---|---|---|
| plan | `filed a plan for` | `utils.text.slugify` |
| cleared | `was cleared to edit` | `utils.text.slugify` |
| contract | `changed the signature of` | `utils.text.slugify` |
| hold | `was held editing` | `blog.views.render_post` |
| briefed | `got the new signature of` | `utils.text.slugify` |
| paused | `was paused from` | `Tower` |
| resumed | `was resumed from` | `Tower` |
| released | `had a hold released at` | `utils.text.slugify` |
| message | `got a message from` | `Tower` |
| resolved | `cleared the collision at` | `utils.text.slugify` |

### Read-model JSON (returned by the engine; the API serves them verbatim)

```jsonc
// state()
{ "now": 1791958771.6,
  "agents": [ { "id": "agent-a", "paused": false, "status": "active", "tasks": ["<task id>"],
                "claims": ["utils.text.slugify"], "held": false } ],   // held: has an open (resolution=held) collision as held_agent
  "collisions": [ { "id": "…", "at": 1791958700.1, "kind": "contract", "symbol": "utils.text.slugify",
                    "held_agent": "agent-b", "owner_agent": "agent-a", "resolution": "held" } ] }   // newest first, max 20

// radar(): at most the 4 most recently active agents
{ "agents": [ { "id": "agent-a", "center": "utils.text.slugify", "claims": ["utils.text.slugify"],
                "cone": [ { "qualname": "blog.models.Post.save", "hop": 1 } ] } ],
  "symbols": { "utils.text.slugify": { "label": "slugify", "kind": "function", "is_test": false } },
  "edges": [ ["blog.models.Post.save", "utils.text.slugify"] ],        // CALLS|COVERS|INHERITS among listed symbols
  "collision": { "id": "…", "symbol": "utils.text.slugify", "caller": "blog.views.render_post",
                 "held_agent": "agent-b", "owner_agent": "agent-a", "resolution": "held" } }   // newest open or most recent, or null

// collision(id)
{ "id": "…", "at": 1791958700.1, "kind": "contract", "symbol": "utils.text.slugify", "caller": "blog.views.render_post",
  "path": ["blog.views.render_post", "utils.text.slugify"], "held_agent": "agent-b", "held_task": "…",
  "owner_agent": "agent-a", "owner_task": "…", "old_sig": "slugify(value, allow_unicode=False)",
  "new_sig": "slugify(value, *, unicode=False)", "resolution": "held" }

// insights()
{ "hot_zones": [ { "qualname": "utils.text.slugify", "collisions": 3, "betweenness": 2.0 } ],   // top 10
  "parallel_groups": [ { "agents": ["agent-a", "agent-b"], "conflict": true }, { "agents": ["agent-c"], "conflict": false } ] }
```

- `hot_zones` combines Collision counts with `algo.betweenness` over `Symbol` / `CALLS`.
- `parallel_groups` comes from `algo.WCC` over `(:Agent)-[:CONFLICTS]->(:Agent)`. The engine writes a CONFLICTS edge between agents whose live claims or cones overlap, or who have an open collision.

### HTTP API (`api/app.py`, owner Q; default port 8787)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/state` | | `state()` |
| GET | `/api/radar` | | `radar()` |
| GET | `/api/events?since=<float>` | | `{"events": [...]}` |
| GET | `/api/events/stream?since=<float>` | | SSE: `event: airspace` with a `data:` line holding one event JSON. The server polls the graph every 500 ms and sends a `: ping` comment every 15 s. |
| GET | `/api/collisions/{id}` | | `collision()` or 404 `{"error": "not found"}` |
| GET | `/api/insights` | | `insights()` |
| POST | `/api/agents/{agent}/pause` | | `{"ok": true}` |
| POST | `/api/agents/{agent}/resume` | | `{"ok": true}` |
| POST | `/api/agents/{agent}/message` | `{"text": str}` (1 to 500 characters) | `{"ok": true, "id": "…"}` |
| POST | `/api/collisions/{id}/release` | | `{"ok": bool}` |

CORS is allowed for `http://localhost:4173`.

### MCP (`mcp_server/server.py`, owner Q)

`airspace mcp --root DIR` uses stdio. The agent comes from `AIRSPACE_AGENT`, and the task is `<agent>:mcp`. Tools:
- `file_flight_plan(symbols: list[str], intent: str)`: cone qualnames plus a one-line summary.
- `check_symbols(symbols: list[str])`: for each symbol, whether another agent claims it or is changing its contract.
- `briefings()`: pending briefings and messages for this agent.
- `explain(from_symbol, to_symbol)`: the path.
- `hot_zones()`: the `insights` hot zones.

### CLI additions (owner Q)

- `airspace serve --root DIR [--port 8787]`
- `airspace mcp --root DIR`
- `airspace insights --root DIR`

### Hooks (owner P)

`handlers.py` adds `airspace.pending_messages(agent)`:
- On a hold, its text is appended to the deny reason.
- On a cleared check and in the post hook, it goes into `additionalContext`, joined with any briefings.

---

## Tasks

### Task P: Engine controls, events, read models, memory, hook messages

**Files:** `admission/engine.py`, `admission/text.py`, `admission/insights.py` (new), `hooks/handlers.py`, `tests/test_engine.py`, `tests/test_controls.py` (new), `tests/test_read_models.py` (new), `tests/test_insights.py` (new), `tests/test_hooks.py`.

- [ ] Write the tests first:
  - `test_same_agent_tasks_never_collide`
  - `test_pause_holds_and_resume_clears`
  - `test_message_is_included_in_hold_reason`
  - `test_message_delivered_once_on_cleared`
  - `test_release_contract_collision_clears_retry`
  - `test_release_claim_collision_grants_one_pass`
  - `test_cleared_retry_resolves_collision`
  - `test_events_written_in_order_with_texts`
  - `test_state_shape`
  - `test_radar_shape_and_hops`
  - `test_collision_detail`
  - `test_insights_hot_zones_use_betweenness_and_collisions`
  - `test_parallel_groups_from_wcc`
  - `test_hooks_include_messages`
- [ ] Implement. Run `uv run pytest -q`; the whole suite stays green.
- [ ] Commit.

### Task Q: HTTP API, SSE, MCP server, CLI

**Files:** `api/app.py`, `api/__init__.py`, `mcp_server/server.py`, `cli.py` (add `serve`, `mcp` and `insights` only), `pyproject.toml` (deps if needed), `tests/test_api.py`, `tests/test_mcp.py`, `tests/test_cli.py` (additions).

The engine additions are being built in parallel. Code against the contract above with a `FakeAirspace` in the tests. `create_app(airspace_factory)` takes a factory so the tests inject fakes.

- [ ] Write the tests first:
  - every route's status code and shape;
  - 404 on an unknown collision;
  - 422 when a message is empty or over 500 characters;
  - `test_pause_unknown_or_released_agent_is_noop`;
  - SSE yields events with `since`, using a fake whose events advance;
  - CORS header present;
  - MCP tools call the right engine methods with agent and task ids (call the tool functions directly);
  - CLI parses `serve` and `mcp`.
- [ ] Implement. Run `uv run pytest -q` green.
- [ ] Commit.

### Task R: Tower in the web app

**Files:**
- `web/src/tower/*` (new);
- `web/src/radar/Scope.tsx` and `graph.ts`: generalise so the scope renders either the marketing demo data or live radar data, with the marketing site visually unchanged;
- `web/src/App.tsx`: route `/tower` and `/tower/collisions/:id` by `location.pathname`, with no router dependency;
- `web/vite.config.ts`: proxy `/api` to `http://localhost:8787`.

**Layout:**
- The Tower app window fills the page: sidebar (agents with status badges and a pause or resume control, then activity from events), the live airspace radar, and a collision panel when one is selected or open.
- Collision panel: the path as a sentence, `agent-a has` / `agent-b wrote` signatures, and actions (Message with a textarea, Release hold, Pause or Resume).
- Live updates: SSE `/api/events/stream?since=`. On each event, refetch `/api/state` and `/api/radar` (debounced 150 ms). Fall back to polling every 3 s if SSE fails.
- **Empty state:** "No agents are flying yet." followed by the commands `airspace index`, `airspace install-hooks`, then "start two Claude Code sessions".
- **Error state:** "Tower cannot reach the Airspace server on :8787." followed by `airspace serve --root .`.
- A `mock.ts` fixture plus `?mock=1` lets Tower render without a server, for development and screenshots.

- [ ] Typecheck and build green. Screenshots of `/tower?mock=1`:
  - desktop, light and dark;
  - phone;
  - empty state and error state.
- [ ] Commit.

### Task S: Integration (lead)

- [ ] Merge P, Q and R. Run the full suite and the web build.
- [ ] Live run on a fixture copy:
  - `airspace serve` plus the web dev server;
  - two real Claude Code sessions;
  - Tower shows agents, the hold, the collision and the path;
  - Message from Tower reaches agent-b;
  - Pause holds agent-a's next edit.
- [ ] Update the README with Tower and MCP instructions. Commit.
