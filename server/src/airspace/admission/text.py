"""Messages shown to agents. Pure functions.

Every message is a factual statement, never an imperative: Claude Code treats imperative hook text as
possible prompt injection. No em or en dashes.
"""

from airspace.types import Briefing


# Agents often work in separate worktrees, so a change another agent made may not be on disk here yet.
BRANCH_NOTE = (
    "That change may not be in this working copy yet, so local tests can still reflect the old signature "
    "until the branches are merged."
)
# The hooks know the agent's working copy and replace BRANCH_NOTE with one of these facts.
LOCAL_NOTE = "This working copy already has that change, so local tests use the new signature."
NOT_HERE_NOTE = (
    "That change is not in this working copy yet, so local tests still reflect the old signature until the "
    "branches are merged. A call that fits the new signature is the one that merges cleanly, and a local test "
    "failure caused only by that difference goes away at the merge."
)


def contract_hold(
    callee: str, caller: str, other_agent: str, old_sig: str, new_sig: str, checked: bool = False
) -> str:
    """`checked` means the call's arguments were checked against the new signature and do not fit it."""
    if not new_sig:
        return (
            f"Airspace hold: {callee} is being renamed or removed by {other_agent}. "
            f"It was {old_sig}. "
            f"This edit adds a call to it from {caller}. "
            f"Path: {caller} -> {callee}. "
            "A retry that does not call it will be cleared. "
            f"{BRANCH_NOTE}"
        )
    fit = f"The call {caller} makes does not fit the new signature. " if checked else ""
    return (
        f"Airspace hold: {callee} is being changed by {other_agent}. "
        f"New signature: {new_sig} (was {old_sig}). "
        f"This edit adds a call to it from {caller}. "
        f"{fit}"
        f"Path: {caller} -> {callee}. "
        "A retry whose call matches the new signature will be cleared. "
        f"{BRANCH_NOTE}"
    )


def briefing_line(b: Briefing) -> str:
    """One contract change in a sentence or two, with the call it breaks when one is known."""
    if not b.new_signature:
        line = f"{b.symbol} was renamed or removed by {b.from_agent} (it was {b.old_signature})."
        if b.caller:
            line += f" The call {b.caller} makes to it has no target now."
        return line
    line = f"{b.symbol} was changed by {b.from_agent}. New signature: {b.new_signature} (was {b.old_signature})."
    if b.caller:
        line += f" The call {b.caller} makes no longer fits {b.new_signature}."
    return line


def claim_hold(symbol: str, other_agent: str, other_task: str) -> str:
    return (
        f"Airspace hold: {symbol} is reserved by {other_agent} (task {other_task}). "
        "The reservation lasts until its lease ends or it is released. "
        "This edit changes that symbol."
    )


def briefing_text(briefings: list[Briefing]) -> str:
    if not briefings:
        return ""
    lines = ["Airspace briefing: contracts this task depends on have changed."]
    for b in briefings:
        if not b.new_signature:
            lines.append(f"- {b.symbol} renamed or removed by {b.from_agent}: it was {b.old_signature}.")
        else:
            lines.append(f"- {b.symbol} changed by {b.from_agent}: {b.old_signature} is now {b.new_signature}.")
        if b.caller:
            target = "has no target now" if not b.new_signature else f"no longer fits {b.new_signature}"
            lines.append(f"  The call {b.caller} makes {target}.")
    lines.append(BRANCH_NOTE)
    return "\n".join(lines)


def landing_hold(violations: list[dict]) -> str:
    """Calls in the agent's own code that do not fit a contract another agent changed, found as it stops.

    Each violation has symbol, caller, call (the call as written, may be ""), old_sig, new_sig ("" when removed)
    and agent (who changed it).
    """
    by_symbol: dict[str, list[dict]] = {}
    for v in violations:
        by_symbol.setdefault(v["symbol"], []).append(v)
    parts = []
    for symbol, calls in by_symbol.items():
        v = calls[0]
        if v["new_sig"]:
            parts.append(f"{symbol} was changed by {v['agent']} to {v['new_sig']} (it was {v['old_sig']}).")
        else:
            parts.append(f"{symbol} was renamed or removed by {v['agent']} (it was {v['old_sig']}).")
        verdict = "does not fit it" if v["new_sig"] else "has no target now"
        for c in calls:
            call = f", {c['call']}," if c["call"] else ""
            parts.append(f"The call {c['caller']} makes{call} {verdict}.")
    return (
        "Airspace: before landing, " + " ".join(parts) + " "
        "Landing is cleared once these calls match the current contracts. "
        f"{BRANCH_NOTE}"
    )


def paused_hold(agent: str) -> str:
    return f"Airspace hold: {agent} is paused from Tower. Its edits are held until it is resumed."


# Event log phrases. Tower renders an event as "<agent> <text> <code>".
EVENT_TEXT = {
    "plan": "filed a plan for",
    "cleared": "was cleared to edit",
    "contract": "changed the signature of",
    "hold": "was held editing",
    "briefed": "got the new signature of",
    "paused": "was paused from",
    "resumed": "was resumed from",
    "released": "had a hold released at",
    "message": "got a message from",
    "resolved": "cleared the collision at",
    "holding": "is holding for",
    "landed": "landed",
}
