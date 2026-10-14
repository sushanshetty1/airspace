from airspace.bench.report import summarize
from airspace.bench.runner import prompt


def _r(cond, outcome, cost=0.5, wall=60.0, holds=0, merged=None):
    if merged is None:
        merged = {"clean": True, "interference": False, "task_failed": True}.get(outcome)
    return {"set_id": f"s-{outcome}-{cond}", "kind": "signature", "condition": cond, "outcome": outcome, "cost_usd": cost, "wall_seconds": wall, "holds": holds, "merged": merged}


def test_summary_counts_only_graded_pairs():
    s = summarize([_r("worktrees", "interference"), _r("worktrees", "clean"), _r("worktrees", "error"), _r("airspace", "clean", holds=2), _r("airspace", "task_failed")])
    w, a = s["conditions"]["worktrees"], s["conditions"]["airspace"]
    assert w["graded"] == 2 and w["interference"] == 1 and w["interference_rate"] == 0.5 and w["errors"] == 1
    assert a["graded"] == 1 and a["interference_rate"] == 0.0 and a["task_failed"] == 1 and a["holds"] == 2
    assert s["conditions"]["broadcast"]["interference_rate"] is None


def test_prompt_mentions_other_task_only_for_broadcast():
    assert "another engineer" not in prompt("do x", None, "py")
    assert "do y" in prompt("do x", "do y", "py")


def test_merged_pass_rate_counts_task_failed_runs_that_merged_green():
    s = summarize([_r("airspace", "task_failed", merged=True), _r("airspace", "clean"), _r("airspace", "interference")])
    a = s["conditions"]["airspace"]
    assert a["merged_runs"] == 3 and a["merged_pass"] == 2 and a["merged_pass_rate"] == 0.667
