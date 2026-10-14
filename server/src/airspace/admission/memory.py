"""Memory: what agents and people learn about the code, kept on the code graph and told once to every later task.

    (:Note {id, text, kind, agent, task, at, seq, symbols})-[:ABOUT]->(:Symbol)
    (:Task)-[:RECALLED {at}]->(:Note)
    (:Task)-[:RECALLED {at}]->(:ContractChange)

A note is about one or more symbols. `kind` is "note" (written by an agent or a person) or "fix" (written by the
engine when a held call clears with one that fits). A note keeps the qualnames it is about as a property as well as
its ABOUT edges: indexing replaces Symbol nodes, and what was learned must outlive that. Who hears a note is decided
by graph queries only, never by a model.
"""

import uuid
from typing import Any

MAX_TEXT = 500
MAX_NAMES = 20
KINDS = ("note", "fix")
RECALL_LIMIT = 8

_NEXT_SEQ = """MERGE (n:Sequence {id: $seq_name}) ON CREATE SET n.value = 0
SET n.value = n.value + 1"""

_NOTE_FIELDS = "m.id, m.kind, m.symbols[0], m.text, m.agent, m.at, m.seq"


def _rows(graph, cypher: str, params: dict | None = None) -> list[list]:
    return graph.query(cypher, params or {}).result_set


def is_path(name: str) -> bool:
    """A repo-relative Python file, as opposed to a qualname."""
    return name.endswith(".py")


def _names(names: Any) -> list[str]:
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, (list, tuple)):
        return []
    return list(dict.fromkeys(n.strip() for n in names if isinstance(n, str) and n.strip()))


def expand(graph, names: list[str]) -> tuple[list[str], list[str]]:
    """(qualnames, file paths that are not in the graph). A file path stands for every symbol the file defines."""
    names = _names(names)
    paths = [n for n in names if is_path(n)]
    defined: dict[str, list[str]] = {p: [] for p in paths}
    if paths:
        for path, q in _rows(
            graph,
            "MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE f.path IN $paths RETURN f.path, s.qualname "
            "ORDER BY f.path, s.lineno, s.qualname",
            {"paths": paths},
        ):
            defined[path].append(q)
        found = {r[0] for r in _rows(graph, "MATCH (f:File) WHERE f.path IN $paths RETURN f.path", {"paths": paths})}
    else:
        found = set()
    out: list[str] = []
    for n in names:
        out.extend(defined[n] if is_path(n) else [n])
    return list(dict.fromkeys(out)), [p for p in paths if p not in found]


def _note_item(row: list) -> dict:
    nid, kind, symbol, text, agent, at, _ = row
    return {"id": nid, "kind": kind, "symbol": symbol, "text": text, "agent": agent, "at": at}


def contract_text(old_sig: str, new_sig: str, renamed_to: str) -> str:
    if new_sig:
        return f"Contract changed: {old_sig} -> {new_sig}"
    if renamed_to:
        return f"Renamed to {renamed_to}"
    return "Removed"


def _contract_item(row: list) -> dict:
    cid, qualname, old_sig, new_sig, renamed_to, agent, at, _ = row
    return {"id": cid, "kind": "contract", "symbol": qualname, "text": contract_text(old_sig, new_sig, renamed_to),
            "agent": agent, "at": at}


def _newest(items_with_seq: list[tuple[dict, Any]], limit: int) -> list[dict]:
    ordered = sorted(items_with_seq, key=lambda x: (-(x[0]["at"] or 0.0), x[0]["kind"] == "contract", -(x[1] or 0)))
    return [item for item, _ in ordered[:limit]]


def recall_rows(graph, qualnames: list[str], exclude_task: str | None, limit: int, fresh_for: str | None) -> list[dict]:
    """Notes about these qualnames and contract changes to them by tasks other than `exclude_task`, newest first.

    With `fresh_for` (a task id), only what that task has not recalled yet, was not briefed on, and did not write.
    """
    if not qualnames:
        return []
    limit = max(1, min(50, int(limit)))
    params = {"qs": qualnames, "exclude": exclude_task or "", "task": fresh_for or "", "limit": limit}
    me = "MATCH (me:Task {id: $task})\n" if fresh_for else ""
    note_fresh = " AND coalesce(m.task, '') <> $task AND NOT (me)-[:RECALLED]->(m)" if fresh_for else ""
    change_fresh = " AND NOT (me)-[:RECALLED]->(cc) AND NOT (cc)-[:BRIEFED]->(me)" if fresh_for else ""
    notes = _rows(
        graph,
        f"""{me}MATCH (m:Note) WHERE any(q IN m.symbols WHERE q IN $qs){note_fresh}
        RETURN {_NOTE_FIELDS} ORDER BY m.at DESC, m.seq DESC LIMIT $limit""",
        params,
    )
    changes = _rows(
        graph,
        f"""{me}MATCH (a:Agent)-[:FLYING]->(t:Task)-[:CHANGED]->(cc:ContractChange)
        WHERE cc.qualname IN $qs AND t.id <> $exclude{change_fresh}
        RETURN cc.id, cc.qualname, cc.old_sig, cc.new_sig, coalesce(cc.renamed_to, ''), a.id, cc.at, cc.seq
        ORDER BY cc.at DESC, cc.seq DESC LIMIT $limit""",
        params,
    )
    items = [(_note_item(r), r[6]) for r in notes] + [(_contract_item(r), r[7]) for r in changes]
    return _newest(items, limit)


