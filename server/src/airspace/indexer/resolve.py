"""Raw call targets to qualnames, using the module's own definitions and its import table.

A target that cannot be pinned to a known symbol stays unresolved. We never guess: a wrong CALLS edge
would hold an innocent agent, while a missing one only weakens the cone.
"""

from airspace.types import ModuleFacts


def _class_of(caller: str, facts: ModuleFacts) -> str | None:
    """The qualname of the class a method belongs to, or None for plain functions."""
    parent = caller.rsplit(".", 1)[0]
    for s in facts.symbols:
        if s.qualname == parent and s.kind == "class":
            return parent
    return None


def resolve_target(target: str, facts: ModuleFacts, caller: str, known: set[str]) -> str | None:
    local = {s.qualname for s in facts.symbols}

    def ok(candidate: str) -> bool:
        return candidate in local or candidate in known

    head, _, rest = target.partition(".")

    # 1. self.x / cls.x inside a method: a member of the enclosing class.
    if head in ("self", "cls") and rest:
        cls = _class_of(caller, facts)
        if cls is not None and ok(f"{cls}.{rest}"):
            return f"{cls}.{rest}"

    # 2. A name defined at module level here (Post, or Post.save when Post is a local class).
    if f"{facts.module}.{head}" in local and ok(f"{facts.module}.{target}"):
        return f"{facts.module}.{target}"

    # 3. An imported alias, expanded: Tag.save with Tag -> tags.models.Tag gives tags.models.Tag.save.
    if head in facts.imports:
        expanded = facts.imports[head] + (f".{rest}" if rest else "")
        if ok(expanded):
            return expanded

    # 4. Already a full qualname.
    if target in known:
        return target
    return None


def resolve_calls(facts: ModuleFacts, known: set[str]) -> list[tuple[str, str]]:
    """Resolved (caller, callee) pairs in source order, each pair once."""
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for call in facts.calls:
        callee = resolve_target(call.target, facts, call.caller, known)
        if callee is None:
            continue
        pair = (call.caller, callee)
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return pairs
