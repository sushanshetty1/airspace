"""Turn raw pair results into the summary the README and the website publish."""

import json
from pathlib import Path

CONDITIONS = ("worktrees", "broadcast", "airspace")


def summarize(results: list[dict]) -> dict:
    conditions = {}
    for c in CONDITIONS:
        rows = [r for r in results if r["condition"] == c]
        graded = [r for r in rows if r["outcome"] not in ("error", "task_failed")]
        # The outcome that matters to a team: is the merged build green? Counted over every pair that merged.
        merged = [r for r in rows if r["outcome"] not in ("error", "conflict") and r.get("merged") is not None]
        merged_pass = sum(bool(r["merged"]) for r in merged)
        interference = sum(r["outcome"] == "interference" for r in graded)
        conditions[c] = {
            "pairs": len(rows),
            "graded": len(graded),
            "interference": interference,
            "interference_rate": round(interference / len(graded), 3) if graded else None,
            "merged_runs": len(merged),
            "merged_pass": merged_pass,
            "merged_pass_rate": round(merged_pass / len(merged), 3) if merged else None,
            "clean": sum(r["outcome"] == "clean" for r in graded),
            "conflict": sum(r["outcome"] == "conflict" for r in graded),
            "task_failed": sum(r["outcome"] == "task_failed" for r in rows),
            # Held or briefed, an agent writes against the other's new contract: its patch fails on its own old
            # branch and passes merged. The paper's alone-then-merged grading calls that a failed task.
            "adapted": sum(_adapted(r) for r in rows),
            "errors": sum(r["outcome"] == "error" for r in rows),
            "median_wall_seconds": _median([r["wall_seconds"] for r in rows if r["outcome"] != "error"]),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 2),
            "holds": sum(r.get("holds", 0) for r in rows),
        }
    by_set = {}
    for r in results:
        row = by_set.setdefault(r["set_id"], {"kind": r["kind"]})
        row.setdefault(r["condition"], []).append({"outcome": r["outcome"], "merged": r.get("merged")})
    return {"conditions": conditions, "sets": by_set}


def _adapted(r: dict) -> bool:
    alone = (r.get("a_alone"), r.get("b_alone"))
    return (r["outcome"] == "task_failed" and bool(r.get("merged")) and False in alone and None not in alone
            and (r.get("holds", 0) > 0 or r.get("briefed", 0) > 0))


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    mid = len(xs) // 2
    return round(xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2, 1)


def write_summary(out_dir: Path) -> dict:
    results = [json.loads(p.read_text()) for p in sorted(out_dir.glob("*--*.json"))]
    summary = summarize(results)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
