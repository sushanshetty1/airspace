# Accounts and workspaces: hosted Tower for your own sessions

**Goal:** a developer signs in with GitHub on the hosted site, creates a workspace for a repo, connects that repo's Claude Code hooks to it with a key, and watches their own sessions live in Tower.

**Today:** hooks talk straight to a FalkorDB on the developer's machine. The hosted site shows only the recorded demo.

**After:** the same hooks can talk to the hosted server instead. Parsing and diffing stay on the developer's machine. The server holds the graph and runs the engine.

## Global constraints

- All state lives in FalkorDB (hackathon rule 3). Accounts live in a graph named `airspace_accounts`. Each workspace is its own graph named `ws_<workspace id>`.
- No passwords. Sign-in is GitHub OAuth only. Keys are stored as SHA-256 hashes. A key is shown once.
- Local mode stays exactly as it is. With no remote configured, nothing changes and every existing test passes.
- Copy follows the site's rules: no em or en dashes, sentence case, factual, no hype.
- Commits are authored by the user only. No co-author lines.
- Wire format: `airspace.wire.encode` / `decode` (already on main).

## Contracts

### Environment (server)

| Variable | Meaning |
| --- | --- |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | The GitHub OAuth app. Unset: sign-in routes answer 503 `{"error": "Sign-in is not configured on this server."}` |
| `AIRSPACE_SECRET` | Key for signing session cookies (32+ bytes). Unset: sign-in is not configured. |
| `AIRSPACE_PUBLIC_URL` | e.g. `https://airspace.sushans.dev`. The OAuth callback is `{AIRSPACE_PUBLIC_URL}/auth/github/callback`. |

### Accounts graph `airspace_accounts`

```
(:User {id, github_id, login, name, avatar_url, created_at})
(:User)-[:OWNS]->(:Workspace {id, name, graph, created_at})
(:Workspace)-[:HAS_KEY]->(:Key {hash, prefix, created_at, last_used_at})
```

- Workspace id: 12 lowercase hex characters. Graph: `ws_<id>`.
- A key is `ask_` followed by 40 hex characters. `prefix` is the first 12 characters, for display.
- At most 5 workspaces per user. Each workspace has exactly one live key; rotating replaces it.

### Session

- Cookie `airspace_session`: `<user_id>.<expiry unix>.<hex HMAC-SHA256(AIRSPACE_SECRET, user_id + "." + expiry)>`. Attributes: HttpOnly, Secure (when the public URL is https), SameSite=Lax, Path=/, 30 days.
- OAuth state: cookie `airspace_oauth_state` (random, 10 minutes), compared on callback.
- Every cookie-authenticated POST or DELETE requires the header `X-Airspace: 1`, or it answers 403. This blocks cross-site form posts.

### Routes (server)

| Method and path | Auth | Answer |
| --- | --- | --- |
| `GET /auth/github/login?next=/app` | none | 302 to GitHub authorize (scope `read:user`) |
| `GET /auth/github/callback` | state cookie | Exchanges the code with httpx, upserts the User, sets the session, 302 to `next` (default `/app`; only same-site paths) |
| `POST /auth/logout` | session | Clears the cookie. `{"ok": true}` |
| `GET /api/me` | optional session | `{"user": {"login","name","avatar_url"} or null, "workspaces": [{"id","name","created_at","key_prefix","agents_flying"}], "signin": true or false}`. `signin` says whether sign-in is configured |
| `POST /api/workspaces` `{"name"}` | session | `{"workspace": {...}, "key": "ask_..."}`. Name 1 to 60 chars |
| `POST /api/workspaces/{id}/key` | session, owner | `{"key": "ask_..."}` (the old key stops working) |
| `DELETE /api/workspaces/{id}` | session, owner | Deletes the workspace graph and its records. `{"ok": true}` |
| `/api/w/{id}/...` | session, owner | The same Tower routes as `/api/...`: `state`, `radar`, `events`, `events/stream`, `collisions/{cid}`, `insights`, `agents/{a}/pause`, `agents/{a}/resume`, `agents/{a}/message`, `collisions/{cid}/release`, against the workspace graph. `GET /api/w/{id}/mode` is always `{"mode": "live"}` |
| `POST /api/rpc` | `Authorization: Bearer ask_...` | See below |

