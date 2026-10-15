"""One step of the local video run, sent through Airspace's real Claude Code hooks.

    uv run --project server python video/capture/session.py <repo> <step> [<step> ...]

The repo is a copy of the blog fixture connected to a local workspace (`airspace connect`, with AIRSPACE_CONFIG_DIR
pointing at video/.stack-data/config), so every hook call goes over RPC into that workspace's graph, exactly as a
connected Claude Code session's hooks do. The edits are the benchmark's reference edits for slugify-keyword-only
(server/tests/bench_refs.py), the same calls the real agents wrote. Each hook answer is appended to
video/.stack-data/hooks.json, which the composition reads for the agent terminals.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "tests"))

from bench_refs import REFS, Agent  # noqa: E402

from airspace.hooks.handlers import default_deps  # noqa: E402

LOG = ROOT / "video" / ".stack-data" / "hooks.json"

SLUG_A, SLUG_B = REFS["slugify-keyword-only"]
FIXED = "slugify(post.title, unicode=True)"
B_RETRY = {"file_path": "blog/views.py", "old_string": "<article>", "new_string": f'<article data-slug="{{{FIXED}}}">'}
C_CALL = {"file_path": "blog/views.py", "old_string": 'return "\\n".join(render_post(p) for p in posts)',
          "new_string": 'return "\\n".join(f\'<li id="{slugify(p.title)}">{render_post(p)}</li>\' for p in posts)'}

PROMPT_A = ("In utils/text.py, make the unicode option of slugify keyword-only and rename it, so the signature is "
            "exactly slugify(value, *, unicode=False). Update the body and every caller.")
PROMPT_B = ("In blog/views.py, make render_post add a data-slug attribute to the article tag, built as "
            "slugify(post.title, allow_unicode=True).")
PROMPT_C = "Make post_list in blog/views.py link each post by its slug."


def log(step: str, agent: str, kind: str, out) -> None:
    rows = json.loads(LOG.read_text()) if LOG.exists() else []
    rows.append({"at": time.time(), "step": step, "agent": agent, "kind": kind, "out": out})
    LOG.write_text(json.dumps(rows, indent=1))


def main() -> None:
    repo = Path(sys.argv[1]).resolve()
    deps = default_deps()
    a = Agent(repo, "agent-a", "video-a1", deps)
    b = Agent(repo, "agent-b", "video-b1", deps)
    c = Agent(repo, "agent-c", "video-c2", deps)
    never = lambda _s: None  # noqa: E731

    for step in sys.argv[2:]:
        if step == "a-start":
            log(step, "agent-a", "prompt", a.prompt(PROMPT_A))
            for rel, tool, ti in __import__("bench_refs").tool_calls(SLUG_A):
                out = a.pre(tool, ti)
                log(step, "agent-a", "pre", out)
                a.write(rel, tool, ti)
                log(step, "agent-a", "post", a.post(tool, ti))
        elif step == "b-start":
            log(step, "agent-b", "prompt", b.prompt(PROMPT_B))
            for rel, tool, ti in __import__("bench_refs").tool_calls(SLUG_B):
                out = b.pre(tool, ti)
                log(step, "agent-b", "pre", out)
                if out and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                    break
                b.write(rel, tool, ti)
                log(step, "agent-b", "post", b.post(tool, ti))
        elif step == "a-land":
            log(step, "agent-a", "stop", a.stop(sleep=never))
        elif step == "b-retry":
            out = b.pre("Edit", B_RETRY)
            log(step, "agent-b", "pre", out)
            b.write("blog/views.py", "Edit", B_RETRY)
            log(step, "agent-b", "post", b.post("Edit", B_RETRY))
        elif step == "b-land":
            log(step, "agent-b", "stop", b.stop(sleep=never))
        elif step == "c-start":
            log(step, "agent-c", "prompt", c.prompt(PROMPT_C))
        elif step == "c-edit":
            out = c.pre("Edit", C_CALL)
            log(step, "agent-c", "pre", out)
            c.write("blog/views.py", "Edit", C_CALL)
            log(step, "agent-c", "post", c.post("Edit", C_CALL))
        elif step == "c-land":
            log(step, "agent-c", "stop", c.stop(sleep=never))
        else:
            raise SystemExit(f"unknown step {step}")
        print(step, "done", flush=True)


if __name__ == "__main__":
    main()
