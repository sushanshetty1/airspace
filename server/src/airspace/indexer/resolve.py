"""Raw call targets to qualnames, using the module's own definitions and its import table.

A target that cannot be pinned to a known symbol stays unresolved. We never guess: a wrong CALLS edge
would hold an innocent agent, while a missing one only weakens the cone.
"""

from airspace.admission.compat import shape_key
from airspace.types import CallFact, ModuleFacts

# How many re-exports a name is followed through (flask.Flask -> flask.app.Flask is one).
_ALIAS_HOPS = 5
ALIAS_MARK = "=>"
BASE_MARK = "<:"


class Known(set):
    """The repo's qualnames, plus the names its packages re-export: flask.Flask -> flask.app.Flask.

    Code calls a package's public name, but the symbol lives where it is defined. A union with any set keeps the
    re-exports, so they travel wherever the known names already go.
    """

    def __init__(self, names=(), aliases: dict[str, str] | None = None, bases: dict[str, list[str]] | None = None):
        super().__init__(names)
        self.aliases: dict[str, str] = dict(aliases or {})
        # Class -> its resolved bases, so self.x and Cls.x find members a base class defines.
        self.bases: dict[str, list[str]] = {k: list(v) for k, v in (bases or {}).items()}

    def __or__(self, other):
        bases = {k: list(v) for k, v in self.bases.items()}
        for k, v in getattr(other, "bases", {}).items():
            bases[k] = list(dict.fromkeys(bases.get(k, []) + list(v)))
        return Known(set.__or__(self, set(other)), {**self.aliases, **getattr(other, "aliases", {})}, bases)

    __ror__ = __or__

    def encoded(self) -> list[str]:
        """Names, re-exports and bases as one list of strings, for the wire: "public=>defined", "cls<:base"."""
        return (sorted(self) + sorted(f"{k}{ALIAS_MARK}{v}" for k, v in self.aliases.items())
                + sorted(f"{k}{BASE_MARK}{b}" for k, v in self.bases.items() for b in v))

    @classmethod
    def decoded(cls, items) -> "Known":
        names, aliases, bases = [], {}, {}
        for item in items:
            public, mark, defined = item.partition(ALIAS_MARK)
            if mark:
                aliases[public] = defined
                continue
            sub, mark, base = item.partition(BASE_MARK)
            if mark:
                bases.setdefault(sub, []).append(base)
                continue
            names.append(item)
        return cls(names, aliases, bases)


def exports(facts: ModuleFacts) -> dict[str, str]:
    """What a package's __init__ re-exports: {"flask.Flask": "flask.app.Flask"}. Other modules export nothing."""
    if not facts.file.endswith("__init__.py"):
        return {}
    return {
        f"{facts.module}.{local}": target
        for local, target in facts.imports.items()
        if target != f"{facts.module}.{local}"
    }


def class_bases(facts: ModuleFacts, known: set[str]) -> dict[str, list[str]]:
    """This module's classes and the bases they resolve to, in declaration order."""
    out: dict[str, list[str]] = {}
    for cls, base in facts.bases:
        target = resolve_target(base, facts, cls, known)
        if target is not None:
            out.setdefault(cls, []).append(target)
    return out


def _member(owner: str, member: str, ok, bases: dict[str, list[str]]) -> str | None:
    """owner.member, or the first base (breadth first, as a rough MRO) that defines it."""
    seen, queue = set(), [owner]
    while queue:
        cls = queue.pop(0)
        if cls in seen:
            continue
        seen.add(cls)
        if ok(f"{cls}.{member}"):
            return f"{cls}.{member}"
        queue.extend(bases.get(cls, []))
    return None


def canonical(name: str, aliases: dict[str, str]) -> str:
    """Follow re-exports to where a name is defined: flask.Flask.route -> flask.app.Flask.route."""
    for _ in range(_ALIAS_HOPS):
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in aliases:
                name = aliases[prefix] + ("." + ".".join(parts[i:]) if i < len(parts) else "")
                break
        else:
            return name
    return name


def _class_of(caller: str, facts: ModuleFacts) -> str | None:
    """The qualname of the class a method belongs to, or None for plain functions."""
    parent = caller.rsplit(".", 1)[0]
    for s in facts.symbols:
        if s.qualname == parent and s.kind == "class":
            return parent
    return None


def resolve_target(target: str, facts: ModuleFacts, caller: str, known: set[str]) -> str | None:
    local = {s.qualname for s in facts.symbols}
    aliases = getattr(known, "aliases", None) or {}
    bases = getattr(known, "bases", None) or {}

    def ok(candidate: str) -> bool:
        return candidate in local or candidate in known

    def found(candidate: str) -> str | None:
        """The candidate, the symbol it re-exports, or a member a base class defines, when any is known."""
        if ok(candidate):
            return candidate
        real = canonical(candidate, aliases) if aliases else candidate
        if real != candidate and ok(real):
            return real
        owner, _, member = real.rpartition(".")
        if owner and bases.get(owner):
            return _member(owner, member, ok, bases)
        return None

    head, _, rest = target.partition(".")

    # 1. self.x / cls.x inside a method: a member of the enclosing class.
    if head in ("self", "cls") and rest:
        cls = _class_of(caller, facts)
        if cls is not None:
            if ok(f"{cls}.{rest}"):
                return f"{cls}.{rest}"
            hit = _member(cls, rest, ok, bases) if "." not in rest else None
            if hit is not None:
                return hit

    # 2. A name defined at module level here (Post, or Post.save when Post is a local class).
    if f"{facts.module}.{head}" in local and ok(f"{facts.module}.{target}"):
        return f"{facts.module}.{target}"

    # 3. An imported alias, expanded: Tag.save with Tag -> tags.models.Tag gives tags.models.Tag.save.
    if head in facts.imports:
        expanded = facts.imports[head] + (f".{rest}" if rest else "")
        hit = found(expanded)
        if hit is not None:
            return hit

    # 4. Already a full qualname, or a public name a package re-exports.
    return found(target) if (target in known or aliases) else None


def is_bound(call: CallFact) -> bool:
    """The call goes through an instance (self.x(), cls.x(), Tag(name).save()), so its first parameter is filled."""
    head, dot, _ = call.target.partition(".")
    return call.via_instance or (bool(dot) and head in ("self", "cls"))


def resolve_shapes(facts: ModuleFacts, known: set[str]) -> dict[tuple[str, str], set[str]]:
    """(caller, callee) -> the shape keys of every resolved call site between them."""
    shapes: dict[tuple[str, str], set[str]] = {}
    for call in facts.calls:
        callee = resolve_target(call.target, facts, call.caller, known)
        if callee is not None:
            key = shape_key(call.nargs, call.kwargs, call.star, is_bound(call), call.used)
            shapes.setdefault((call.caller, callee), set()).add(key)
    return shapes


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
