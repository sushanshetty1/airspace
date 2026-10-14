# Passes alone, fails together: air-traffic control for coding agents

Running several coding agents at once is now ordinary. You split a feature, open a few Claude Code sessions, give each a worktree, and let them go. Each one finishes, each one passes its tests, and then the merge is red.

A recent paper, *Passes Alone, Fails Together* (arXiv 2609.25396), measured this. On constructed tasks where two agents work on related code, it found interference in 97% of runs with worktrees alone. Telling each agent what the other was doing helped, but not enough.

The failure is almost always the same shape. Agent A changes a function. Agent B, on its own branch, writes new code that calls the old version. Both are right on their own branch. Together they are wrong.

## The idea

Air-traffic control does not stop planes from flying. It gives each one a piece of sky, watches where they overlap, and holds the one that would collide.

Airspace does that for code:

- **A live code graph.** Every Python file is parsed with the standard library's `ast` into symbols, calls, imports, inheritance and test coverage, and stored in FalkorDB. Each call edge also carries its shape: how many positional arguments, which keywords, whether it unpacks, whether it is called through an instance, and whether its result is used.
- **Claims and cones.** When an agent edits a symbol, its task claims it with a lease. The task's impact cone is everything that depends on what it claims, a couple of hops out.
- **Clearance before every write.** A Claude Code `PreToolUse` hook sends each `Edit`, `Write` and `MultiEdit` to Airspace before the file changes. The edit is analysed against the current file: which symbols it touches, which calls it adds, which signatures it changes.
- **Contracts, not guesses.** When a signature changes, Airspace records the change and checks every known caller against the new signature with Python's own binding rules. A call that cannot bind is a collision. A function that never returns a value carries `-> None` in its contract, so a caller that uses its result breaks too.

No model is asked whether an edit is safe. The decision is a Cypher query and a few rules, so it is fast, it is the same every time, and you can read why it was made.

## What an agent sees

When agent-b writes `slugify(post.title, allow_unicode=True)` after agent-a changed `slugify` to `slugify(value, *, unicode=False)`, its edit is denied with this:

> Airspace hold: utils.text.slugify is being changed by agent-a. New signature: slugify(value, \*, unicode=False) (was slugify(value, allow_unicode=False)). This edit adds a call to it from blog.views.render_post. The call blog.views.render_post makes does not fit the new signature. Path: blog.views.render_post -> utils.text.slugify. A retry whose call matches the new signature will be cleared.

The agent reads it, rewrites the call with `unicode=True`, and is cleared. Nobody had to tell it what to do. It was told what is true.

## The races

The first benchmark run showed Airspace barely better than nothing: 1 of 18 merges green. The clearance logic was right; the timing was wrong. Real agents are fast, and most collisions happened in an order the hooks did not see.

- **The caller lands first.** Agent B finishes and stops before agent A changes the function B calls. There is no next tool call to deliver a briefing to. Airspace now runs a check at Claude Code's `Stop` hook: it reads every call in the files the task edited and checks them against every contract change by another agent. While another agent still holds a claim on something B calls, B waits in a holding pattern, then lands only if its calls fit.
- **The other agent has not started editing yet.** Agent A has read the file but not written to it. Reads now count as soft interest, and so do files a prompt names, so a landing agent waits for them too.
- **The write never goes through the edit tools.** One agent wrote its file with `cat > views.py <<EOF`. No edit hook fired. After every shell command, and again before landing, Airspace now compares the working copy with the version it last saw (git `HEAD` when it has seen none) and treats any difference as an edit.
- **A rename is not a removal.** When a method disappears and exactly one new method with the same parameters appears beside it, the hold names the new one.

## Results on Flask

A small repo proves the mechanism; a real one proves it holds up. On [Flask](https://github.com/pallets/flask) (83 files, 894 symbols), agent A changes part of Flask's public API while agent B adds a feature that uses it: a renamed keyword on `get_flashed_messages`, a renamed `get_debug_flag`, a renamed keyword on `send_file`. Each pair is graded with Flask's own 491 tests plus a hidden test per agent.

| Condition | Merged build green |
| --- | --- |
| Worktrees only | 0 of 9 |
| Broadcast | 5 of 9 |
| Airspace | 9 of 9 |

The first Flask run scored 7 of 9, and the two misses were a real bug. Agents on separate worktrees share one graph. When agent B edited its own copy of `helpers.py`, which never had agent A's rename, re-indexing that file read as B renaming the parameter back, and A was held for a change nobody made. The fix: a re-index only counts changes to symbols the agent's own edits touched, and the graph keeps the newest contract. Both runs are published.

Getting the graph right on a real repo took work too. Flask keeps its code under `src/`, re-exports its public names from `flask/__init__.py`, and puts half of `Flask`'s methods on base classes. Handling those, plus instances made in the same function, took resolved calls from 194 to 845. Indexing all of Flask takes under half a second, and a hook adds about 190 ms to an edit.

## Results on a sample repo

Two real Claude Code agents per pair, at the same time, on the same small repo. Six kinds of contract change, three conditions, three runs each, graded on the merge of both branches with both agents' hidden tests.

| Condition | Merged build green |
| --- | --- |
| Worktrees only | 0 of 18 |
| Broadcast (each agent is told the other's task) | 3 of 18 |
| Airspace | 17 of 18 |

The one miss is worth telling. Agent B was held, understood the hold, wrote nothing wrong, and then stopped to ask whether it should write code that would fail its local tests until the branches were merged. That is a reasonable question. The hold note now says, as a fact, that such a failure goes away at the merge.

Airspace is slower per pair, 43 seconds against 25, because a held agent waits for the change it depends on. That is the trade: a little waiting for a merge that works.

These are constructed tasks on a small repo. The same paper found interference in only 1 of 417 pairs of real merged pull requests. Constructed tasks show that a coordination method works, not how often the problem happens in practice.

## Pre-flight

Holds are the safety net. Pre-flight is the plan. Before any agent starts, you list the tasks and the symbols each will change, and Airspace answers from the graph: which tasks can run in parallel, which must coordinate, and the path between them. Impact cones are Cypher traversals, the explanation is `shortestPath`, the groups are `algo.WCC`, and hot spots are `algo.betweenness`. On Flask, five tasks come back as three groups in about 20 ms: routing and rule registration must coordinate (`Scaffold.route` calls `Scaffold.add_url_rule`), error handlers and error lookup must coordinate (`Flask.handle_user_exception` calls `App._find_error_handler`, across Flask's class hierarchy), and the debug flag task is free. Try it at airspace.sushans.dev/preflight.

## Tower

Agents work in their own terminals. Tower is the web app where you watch them. Each agent's airspace is a circle of the symbols it claims and their callers. When two overlap and one is held, the overlap turns orange. You can pause an agent, send it a message that arrives with its next tool call, or release a hold.

## Why FalkorDB

The questions Airspace asks are graph questions. Who calls this, within two hops? What is the shortest path from this edit to that change? Which symbols collide most, and which sit on the most paths? FalkorDB answers them in Cypher, with shortest paths and betweenness built in, fast enough to run on every edit. Everything lives in one graph per repo: the code, the tasks, the claims, the contract changes and the collisions, so one query can cross all of them.

## Try it

The repo is at github.com/sushanshetty1/airspace. Index a Python repo, install the hooks, and open two Claude Code sessions:

```sh
uv run airspace index --root /path/to/repo
uv run airspace install-hooks --root /path/to/repo
```

Or open the playground on the site, pick a change and a call, and get the verdict and the path without installing anything.