def history(graph, qualnames: list[str]) -> dict:
    """What happened at these symbols before: collisions, notes and contract changes, and when the last was."""
    qs = list(qualnames)
    if not qs:
        return {"collisions": 0, "notes": 0, "changes": 0, "last_at": None}
    found = {}
    for key, cypher in (
        ("collisions", "MATCH (x:Collision) WHERE x.symbol IN $qs RETURN count(x), max(x.at)"),
        ("notes", "MATCH (m:Note) WHERE any(q IN m.symbols WHERE q IN $qs) RETURN count(m), max(m.at)"),
        ("changes", "MATCH (cc:ContractChange) WHERE cc.qualname IN $qs RETURN count(cc), max(cc.at)"),
    ):
        found[key] = _rows(graph, cypher, {"qs": qs})[0]
    times = [at for _, at in found.values() if at is not None]
    return {**{k: int(v[0]) for k, v in found.items()}, "last_at": max(times) if times else None}


def collision_counts(graph, qualnames: list[str]) -> dict[str, int]:
    """qualname -> how many collisions happened at it, for the symbols that had any."""
    if not qualnames:
        return {}
    rows = _rows(graph, "MATCH (x:Collision) WHERE x.symbol IN $qs RETURN x.symbol, count(x)", {"qs": list(qualnames)})
    return {q: int(n) for q, n in rows}


def recent(graph, limit: int = 20) -> list[dict]:
    """The newest notes and fixes, newest first."""
    limit = max(1, min(100, int(limit)))
    rows = _rows(graph, f"MATCH (m:Note) RETURN {_NOTE_FIELDS} ORDER BY m.at DESC, m.seq DESC LIMIT $limit",
                 {"limit": limit})
    return [_note_item(r) for r in rows]


def note_for_collision(graph, collision_id: str) -> dict | None:
    rows = _rows(
        graph,
        f"""MATCH (x:Collision {{id: $id}}) WHERE x.fix_note IS NOT NULL
        MATCH (m:Note {{id: x.fix_note}}) RETURN {_NOTE_FIELDS}""",
        {"id": collision_id},
    )
    return _note_item(rows[0]) if rows else None


def fix_text(held_agent: str, owner_agent: str, symbol: str, new_sig: str, held_call: str, fixed_call: str) -> str:
    """The note a resolved contract collision leaves. Factual, one or two sentences."""
    if not new_sig:
        return f"{held_agent} was held at {symbol} after {owner_agent} renamed or removed it, and cleared."
    if held_call and fixed_call:
        return (f"{held_agent}'s call {held_call} did not fit {new_sig} after {owner_agent}'s change. "
                f"It cleared as {fixed_call}.")
    return (f"{held_agent} was held at {symbol} after {owner_agent}'s change to {new_sig}, "
            "and cleared with a call that fits.")


def resolve_names(engine: Any, names: list[str]) -> list[str]:
    """Qualnames and file paths for names as people write them, through the engine (local or remote).

    Raises PreflightError (a ValueError) with suggestions when a name matches nothing or several symbols.
    """
    from airspace.admission.preflight import PreflightError

    answer = engine.lookup_symbols(list(names))
    if "error" in answer:
        raise PreflightError(str(answer["error"]), list(answer.get("suggestions") or []))
    return list(answer["symbols"])


