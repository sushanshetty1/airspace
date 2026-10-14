"""Run the benchmark: two real Claude Code agents at once, per task set, under three conditions.

worktrees  each agent on its own branch, no coordination (today's default)
broadcast  each prompt also describes the other agent's task (plan sharing)
airspace   Airspace hooks in both worktrees, sharing one graph through AIRSPACE_GRAPH
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from airspace.bench.grade import Grade, git, grade
from airspace.bench.tasks import TaskSet, load_tasks

CONDITIONS = ("worktrees", "broadcast", "airspace")
FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "blog"
RESULTS = Path(__file__).resolve().parents[3] / "bench" / "results"
AGENT_TIMEOUT = 600


def prompt(task: str, other: str | None, python: str) -> str:
    text = (
        "You are working in a small Python repository.\n\n"
        f"Task: {task}\n\n"
        f"Run the tests with `{python} -m pytest -q -p no:cacheprovider tests` before you finish and make them pass. "
        "Keep the change focused on the task. Do not commit. When you are done, reply with one sentence."
    )
    if other:
        text += f"\n\nAt the same time, another engineer is working in a separate branch of this repository on this task: {other}"
    return text


@dataclass
class AgentRun:
    agent: str
    seconds: float = 0.0
    cost_usd: float = 0.0
    turns: int = 0
    result: str = ""
    error: str = ""


@dataclass
class PairResult:
    set_id: str
    kind: str
    condition: str
    outcome: str
    a_alone: bool | None
    b_alone: bool | None
    merged: bool | None
    wall_seconds: float
    cost_usd: float
    holds: int = 0
    briefed: int = 0
    agents: list[AgentRun] = field(default_factory=list)
    diff_a: str = ""
    diff_b: str = ""
    detail: str = ""


def _commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", message, "--allow-empty")


def _setup(tmp: Path) -> Path:
    base = tmp / "repo"
    shutil.copytree(FIXTURE, base, ignore=shutil.ignore_patterns("__pycache__"))
    (base / ".gitignore").write_text(".claude/\n__pycache__/\n*.log\n.pytest_cache/\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(base)], check=True)
    _commit(base, "base")
    for name in ("a", "b"):
        git(base, "worktree", "add", "-q", "-b", name, str(tmp / name), "main")
    return base


def _claude(cwd: Path, text: str, env: dict, agent: str, python: str = sys.executable) -> AgentRun:
    run = AgentRun(agent=agent)
    started = time.time()
    try:
        r = subprocess.run(
            [
                "claude", "-p", text,
                "--permission-mode", "acceptEdits",
                # The test command is the only shell command an agent may run.
                "--allowedTools", f"Bash({python} -m pytest:*)",
                # Isolated from the machine's own user settings, hooks and MCP servers; project settings still
                # load, which is where the airspace condition installs its hooks.
                "--setting-sources", "project,local",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}',
                "--output-format", "json", "--max-turns", "25",
            ],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=AGENT_TIMEOUT,
        )
        out = json.loads(r.stdout or "{}")
        run.cost_usd = float(out.get("total_cost_usd") or 0.0)
        run.turns = int(out.get("num_turns") or 0)
        run.result = str(out.get("result") or "")[:600]
        if r.returncode != 0 or out.get("is_error"):
            run.error = (r.stderr or str(out.get("subtype")))[-400:]
    except subprocess.TimeoutExpired:
        run.error = "timed out"
    except json.JSONDecodeError:
        run.error = "unreadable output"
    run.seconds = round(time.time() - started, 1)
    return run


def _airspace_counts(graph_name: str) -> tuple[int, int]:
    from airspace.graph.db import connect

    try:
        g = connect().select_graph(graph_name)
        holds = g.query("MATCH (c:Collision) RETURN count(c)").result_set[0][0]
        briefed = g.query("MATCH (:ContractChange)-[b:BRIEFED]->(:Task) RETURN count(b)").result_set[0][0]
        return int(holds), int(briefed)
    except Exception:
        return 0, 0


def run_pair(t: TaskSet, condition: str, python: str = sys.executable) -> PairResult:
    tmp = Path(tempfile.mkdtemp(prefix=f"airspace-bench-{t.id}-{condition}-"))
    graph_name = f"bench_{uuid.uuid4().hex[:12]}"
    try:
        base = _setup(tmp)
        env = {**os.environ}
        env.pop("CLAUDE_PROJECT_DIR", None)
        if condition == "airspace":
            env["AIRSPACE_GRAPH"] = graph_name
            subprocess.run([python, "-m", "airspace.cli", "index", "--root", str(base)], env=env, check=True, capture_output=True)
            for name in ("a", "b"):
                subprocess.run([python, "-m", "airspace.cli", "install-hooks", "--root", str(tmp / name)], env=env, check=True, capture_output=True)
        other = {"a": t.b, "b": t.a} if condition == "broadcast" else {"a": None, "b": None}
        started = time.time()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                name: pool.submit(_claude, tmp / name, prompt(getattr(t, name), other[name], python), {**env, "AIRSPACE_AGENT": f"agent-{name}"}, f"agent-{name}", python)
                for name in ("a", "b")
            }
            runs = {name: f.result() for name, f in futures.items()}
        wall = round(time.time() - started, 1)
        for name in ("a", "b"):
            _commit(tmp / name, f"agent-{name}")
        diff_a = git(base, "diff", "main", "a").stdout
        diff_b = git(base, "diff", "main", "b").stdout
        for name in ("a", "b"):
            git(base, "worktree", "remove", "--force", str(tmp / name))
        errored = any(r.error == "timed out" for r in runs.values())
        g: Grade = grade(base, "a", "b", t.hidden_a, t.hidden_b, python)
        outcome = "error" if errored else g.outcome
        holds, briefed = _airspace_counts(graph_name) if condition == "airspace" else (0, 0)
        return PairResult(
            set_id=t.id, kind=t.kind, condition=condition, outcome=outcome, a_alone=g.a_alone, b_alone=g.b_alone, merged=g.merged,
            wall_seconds=wall, cost_usd=round(sum(r.cost_usd for r in runs.values()), 4), holds=holds, briefed=briefed,
            agents=list(runs.values()), diff_a=diff_a, diff_b=diff_b, detail=g.detail[-1500:],
        )
    except Exception as e:  # recorded, never raised: one broken run must not stop the benchmark
        return PairResult(set_id=t.id, kind=t.kind, condition=condition, outcome="error", a_alone=None, b_alone=None, merged=None,
                          wall_seconds=0.0, cost_usd=0.0, detail=f"{type(e).__name__}: {e}")
    finally:
        if condition == "airspace":
            try:
                from airspace.graph.db import connect

                connect().select_graph(graph_name).delete()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="airspace-bench")
    parser.add_argument("--sets", nargs="*", help="task set ids (default: all)")
    parser.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    parser.add_argument("--jobs", type=int, default=3, help="pairs to run at once")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    sets = [t for t in load_tasks() if not args.sets or t.id in args.sets]
    jobs = [(t, c) for t in sets for c in args.conditions]
    out_dir = Path(args.out) if args.out else RESULTS / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Running {len(jobs)} pairs ({len(jobs) * 2} Claude Code sessions), {args.jobs} at a time. Results: {out_dir}")

    def one(job):
        t, c = job
        r = run_pair(t, c)
        (out_dir / f"{t.id}--{c}.json").write_text(json.dumps(asdict(r), indent=2))
        print(f"  {t.id:28} {c:10} {r.outcome:13} {r.wall_seconds:6.0f}s  ${r.cost_usd:.2f}  holds={r.holds}", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(one, jobs))
    from airspace.bench.report import write_summary

    summary = write_summary(out_dir)
    print(json.dumps(summary["conditions"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
