# Demo video script

About three minutes. One screen recording with three panes side by side: agent-a's terminal, agent-b's terminal, and Tower in the browser. Everything shown is a real run; nothing is mocked.

## Before recording

```sh
docker compose up -d falkordb
cd server && uv sync

# A repo with two worktrees, one per agent, sharing one graph.
mkdir -p ~/airspace-demo && cp -R tests/fixtures/blog ~/airspace-demo/repo
cd ~/airspace-demo/repo && git init -q -b main && git add -A && git commit -qm base
git worktree add -q -b agent-a ../agent-a main
git worktree add -q -b agent-b ../agent-b main

export AIRSPACE_GRAPH=airspace_demo
uv run --project <airspace>/server airspace index --root ~/airspace-demo/repo
uv run --project <airspace>/server airspace install-hooks --root ~/airspace-demo/agent-a
uv run --project <airspace>/server airspace install-hooks --root ~/airspace-demo/agent-b
AIRSPACE_GRAPH=airspace_demo uv run --project <airspace>/server airspace serve --root ~/airspace-demo/repo
```

Open Tower at `http://localhost:4173/tower` (`npm run dev` in `web/`). Start each agent in its worktree with `AIRSPACE_GRAPH=airspace_demo` and `AIRSPACE_AGENT=agent-a` or `agent-b`.

Prompts:

- **agent-a:** "In utils/text.py, make the unicode option of slugify keyword-only and rename it, so the signature is exactly slugify(value, \*, unicode=False). Update the body and every caller. Run the tests and make them pass."
- **agent-b** (start it about ten seconds later): "In blog/views.py, make render_post add a data-slug attribute to the article tag, built as slugify(post.title, allow_unicode=True). Run the tests and make them pass."

agent-b's ticket was written against the old API, which is how this happens in real teams.

## Shots

| Time | On screen | Voice |
| --- | --- | --- |
| 0:00 | Two terminals, one feature split in two | "Two Claude Code agents, one feature, each on its own branch. Each will pass its own tests. The question is whether the merge does." |
| 0:12 | The merge from a worktrees-only run: red test output | "Without coordination, this is what we measured: 0 of 18 merges green. One agent changed a function the other was busy calling." |
| 0:25 | Tower, empty radar | "Airspace keeps a live graph of the code in FalkorDB and checks every edit against it before it is written." |
| 0:35 | agent-a edits `slugify`; Tower shows agent-a's airspace with slugify and its callers | "agent-a changes slugify. Airspace records the contract change: the new signature, and every caller in the graph." |
| 0:55 | agent-b's edit is denied in its terminal; the overlap lens on the radar turns orange, Hold | "agent-b writes `slugify(post.title, allow_unicode=True)`. That call no longer fits, so the edit is held. No model is asked. The hold is a graph query and Python's own argument-binding rules." |
| 1:15 | Zoom on the hold text in agent-b's terminal | "The hold gives agent-b the new signature, who is changing it, and the path from its code to the change." |
| 1:30 | agent-b retries with `unicode=True`; Tower shows Cleared and the call edge across both airspaces | "agent-b adapts on its own. The retry fits, so it is cleared, and the collision resolves." |
| 1:45 | Both agents land; merge both branches; tests pass | "Both land. We merge the two branches, and the build is green." |
| 2:00 | FalkorDB Browser: the path query on the code graph | "Everything lives in one FalkorDB graph: symbols, calls with their argument shapes, tasks, claims, contract changes and collisions." |
| 2:20 | The results section of the site: 0, 3 and 17 of 18 | "We ran 54 pairs of real agents. Worktrees: 0 of 18 merges green. Telling each agent the other's task: 3 of 18. Airspace: 17 of 18." |
| 2:40 | The playground on the site | "You can try it without installing anything. Pick a change and a call, and get the verdict and the path." |
| 2:55 | Wordmark | "Airspace. Air-traffic control for coding agents." |

## Notes

- Record at 1440 x 900, dark theme. Tower's replay at `/tower` plays the same run if a live take goes wrong.
- Keep the hold text on screen long enough to read. It is the product.
- Say the numbers exactly as measured. Mention that the tasks are constructed.
