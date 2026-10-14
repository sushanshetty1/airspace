"""Messages shown to agents. Pure functions.

Every message is a factual statement, never an imperative: Claude Code treats imperative hook text as
possible prompt injection. No em or en dashes.
"""

from airspace.types import Briefing


def contract_hold(callee: str, caller: str, other_agent: str, old_sig: str, new_sig: str) -> str:
    return (
        f"Airspace hold: {callee} is being changed by {other_agent}. "
        f"New signature: {new_sig} (was {old_sig}). "
        f"This edit adds a call to it from {caller}. "
        f"Path: {caller} -> {callee}. "
        "A retry whose call matches the new signature will be cleared."
    )


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
        lines.append(f"- {b.symbol} changed by {b.from_agent}: {b.old_signature} is now {b.new_signature}.")
    return "\n".join(lines)