class Memory:
    """The memory methods of Airspace. Mixed into the engine, which provides graph, clock, _q and _event."""

    graph: Any

    def remember(self, agent_id: str, task_id: str | None, qualnames: list[str], text: str, kind: str = "note") -> str:
        """Write a note about these symbols (or every symbol of a file path). Returns its id.

        Raises ValueError for empty or long text, an unknown kind, or symbols not in the code graph (named).
        """
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_TEXT:
            raise ValueError(f"A note is 1 to {MAX_TEXT} characters.")
        if kind not in KINDS:
            raise ValueError(f"A note's kind is note or fix, not {kind}.")
        qs, missing = expand(self.graph, qualnames)
        if not qs and not missing:
            raise ValueError("A note needs at least one symbol.")
        known = {r[0] for r in self._q("MATCH (s:Symbol) WHERE s.qualname IN $qs RETURN s.qualname", {"qs": qs})}
        unknown = [n for n in _names(qualnames) if n in missing or (not is_path(n) and n not in known)]
        if unknown:
            raise ValueError(f"Not in the code graph: {', '.join(unknown)}.")
        now = self.clock()
        nid = self._write_note(agent_id, task_id, qs, text.strip(), kind, now)
        self._event("noted", agent_id, task_id or None, qs[0], now)
        return nid

    def _write_note(self, agent: str, task: str | None, qs: list[str], text: str, kind: str, now: float) -> str:
        nid = uuid.uuid4().hex
        self._q(
            f"""{_NEXT_SEQ}
            CREATE (:Note {{id: $id, text: $text, kind: $kind, agent: $agent, task: $task, at: $now, seq: n.value,
                    symbols: $qs}})""",
            {"seq_name": "note", "id": nid, "text": text[:MAX_TEXT], "kind": kind, "agent": agent or "",
             "task": task or "", "now": now, "qs": qs},
        )
        # A symbol already gone from the code graph keeps the note through its symbols property.
        self._q(
            """MATCH (m:Note {id: $id}) UNWIND $qs AS q
            MATCH (s:Symbol {qualname: q}) MERGE (m)-[:ABOUT]->(s)""",
            {"id": nid, "qs": qs},
        )
        return nid

    def recall(self, qualnames: list[str], exclude_task: str | None = None, limit: int = RECALL_LIMIT) -> list[dict]:
        """What the graph remembers about these symbols or files, newest first: notes, and contract changes by
        tasks other than exclude_task.

        Items: {"id", "kind": "note"|"fix"|"contract", "symbol", "text", "agent", "at"}.
        """
        qs, _ = expand(self.graph, qualnames)
        return recall_rows(self.graph, qs, exclude_task, limit, None)

    def memory_for_task(self, task_id: str, qualnames: list[str], limit: int = RECALL_LIMIT) -> list[dict]:
        """recall for a task, minus what it already recalled, was briefed on, or wrote itself. What it returns is
        marked RECALLED in the same write, so each item reaches a task once even when two hooks ask at once."""
        qs, _ = expand(self.graph, qualnames)
        items = recall_rows(self.graph, qs, task_id, limit, task_id)
        if not items:
            return []
        now = self.clock()
        marked: set[str] = set()
        for label, kinds in (("Note", ("note", "fix")), ("ContractChange", ("contract",))):
            ids = [i["id"] for i in items if i["kind"] in kinds]
            if ids:
                marked |= {r[0] for r in self._q(
                    f"""MATCH (me:Task {{id: $task}}) UNWIND $ids AS id
                    MATCH (x:{label} {{id: id}}) WHERE NOT (me)-[:RECALLED]->(x)
                    CREATE (me)-[:RECALLED {{at: $now}}]->(x)
                    RETURN x.id""",
                    {"task": task_id, "ids": ids, "now": now},
                )}
        return [i for i in items if i["id"] in marked]

    def history(self, qualnames: list[str]) -> dict:
        """{"collisions", "notes", "changes", "last_at"} over these symbols (or every symbol of a file path)."""
        qs, _ = expand(self.graph, qualnames)
        return history(self.graph, qs)

    def recent_notes(self, limit: int = 20) -> list[dict]:
        return recent(self.graph, limit)

    def lookup_symbols(self, names: list[str]) -> dict:
        """{"symbols": [...]} for names as people write them (short names, unique suffixes, file paths), or
        {"error", "suggestions"} for the first that matches nothing or several symbols. Plain values, so the answer
        travels over RPC with its suggestions."""
        from airspace.admission.preflight import PreflightError, resolve_symbol

        names = _names(names)
        if not names:
            return {"error": "No symbols given.", "suggestions": []}
        if len(names) > MAX_NAMES:
            return {"error": f"At most {MAX_NAMES} symbols at a time.", "suggestions": []}
        out = []
        for name in names:
            if is_path(name):
                if not self._q("MATCH (f:File {path: $p}) RETURN f.path", {"p": name}):
                    return {"error": f"No file {name} in the code graph.", "suggestions": []}
                out.append(name)
                continue
            try:
                out.append(resolve_symbol(self.graph, name))
            except PreflightError as e:
                return {"error": e.message, "suggestions": e.suggestions}
        return {"symbols": list(dict.fromkeys(out))}
