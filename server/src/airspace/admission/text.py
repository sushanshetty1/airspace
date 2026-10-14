"""Messages shown to agents. Pure functions.

Every message is a factual statement, never an imperative: Claude Code treats imperative hook text as
possible prompt injection. No em or en dashes.
"""

from airspace.types import Briefing


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
            "A retry that does not call it will be cleared."
        )
    fit = f"The call {caller} makes does not fit the new signature. " if checked else ""
    return (
        f"Airspace hold: {callee} is being changed by {other_agent}. "
        f"New signature: {new_sig} (was {old_sig}). "
        f"This edit adds a call to it from {caller}. "
        f"{fit}"
        f"Path: {caller} -> {callee}. "
        "A retry whose call matches the new signature will be cleared."
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
    return "\n".join(lines)


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
}