Unknown or foreign workspace: 404. No session: 401 `{"error": "Sign in first."}`.

### RPC `POST /api/rpc`

Request: `{"method": "<name>", "args": [...], "kwargs": {...}}`, values in wire form. Answer: 200 `{"ok": true, "result": <wire>}`, or 4xx `{"ok": false, "error": "<text>"}`. Bad key: 401. Over 1200 calls a minute per key: 429. Body over 2 MB: 413.

Engine methods, called on the workspace's `Airspace`: `ensure_task`, `agent_of`, `check_edit`, `record_changes`, `renamed`, `claim_pending`, `claim`, `file_plan`, `release`, `pending_briefings`, `record_edited_file`, `edited_files`, `note_touched`, `started_at`, `stop_check`, `holding`, `land`, `block_landing`, `last_block`, `note_reading`, `note_interest_from_text`, `pending_messages`, `state`, `explain`, `insights`. Anything else: 400.

Graph methods, run on the workspace graph:

- `graph.known` with no args: `known_qualnames(graph) | removed_qualnames(graph)`, as a list.
- `graph.write_file` with args `[rel, facts]`: `facts` is a `ModuleFacts`, or `null` when the file was deleted. Same effect as `reindex_file` for that file. Returns the list of `SignatureChange`.
- `graph.index` with args `[facts_list, reset]`: writes every `ModuleFacts` like `index_repo` does (with `reset` true, the code layer is cleared first). Returns `{"files","symbols","calls","unresolved"}`.

The writer gets `reindex_facts(graph, rel, facts_or_none)` and `index_facts(graph, facts_list)`. `reindex_file` and `index_repo` become thin wrappers that parse from disk and call them.

### Client

- `~/.config/airspace/remotes.json` (mode 600): `{"<realpath of repo root>": {"server": "https://...", "key": "ask_...", "workspace": "<id>"}}`.
- `airspace connect --root R --server URL --key KEY`: checks the key with `graph.known`, stores it, runs a remote index, and prints the Tower URL `{server}/w/{workspace}`. The RPC answer to `graph.known` carries the workspace id in a header `X-Airspace-Workspace`.
- `airspace disconnect --root R` removes the entry.
- `airspace index`, the hooks (`default_deps`) and `airspace status` use the remote when `remotes.json` has the repo, and FalkorDB otherwise.
- `RemoteAirspace` sends engine calls over RPC with short timeouts (connect 3 s, read 15 s). In remote mode, `seen_source` and `note_seen` stay on the developer's machine under `~/.cache/airspace/seen/<sha1 of repo path>/`, so whole files never leave it.
- Hooks fail open in remote mode as in local mode. Server down or bad key: one line on stderr, then the edit goes ahead.

### Web

- Nav: "Sign in" when signed out and sign-in is configured. Signed in: avatar, with a menu holding "Workspaces" and "Sign out".
- `/app`: workspaces (name, key prefix, agents flying, "Open Tower"), a "New workspace" form, and, once, the new key with the commands to run:
  `uv run airspace connect --root ~/your-repo --server https://airspace.sushans.dev --key ask_...` then `uv run airspace install-hooks --root ~/your-repo`.
  Plus a plain statement of what is sent: symbol names, signatures, call shapes and the one-line text of calls, never whole files.
- `/w/:id`: Tower, live, on `/api/w/:id/...`. The Tower code takes an API base instead of hard-coding `/api`.
- Signed out on `/app` or `/w/:id`: a sign-in prompt, not an error.
