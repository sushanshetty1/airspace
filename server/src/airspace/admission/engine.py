"""The admission engine: flight plans, leases, impact cones, clearance, contract changes and briefings.

Every decision is deterministic Cypher plus the rules in check_edit. All state lives in the FalkorDB graph,
so any number of hook processes can share one Airspace view of the repo. That includes what Tower controls
(paused agents, messages, released holds), the append-only Event log and the read models Tower renders.

Agents are the unit of conflict. One agent can fly several tasks (a task per Claude session from the hooks,
"<agent>:mcp" from the MCP server), and an agent's own tasks never hold each other.
"""

import re
import time
import uuid
from typing import Callable

from airspace.admission import insights as memory
from airspace.admission import text
from airspace.admission.compat import call_fits, parse_shape
from airspace.graph.db import ensure_schema
from airspace.types import Briefing, CallSite, SignatureChange, Verdict

# Edges along which a change to one symbol can break another. Read as "dependent -> dependency".
_DEPENDS = "CALLS|COVERS|INHERITS"

# Atomic lease. Writes to one graph are serialised, so check-and-set in one query cannot race.
# Every node is matched before the count: a MATCH after an aggregation loses rows in FalkorDB.
# Only another agent's live claim blocks; the agent's other tasks may hold the same symbol.
_LEASE = """
MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
OPTIONAL MATCH (oa:Agent)-[:FLYING]->(ot:Task)-[c:CLAIMS]->(s)
WHERE oa.id <> $agent AND c.lease_until > $now AND coalesce(ot.status, 'active') <> 'landed'
WITH t, s, count(c) AS held
WHERE held = 0
MERGE (t)-[k:CLAIMS]->(s)
SET k.lease_until = $now + $ttl, k.fence = coalesce(k.fence, 0) + 1, k.at = $now
RETURN k.fence
"""

# A per-graph counter, so rows written in the same clock tick keep their insertion order.
_NEXT_SEQ = """MERGE (n:Sequence {id: $seq_name}) ON CREATE SET n.value = 0
SET n.value = n.value + 1"""

_COLLISION_FIELDS = (
    "x.id, x.at, x.kind, x.symbol, x.caller, x.held_agent, x.held_task, x.owner_agent, x.owner_task, "
    "x.old_sig, x.new_sig, x.resolution"
)
_RADAR_AGENTS = 4
_STATE_COLLISIONS = 20

# Task status. 'active' is flying; 'holding' waits at its Stop hook for another agent; 'landed' has stopped (a task
# that edits again is 'active' once more); 'released' gave up its claims. A contract change stands until its task is
# released, and Tower shows every task that has not been released.
_STANDING = ["active", "holding", "landed"]


def removed_qualnames(graph) -> set[str]:
    """Symbols some agent renamed or removed. Clearance keeps resolving calls to them, so such calls are held."""
    return {r[0] for r in graph.query("MATCH (cc:ContractChange {new_sig: ''}) RETURN DISTINCT cc.qualname").result_set}


def _label(qualname: str, kind: str | None) -> str:
    parts = qualname.split(".")
    # A method reads better with its class: "Post.save", not "save".
    return ".".join(parts[-2:]) if kind == "method" and len(parts) > 1 else parts[-1]


# How long a Read of a file counts as interest in it, for the holding pattern at landing.
READ_INTEREST_SECONDS = 900
_TOKEN = re.compile(r"[A-Za-z_][\w./]*")

class Airspace:
    def __init__(self, graph, lease_seconds: int = 900, cone_depth: int = 2, clock: Callable[[], float] = time.time):
        self.graph = graph
        self.lease_seconds = lease_seconds
        # Interpolated into variable-length patterns (Cypher cannot parameterise them), so force an int.
        self.cone_depth = max(1, int(cone_depth))
        self.clock = clock
        ensure_schema(graph)

    def _q(self, cypher: str, params: dict | None = None) -> list[list]:
        return self.graph.query(cypher, params or {}).result_set

    # Tasks and leases

    def ensure_task(self, agent_id: str, task_id: str, intent: str = "") -> None:
        # A task that edits again is flying again: a released, holding or landed task is active on its next edit.
        self._q(
            """MERGE (a:Agent {id: $agent})
            ON CREATE SET a.paused = false
            MERGE (t:Task {id: $task})
            ON CREATE SET t.started_at = $now, t.intent = $intent
            SET t.status = 'active', t.intent = CASE WHEN $intent = '' THEN coalesce(t.intent, '') ELSE $intent END
            MERGE (a)-[:FLYING]->(t)""",
            {"agent": agent_id, "task": task_id, "intent": intent, "now": self.clock()},
        )

    def _ensure_known(self, task_id: str) -> str:
        agent = self.agent_of(task_id)
        if agent is None:
            self.ensure_task(task_id, task_id)
            agent = task_id
        return agent

    def agent_of(self, task_id: str) -> str | None:
        rows = self._q("MATCH (a:Agent)-[:FLYING]->(:Task {id: $task}) RETURN a.id LIMIT 1", {"task": task_id})
        return rows[0][0] if rows else None

    def claim(self, task_id: str, qualnames: list[str]) -> list[str]:
        held = self._claim(task_id, qualnames)
        # A task's first claim is its flight plan. Dynamic claims made by cleared edits log as "cleared" instead.
        if held and self._q(
            "MATCH (t:Task {id: $task}) WHERE t.planned IS NULL SET t.planned = true RETURN t.id", {"task": task_id}
        ):
            self._event("plan", self.agent_of(task_id), task_id, held[0])
        return held

    def _claim(self, task_id: str, qualnames: list[str]) -> list[str]:
        agent = self.agent_of(task_id) or task_id
        held = []
        now = self.clock()
        for q in dict.fromkeys(qualnames):
            params = {"task": task_id, "agent": agent, "q": q, "now": now, "ttl": self.lease_seconds}
            if self._q(_LEASE, params):
                held.append(q)
        return held

    def _defer_claims(self, task_id: str, qualnames: list[str]) -> None:
        """Remember touched symbols that do not exist yet, to claim once the edit that creates them is written."""
        if not qualnames:
            return
        existing = {r[0] for r in self._q(
            "MATCH (s:Symbol) WHERE s.qualname IN $qs RETURN s.qualname", {"qs": qualnames}
        )}
        missing = [q for q in qualnames if q not in existing]
        if missing:
            self._q(
                """MATCH (t:Task {id: $task})
                SET t.pending_claims = coalesce(t.pending_claims, []) + $missing""",
                {"task": task_id, "missing": missing},
            )

    def claim_pending(self, task_id: str) -> list[str]:
        """Claim the symbols a cleared edit created, now that they are indexed. Returns what was claimed."""
        rows = self._q(
            """MATCH (t:Task {id: $task}) WHERE size(coalesce(t.pending_claims, [])) > 0
            WITH t, t.pending_claims AS pending
            SET t.pending_claims = []
            RETURN pending""",
            {"task": task_id},
        )
        if not rows:
            return []
        held = self._claim(task_id, list(dict.fromkeys(rows[0][0])))
        if held:
            self.refresh_cone(task_id)
        return held

    def file_plan(self, agent_id: str, task_id: str, intent: str, qualnames: list[str]) -> list[str]:
        self.ensure_task(agent_id, task_id, intent)
        self.claim(task_id, qualnames)
        return self.refresh_cone(task_id)

    def refresh_cone(self, task_id: str) -> list[str]:
        params = {"task": task_id, "now": self.clock()}
        self._q("MATCH (:Task {id: $task})-[k:CONE]->() DELETE k", params)
        self._q(
            f"""MATCH (t:Task {{id: $task}})-[c:CLAIMS]->(s:Symbol) WHERE c.lease_until > $now
            MATCH (d:Symbol)-[:{_DEPENDS}*1..{self.cone_depth}]->(s)
            MERGE (t)-[:CONE]->(d)""",
            params,
        )
        # The cone is what depends on the claims, not the claims themselves (two claimed symbols can call each other).
        self._q(
            """MATCH (t:Task {id: $task})-[k:CONE]->(d:Symbol)
            MATCH (t)-[c:CLAIMS]->(d) WHERE c.lease_until > $now
            DELETE k""",
            params,
        )
        rows = self._q("MATCH (:Task {id: $task})-[:CONE]->(d:Symbol) RETURN d.qualname ORDER BY d.qualname", params)
        return [r[0] for r in rows]

    def release(self, task_id: str) -> None:
        self._q("MATCH (:Task {id: $task})-[k:CLAIMS|CONE|PASS]->() DELETE k", {"task": task_id})
        self._q(
            "MATCH (t:Task {id: $task}) SET t.status = 'released', t.released_at = $now",
            {"task": task_id, "now": self.clock()},
        )

    # Clearance

    def check_edit(
        self,
        task_id: str,
        touched: list[str],
        new_calls: list[tuple[str, str]],
        call_shapes: dict[str, list[CallSite]] | None = None,
    ) -> Verdict:
        me = self._ensure_known(task_id)
        now = self.clock()
        touched = list(dict.fromkeys(touched))
        callees = [callee for _, callee in new_calls]
        subject = touched[0] if touched else (new_calls[0][0] if new_calls else "")

        # Rule 0: an agent paused from Tower is held whatever it edits.
        if self._q("MATCH (a:Agent {id: $agent}) WHERE a.paused = true RETURN a.id", {"agent": me}):
            self._event("hold", me, task_id, subject, now)
            return Verdict(kind="hold", reason=text.paused_hold(me))

        # Rule 1: a new call into a contract another agent's active task is changing.
        # With the call's shapes, it is checked against the latest new signature every time: it holds while it does
        # not fit and clears once it does, briefed or not. Without shapes, it holds once, until briefed.
        for caller, callee in new_calls:
            rows = self._q(
                """MATCH (me:Task {id: $task})
                MATCH (a:Agent)-[:FLYING]->(o:Task)-[:CHANGED]->(cc:ContractChange {qualname: $callee})
                WHERE a.id <> $agent AND o.status IN $standing
                OPTIONAL MATCH (cc)-[b:BRIEFED]->(me)
                RETURN cc.id, cc.qualname, cc.old_sig, cc.new_sig, o.id, a.id, b IS NOT NULL, coalesce(b.released, false)
                ORDER BY cc.at, cc.seq""",
                {"task": task_id, "agent": me, "callee": callee, "standing": _STANDING},
            )
            if not rows:
                continue
            unbriefed = [r for r in rows if not r[6]]
            sites = [site for site in (call_shapes or {}).get(callee, []) if site.caller == caller]
            latest = rows[-1]
            checked = bool(sites) and self._judgeable(callee, latest[3])
            if checked:
                if latest[7]:
                    continue  # Tower released this hold
                if all(call_fits(latest[3], x.nargs, x.kwargs, x.star, x.bound) for x in sites):
                    continue
                first, last = rows[0], latest
            else:
                if not unbriefed:
                    continue
                first, last = unbriefed[0], unbriefed[-1]
            briefings = [Briefing(r[0], r[1], r[2], r[3], r[5]) for r in unbriefed]
            for b in briefings:
                self._brief(b.id, task_id, now)
            other_task, other_agent = last[4], last[5]
            old_sig, new_sig = first[2], last[3]
            cid = self._contract_collision(
                now, me, task_id, other_agent, other_task, callee, caller, old_sig, new_sig, last[0]
            )
            self._event("hold", me, task_id, caller, now)
            if briefings:
                self._event("briefed", me, task_id, callee, now)
            return Verdict(
                kind="hold",
                reason=text.contract_hold(callee, caller, other_agent, old_sig, new_sig, checked=checked),
                path=[caller, callee],
                other_agent=other_agent,
                collision_id=cid,
                briefings=briefings,
            )

        # Rule 2: a touched symbol another agent's active task holds under a live lease, unless Tower released it.
        passed = []
        for q in touched:
            rows = self._q(
                """MATCH (a:Agent)-[:FLYING]->(o:Task {status: 'active'})-[c:CLAIMS]->(:Symbol {qualname: $q})
                WHERE a.id <> $agent AND c.lease_until > $now
                RETURN o.id, a.id LIMIT 1""",
                {"agent": me, "q": q, "now": now},
            )
            if not rows:
                continue
            if self._q(
                "MATCH (:Task {id: $task})-[p:PASS]->(:Symbol {qualname: $q}) WHERE p.until > $now RETURN p.until",
                {"task": task_id, "q": q, "now": now},
            ):
                passed.append(q)
                continue
            other_task, other_agent = rows[0]
            cid = self._collide("claim", now, me, task_id, other_agent, other_task, q)
            self._event("hold", me, task_id, q, now)
            return Verdict(
                kind="hold",
                reason=text.claim_hold(q, other_agent, other_task),
                path=[q],
                other_agent=other_agent,
                collision_id=cid,
            )

        # Rule 3: cleared. A pass is spent only once the edit it covers goes through.
        if passed:
            self._q(
                "MATCH (:Task {id: $task})-[p:PASS]->(s:Symbol) WHERE s.qualname IN $qs DELETE p",
                {"task": task_id, "qs": passed},
            )
        # Dynamic scope: whatever the task touches becomes its claim if free. A symbol the edit creates is not in
        # the graph until the post hook re-indexes the file, so it is claimed then (claim_pending).
        self._claim(task_id, touched)
        self._defer_claims(task_id, touched)
        self._note_touched(task_id, touched)
        self.refresh_cone(task_id)
        if subject:
            self._event("cleared", me, task_id, subject, now)
        names = touched + [caller for caller, _ in new_calls] + callees
        self._resolve(me, task_id, names, now, None if call_shapes is None else new_calls)
        return Verdict(kind="cleared", reason="")

    def _judgeable(self, qualname: str, new_sig: str) -> bool:
        """Whether calls can be checked against this change. A class line ("Post(Base)") says nothing about calls."""
        if not new_sig:
            return True
        rows = self._q("MATCH (s:Symbol {qualname: $q}) RETURN s.kind", {"q": qualname})
        return not rows or rows[0][0] != "class"

    def _resolve(
        self, agent: str, task_id: str, qualnames: list[str], now: float,
        cleared_calls: list[tuple[str, str]] | None = None,
    ) -> None:
        """A cleared edit by the held task on the contested symbol means the collision has been worked out.

        When the check carried call shapes, a contract collision is resolved only by a cleared call on the same
        (caller, symbol) pair: that call was checked and fits, so the broken call has been fixed.
        """
        if not qualnames:
            return
        params = {"task": task_id, "qs": list(dict.fromkeys(qualnames)), "now": now}
        if cleared_calls is None:
            where = "x.symbol IN $qs OR x.caller IN $qs"
        else:
            where = (
                "(x.kind = 'contract' AND (x.caller + ' ' + x.symbol) IN $pairs) "
                "OR (x.kind <> 'contract' AND (x.symbol IN $qs OR x.caller IN $qs))"
            )
            params["pairs"] = [f"{caller} {callee}" for caller, callee in cleared_calls]
        rows = self._q(
            f"""MATCH (x:Collision {{held_task: $task, resolution: 'held'}})
            WHERE {where}
            SET x.resolution = 'resolved', x.resolved_at = $now
            RETURN x.symbol ORDER BY x.at, x.seq""",
            params,
        )
        for (symbol,) in rows:
            self._event("resolved", agent, task_id, symbol, now)

    def _brief(self, change_id: str, task_id: str, now: float) -> None:
        self._q(
            """MATCH (cc:ContractChange {id: $id}), (t:Task {id: $task})
            MERGE (cc)-[b:BRIEFED]->(t)
            ON CREATE SET b.at = $now""",
            {"id": change_id, "task": task_id, "now": now},
        )

    def _collide(
        self, kind: str, now: float, held_agent: str, held_task: str, owner_agent: str, owner_task: str, symbol: str,
        caller: str | None = None, old_sig: str | None = None, new_sig: str | None = None,
        change_id: str | None = None,
    ) -> str:
        # Append-only: collisions are history the planner learns hot zones from.
        cid = uuid.uuid4().hex
        self._q(
            f"""MATCH (me:Task {{id: $held_task}}), (o:Task {{id: $owner_task}})
            {_NEXT_SEQ}
            CREATE (x:Collision {{id: $id, at: $now, seq: n.value, kind: $kind, resolution: 'held',
                    held_agent: $held_agent, held_task: $held_task, owner_agent: $owner_agent, owner_task: $owner_task,
                    symbol: $symbol, caller: $caller, old_sig: $old_sig, new_sig: $new_sig, change_id: $change_id}})
            CREATE (x)-[:BETWEEN]->(me), (x)-[:BETWEEN]->(o)""",
            {"seq_name": "collision", "id": cid, "now": now, "kind": kind, "held_agent": held_agent,
             "held_task": held_task, "owner_agent": owner_agent, "owner_task": owner_task, "symbol": symbol,
             "caller": caller, "old_sig": old_sig, "new_sig": new_sig, "change_id": change_id},
        )
        # A removed symbol may already be gone from the code graph; the collision is recorded all the same.
        self._q(
            "MATCH (x:Collision {id: $id}), (s:Symbol {qualname: $symbol}) CREATE (x)-[:AT]->(s)",
            {"id": cid, "symbol": symbol},
        )
        return cid

    def _contract_collision(
        self, now: float, held_agent: str, held_task: str, owner_agent: str, owner_task: str, symbol: str,
        caller: str, old_sig: str, new_sig: str, change_id: str,
    ) -> str:
        """The open collision for this call and signature, or a new one: a call held again is the same collision."""
        rows = self._q(
            """MATCH (x:Collision {kind: 'contract', resolution: 'held', held_task: $task, symbol: $symbol,
                                   caller: $caller, new_sig: $new_sig})
            RETURN x.id ORDER BY x.at, x.seq LIMIT 1""",
            {"task": held_task, "symbol": symbol, "caller": caller, "new_sig": new_sig},
        )
        if rows:
            return rows[0][0]
        return self._collide(
            "contract", now, held_agent, held_task, owner_agent, owner_task, symbol,
            caller=caller, old_sig=old_sig, new_sig=new_sig, change_id=change_id,
        )

    # Contract changes and briefings

    def renamed(self, qualnames: list[str]) -> dict[str, tuple[str, str]]:
        """For removed symbols that were renamed: qualname -> (new qualname, new signature), latest change wins."""
        rows = self._q(
            """MATCH (cc:ContractChange) WHERE cc.qualname IN $qs AND cc.new_sig = '' AND coalesce(cc.renamed_to, '') <> ''
            RETURN cc.qualname, cc.renamed_to, cc.renamed_sig ORDER BY cc.at, cc.seq""",
            {"qs": qualnames},
        )
        return {r[0]: (r[1], r[2]) for r in rows}

    def record_changes(self, task_id: str, changes: list[SignatureChange]) -> list[str]:
        """Record contract changes and hold the callers they break.

        A change the agent already recorded (same new signature) is skipped, so the pre hook and the post hook can
        both report it. A removal (new signature "") is recorded even once the symbol has left the code graph.
        """
        agent = self._ensure_known(task_id)
        ids = []
        for ch in changes:
            now = self.clock()
            latest = self._q(
                """MATCH (:Agent {id: $agent})-[:FLYING]->(:Task)-[:CHANGED]->(cc:ContractChange {qualname: $q})
                RETURN cc.new_sig ORDER BY cc.at DESC, cc.seq DESC LIMIT 1""",
                {"agent": agent, "q": ch.qualname},
            )
            if latest and latest[0][0] == ch.new_signature:
                continue
            kind = self._q("MATCH (s:Symbol {qualname: $q}) RETURN s.kind", {"q": ch.qualname})
            if not kind and ch.new_signature:
                continue
            cid = uuid.uuid4().hex
            rows = self._q(
                f"""MATCH (t:Task {{id: $task}})
                {_NEXT_SEQ}
                CREATE (cc:ContractChange {{id: $id, qualname: $q, old_sig: $old, new_sig: $new, at: $now,
                        renamed_to: $renamed_to, renamed_sig: $renamed_sig, seq: n.value}})
                CREATE (t)-[:CHANGED]->(cc)
                RETURN cc.id""",
                {"seq_name": "change", "task": task_id, "q": ch.qualname, "id": cid, "old": ch.old_signature,
                 "new": ch.new_signature, "now": now, "renamed_to": ch.renamed_to, "renamed_sig": ch.renamed_signature},
            )
            if not rows:
                continue
            if kind:
                self._q(
                    "MATCH (cc:ContractChange {id: $id}), (s:Symbol {qualname: $q}) CREATE (cc)-[:ON]->(s)",
                    {"id": cid, "q": ch.qualname},
                )
            self._event("contract", agent, task_id, ch.qualname, now)
            ids.append(cid)
            self._hold_callers(task_id, agent, ch, cid, kind[0][0] if kind else None, now)
        return ids

    def _hold_callers(
        self, task_id: str, agent: str, ch: SignatureChange, change_id: str, kind: str | None, now: float
    ) -> None:
        """Caller first: another agent already wrote a call this change breaks, in code it has claimed.

        That agent may be flying, holding at its landing or landed. Each such agent gets a held contract collision
        and a hold event. Its briefing stays pending, so its next
        tool call of any kind delivers it. Only stored call shapes count: an edge without shapes holds no one.
        """
        if kind == "class" and ch.new_signature:
            return
        targets = [ch.qualname]
        owner, _, name = ch.qualname.rpartition(".")
        if name == "__init__":
            targets.append(owner)  # Class(...) binds its arguments to __init__
        rows = self._q(
            """MATCH (d:Symbol)-[r:CALLS|COVERS]->(s:Symbol)
            WHERE s.qualname IN $targets AND r.shapes IS NOT NULL
            MATCH (a:Agent)-[:FLYING]->(t:Task)-[c:CLAIMS]->(d)
            WHERE a.id <> $agent AND c.lease_until > $now AND t.status IN $standing
            RETURN a.id, t.id, d.qualname, s.qualname, s.kind, r.shapes
            ORDER BY a.id, d.qualname, t.id""",
            {"targets": targets, "agent": agent, "now": now, "standing": _STANDING},
        )
        broken: dict[str, tuple[str, str]] = {}  # agent -> (its task, the caller whose call no longer fits)
        for other, other_task, caller, target, target_kind, shapes in rows:
            if other in broken:
                continue
            via_class = target != ch.qualname
            if via_class and target_kind != "class":
                continue
            for key in shapes or []:
                shape = parse_shape(key)
                if shape is None:
                    continue
                nargs, kwargs, star, bound = shape
                if not call_fits(ch.new_signature, nargs, kwargs, star, bound or via_class):
                    broken[other] = (other_task, caller)
                    break
        for other, (other_task, caller) in broken.items():
            if self._q(
                """MATCH (x:Collision {kind: 'contract', resolution: 'held', held_agent: $other, symbol: $q,
                                       new_sig: $new})
                RETURN x.id LIMIT 1""",
                {"other": other, "q": ch.qualname, "new": ch.new_signature},
            ):
                continue
            self._collide(
                "contract", now, other, other_task, agent, task_id, ch.qualname,
                caller=caller, old_sig=ch.old_signature, new_sig=ch.new_signature, change_id=change_id,
            )
            self._event("hold", other, other_task, caller, now)

    def pending_briefings(self, task_id: str) -> list[Briefing]:
        """Contract changes this task depends on and has not been told about, each returned once.

        Two sources: changes in the cone of what the task claims, and changes behind a held contract collision on
        this agent (the caller-first case). The second kind names the call that no longer fits.
        """
        now = self.clock()
        agent = self.agent_of(task_id) or task_id
        rows = self._q(
            f"""MATCH (me:Task {{id: $task}})-[c:CLAIMS]->(mine:Symbol) WHERE c.lease_until > $now
            MATCH (mine)-[:{_DEPENDS}*1..{self.cone_depth}]->(s:Symbol)<-[:ON]-(cc:ContractChange)
                  <-[:CHANGED]-(o:Task)<-[:FLYING]-(a:Agent)
            WHERE a.id <> $agent AND NOT (cc)-[:BRIEFED]->(me)
            RETURN DISTINCT cc.id, cc.qualname, cc.old_sig, cc.new_sig, a.id, cc.at
            ORDER BY cc.at""",
            {"task": task_id, "agent": agent, "now": now},
        )
        callers = self._q(
            """MATCH (x:Collision {held_agent: $agent, kind: 'contract', resolution: 'held'})
            WHERE x.change_id IS NOT NULL
            MATCH (cc:ContractChange) WHERE cc.id = x.change_id
            MATCH (me:Task {id: $task})
            WHERE NOT (cc)-[:BRIEFED]->(me)
            RETURN cc.id, cc.qualname, cc.old_sig, cc.new_sig, x.owner_agent, cc.at, x.caller
            ORDER BY cc.at""",
            {"task": task_id, "agent": agent},
        )
        found: dict[str, list] = {r[0]: [*r, None] for r in rows}
        for r in callers:
            found[r[0]] = list(r)
        briefings = []
        for r in sorted(found.values(), key=lambda r: r[5]):
            self._brief(r[0], task_id, now)
            self._event("briefed", agent, task_id, r[1], now)
            briefings.append(Briefing(r[0], r[1], r[2], r[3], r[4], r[6]))
        return briefings

    # Landing. The Stop hook checks the calls in the files a task edited before the agent stops.

    def _note_touched(self, task_id: str, qualnames: list[str]) -> None:
        if qualnames:
            self._q(
                """MATCH (t:Task {id: $task})
                SET t.touched = coalesce(t.touched, []) + [q IN $qs WHERE NOT q IN coalesce(t.touched, [])]""",
                {"task": task_id, "qs": list(dict.fromkeys(qualnames))},
            )

    def record_edited_file(self, task_id: str, rel: str) -> None:
        """Remember a repo-relative file the task edited, once. A task not in the graph yet is left alone."""
        self._q(
            """MATCH (t:Task {id: $task})
            WITH t, coalesce(t.files, []) AS files
            SET t.files = CASE WHEN $rel IN files THEN files ELSE files + [$rel] END""",
            {"task": task_id, "rel": rel},
        )

    def edited_files(self, task_id: str) -> list[str]:
        rows = self._q("MATCH (t:Task {id: $task}) RETURN coalesce(t.files, [])", {"task": task_id})
        return list(rows[0][0]) if rows else []

    def _own_symbols(self, task_id: str) -> set[str]:
        """What the task touched or claims (at any lease): the code that is the task's own."""
        rows = self._q(
            """MATCH (t:Task {id: $task})
            OPTIONAL MATCH (t)-[:CLAIMS]->(s:Symbol)
            RETURN coalesce(t.touched, []), coalesce(t.pending_claims, []), collect(s.qualname)""",
            {"task": task_id},
        )
        if not rows:
            return set()
        touched, pending, claimed = rows[0]
        return set(touched) | set(pending) | set(claimed)

    def stop_check(
        self, task_id: str, calls: list[tuple[str, str, CallSite]]
    ) -> tuple[list[dict], list[str]]:
        """(violations, agents to wait for) for the calls in the task's files as they are now.

        Only calls made from the task's own symbols count. A violation is a call that does not fit the latest
        signature another agent gave its callee, or a call to a symbol another agent renamed or removed; each one is
        recorded as a held contract collision, and the change counts as briefed (the Stop hook states it). The
        agents to wait for are other agents with an active task holding a live claim on a callee: they may still
        change it. An agent that is paused, or itself holding at its landing, is never waited for, so two agents
        cannot wait for each other.
        """
        me = self._ensure_known(task_id)
        now = self.clock()
        own = self._own_symbols(task_id)
        mine = [(caller, callee, site) for caller, callee, site in calls if caller in own]
        callees = sorted({callee for _, callee, _ in mine})
        if not callees:
            return [], []

        rows = self._q(
            """MATCH (a:Agent)-[:FLYING]->(o:Task)-[:CHANGED]->(cc:ContractChange)
            WHERE cc.qualname IN $callees AND a.id <> $agent AND o.status IN $standing
            OPTIONAL MATCH (cc)-[b:BRIEFED]->(:Task {id: $task})
            RETURN cc.qualname, cc.id, cc.old_sig, cc.new_sig, a.id, o.id, coalesce(b.released, false)
            ORDER BY cc.at, cc.seq""",
            {"callees": callees, "agent": me, "task": task_id, "standing": _STANDING},
        )
        changes: dict[str, tuple[str, list]] = {}  # callee -> (first old signature, latest change)
        for row in rows:
            first = changes.get(row[0], (row[2], row))[0]
            changes[row[0]] = (first, row)

        violations: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for caller, callee, site in mine:
            if callee not in changes:
                continue
            old_sig, (_, change_id, _, new_sig, other_agent, other_task, released) = changes[callee]
            if released or not self._judgeable(callee, new_sig):
                continue  # Tower released this hold, or a class line says nothing about calls
            if call_fits(new_sig, site.nargs, site.kwargs, site.star, site.bound):
                continue
            key = (caller, callee, site.text)
            if key in seen:
                continue
            seen.add(key)
            violations.append({
                "symbol": callee, "caller": caller, "call": site.text, "old_sig": old_sig, "new_sig": new_sig,
                "agent": other_agent, "task": other_task, "change_id": change_id,
            })

        for v in {(v["caller"], v["symbol"]): v for v in violations}.values():
            self._contract_collision(
                now, me, task_id, v["agent"], v["task"], v["symbol"], v["caller"], v["old_sig"], v["new_sig"],
                v["change_id"],
            )
            self._brief(v["change_id"], task_id, now)

        waiting = self._q(
            """MATCH (a:Agent)-[:FLYING]->(o:Task {status: 'active'})-[c:CLAIMS]->(s:Symbol)
            WHERE s.qualname IN $callees AND a.id <> $agent AND c.lease_until > $now
                  AND coalesce(a.paused, false) = false AND NOT (a)-[:FLYING]->(:Task {status: 'holding'})
            RETURN DISTINCT a.id ORDER BY a.id""",
            {"callees": callees, "agent": me, "now": now},
        )
        # Agents read a file before they change it. A soft interest (a recent Read of the file that defines a callee)
        # counts too, so an agent that has not edited or claimed anything yet is still waited for. Waiting only:
        # interest never holds anyone's edit.
        reading = self._q(
            """MATCH (a:Agent)-[:FLYING]->(o:Task {status: 'active'})-[r:READING]->(f:File)-[:DEFINES]->(s:Symbol)
            WHERE s.qualname IN $callees AND a.id <> $agent AND r.at > $since
                  AND coalesce(a.paused, false) = false AND NOT (a)-[:FLYING]->(:Task {status: 'holding'})
            RETURN DISTINCT a.id ORDER BY a.id""",
            {"callees": callees, "agent": me, "since": now - READ_INTEREST_SECONDS},
        )
        return violations, sorted({r[0] for r in waiting} | {r[0] for r in reading})

    def note_interest_from_text(self, agent_id: str, task_id: str, text: str) -> list[str]:
        """Files of the repo a task's prompt names, directly or through a symbol defined in them.

        Recorded as the same soft interest as a Read, at the moment the agent starts, so an agent that lands early
        waits for one that has only been given its task. Returns the files noted.
        """
        tokens = {t.strip(".,:;()`'\"") for t in _TOKEN.findall(text or "")}
        tokens = {t for t in tokens if t}
        if not tokens:
            return []
        files = {r[0] for r in self._q("MATCH (f:File) RETURN f.path")}
        hit = {f for f in files if f in tokens or f.replace("/", ".")[:-3] in tokens}
        for qualname, name, file in self._q("MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN s.qualname, s.name, f.path"):
            short = qualname.rsplit(".", 2)
            dotted = ".".join(short[-2:]) if len(short) > 2 else qualname
            # Bare names count when they are distinctive enough to mean this symbol (save, url, get do not).
            if qualname in tokens or dotted in tokens or (name in tokens and (len(name) >= 6 or "_" in name)):
                hit.add(file)
        for rel in sorted(hit):
            self.note_reading(agent_id, task_id, rel)
        return sorted(hit)

    def note_reading(self, agent_id: str, task_id: str, rel: str) -> None:
        """Record that a task read a file of the repo: a soft interest that landing agents wait for."""
        self.ensure_task(agent_id, task_id)
        self._q(
            """MATCH (t:Task {id: $task}), (f:File {path: $rel})
            MERGE (t)-[r:READING]->(f)
            SET r.at = $now""",
            {"task": task_id, "rel": rel, "now": self.clock()},
        )

    def _set_status(self, task_id: str, status: str, unless: str, extra: str = "", params: dict | None = None):
        """Set the task's status unless `unless` (a Cypher condition on t) holds. Returns its agent when it changed."""
        rows = self._q(
            f"""MATCH (a:Agent)-[:FLYING]->(t:Task {{id: $task}})
            WHERE NOT ({unless})
            SET t.status = $status{extra}
            RETURN a.id LIMIT 1""",
            {"task": task_id, "status": status, **(params or {})},
        )
        return rows[0][0] if rows else None

    def holding(self, task_id: str, on_agent: str) -> None:
        """The task waits at its landing for `on_agent`. One event per wait, however often it is called."""
        agent = self._set_status(
            task_id, "holding", "t.status = 'holding' AND t.holding_for = $on", ", t.holding_for = $on",
            {"on": on_agent},
        )
        if agent is not None:
            self._event("holding", agent, task_id, on_agent)

    def land(self, task_id: str) -> None:
        """The agent stopped. Its claims stay until their leases end, and its contract changes stand."""
        now = self.clock()
        agent = self._set_status(task_id, "landed", "t.status = 'landed'", ", t.landed_at = $now", {"now": now})
        if agent is not None:
            self._event("landed", agent, task_id, "", now)

    def block_landing(self, task_id: str, fingerprint: str, caller: str) -> None:
        """The Stop hook sent the agent back to work over these violations: it is active again, and held."""
        agent = self.agent_of(task_id)
        self._q(
            "MATCH (t:Task {id: $task}) SET t.status = 'active', t.stop_block = $fp",
            {"task": task_id, "fp": fingerprint},
        )
        self._event("hold", agent, task_id, caller)

    def last_block(self, task_id: str) -> str | None:
        """The fingerprint of the violations the last blocked stop reported, if any."""
        rows = self._q("MATCH (t:Task {id: $task}) RETURN t.stop_block", {"task": task_id})
        return rows[0][0] if rows else None

    def explain(self, from_q: str, to_q: str) -> list[str]:
        # shortestPath is only allowed inside WITH or RETURN in FalkorDB.
        rows = self._q(
            f"""MATCH (a:Symbol {{qualname: $a}}), (b:Symbol {{qualname: $b}})
            WITH shortestPath((a)-[:{_DEPENDS}*..6]->(b)) AS p
            RETURN CASE WHEN p IS NULL THEN [] ELSE [n IN nodes(p) | n.qualname] END""",
            {"a": from_q, "b": to_q},
        )
        return list(rows[0][0] or []) if rows else []

    # Controls from Tower. An unknown agent is left alone: Tower may act on an agent that has already gone.

    def pause(self, agent_id: str) -> None:
        self._set_paused(agent_id, True, "paused")

    def resume(self, agent_id: str) -> None:
        self._set_paused(agent_id, False, "resumed")

    def _set_paused(self, agent_id: str, paused: bool, kind: str) -> None:
        changed = self._q(
            """MATCH (a:Agent {id: $agent}) WHERE coalesce(a.paused, false) <> $paused
            SET a.paused = $paused RETURN a.id""",
            {"agent": agent_id, "paused": paused},
        )
        if changed:
            self._event(kind, agent_id, None, "Tower")

    def message(self, agent_id: str, text: str, sender: str = "Tower") -> str:
        """Queue a message for the agent's next hook. Returns its id, or "" when the agent is unknown."""
        mid = uuid.uuid4().hex
        now = self.clock()
        rows = self._q(
            f"""MATCH (a:Agent {{id: $agent}})
            {_NEXT_SEQ}
            CREATE (m:Message {{id: $id, text: $text, sender: $sender, at: $now, seq: n.value}})-[:TO]->(a)
            RETURN m.id""",
            {"seq_name": "message", "agent": agent_id, "id": mid, "text": text, "sender": sender, "now": now},
        )
        if not rows:
            return ""
        self._event("message", agent_id, None, sender, now)
        return mid

    def pending_messages(self, agent_id: str, task_id: str | None = None) -> list[str]:
        """Undelivered message text for the agent, oldest first. Each message is returned once.

        Delivery is recorded on the task that receives it: task_id when given, else the agent's newest active task.
        """
        now = self.clock()
        if task_id is None:
            rows = self._q(
                """MATCH (:Agent {id: $agent})-[:FLYING]->(t:Task {status: 'active'})
                RETURN t.id ORDER BY t.started_at DESC LIMIT 1""",
                {"agent": agent_id},
            )
            task_id = rows[0][0] if rows else ""
        # Marked and read in one query, so two hook processes cannot both deliver the same message.
        rows = self._q(
            """MATCH (m:Message)-[:TO]->(:Agent {id: $agent}) WHERE m.delivered_at IS NULL
            SET m.delivered_at = $now
            WITH m
            OPTIONAL MATCH (t:Task {id: $task})
            FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | CREATE (m)-[:DELIVERED {at: $now}]->(t))
            RETURN m.text, m.seq ORDER BY m.at, m.seq""",
            {"agent": agent_id, "task": task_id, "now": now},
        )
        return [r[0] for r in rows]

    def release_collision(self, collision_id: str) -> bool:
        """Let the held side through. False when the collision is unknown or no longer held."""
        now = self.clock()
        rows = self._q(
            """MATCH (x:Collision {id: $id, resolution: 'held'})
            SET x.resolution = 'released', x.released_at = $now
            RETURN x.kind, x.held_agent, x.held_task, x.symbol""",
            {"id": collision_id, "now": now},
        )
        if not rows:
            return False
        kind, held_agent, held_task, symbol = rows[0]
        if kind == "contract":
            # The held task now counts as briefed on every change to that contract, and released from it, so its
            # retry is cleared whether or not the call fits.
            self._q(
                """MATCH (a:Agent)-[:FLYING]->(:Task)-[:CHANGED]->(cc:ContractChange {qualname: $q})
                MATCH (t:Task {id: $task})
                WHERE a.id <> $agent
                MERGE (cc)-[b:BRIEFED]->(t)
                ON CREATE SET b.at = $now
                SET b.released = true""",
                {"q": symbol, "task": held_task, "agent": held_agent, "now": now},
            )
        else:
            # A one-time pass past the claim rule, valid for one lease.
            self._q(
                """MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
                MERGE (t)-[p:PASS]->(s)
                SET p.until = $until""",
                {"task": held_task, "q": symbol, "until": now + self.lease_seconds},
            )
        self._event("released", held_agent, held_task, symbol, now)
        return True

    # Event log

    def _event(self, kind: str, agent: str | None, task: str | None, code: str, now: float | None = None) -> None:
        self._q(
            f"""{_NEXT_SEQ}
            CREATE (:Event {{id: $id, at: $at, seq: n.value, kind: $kind, agent: $agent, task: $task,
                    text: $text, code: $code}})""",
            {"seq_name": "event", "id": uuid.uuid4().hex, "at": self.clock() if now is None else now, "kind": kind,
             "agent": agent, "task": task, "text": text.EVENT_TEXT[kind], "code": code},
        )

    def events(self, since: float = 0.0, limit: int = 200) -> list[dict]:
        """Events strictly after `since`, oldest first."""
        rows = self._q(
            """MATCH (e:Event) WHERE e.at > $since
            RETURN e.id, e.at, e.kind, e.agent, e.task, e.text, e.code
            ORDER BY e.at, e.seq LIMIT $limit""",
            {"since": float(since), "limit": int(limit)},
        )
        keys = ("id", "at", "kind", "agent", "task", "text", "code")
        return [dict(zip(keys, r)) for r in rows]

    # Read models. Shapes are the API contract; the API serves them verbatim.

    def _live_claims(self, now: float) -> dict[str, list[tuple[str, float]]]:
        """agent id -> [(qualname, claimed at)] for live claims of tasks that have not been released."""
        rows = self._q(
            """MATCH (a:Agent)-[:FLYING]->(t:Task)-[c:CLAIMS]->(s:Symbol)
            WHERE c.lease_until > $now AND t.status IN $standing
            RETURN a.id, s.qualname, max(coalesce(c.at, 0.0))""",
            {"now": now, "standing": _STANDING},
        )
        claims: dict[str, list[tuple[str, float]]] = {}
        for agent, q, at in rows:
            claims.setdefault(agent, []).append((q, float(at)))
        return claims

    def state(self) -> dict:
        now = self.clock()
        rows = self._q(
            """MATCH (a:Agent)
            OPTIONAL MATCH (a)-[:FLYING]->(t:Task)
            RETURN a.id, coalesce(a.paused, false), t.id, t.status
            ORDER BY a.id, t.started_at, t.id"""
        )
        claims = self._live_claims(now)
        held = {r[0] for r in self._q("MATCH (x:Collision {resolution: 'held'}) RETURN DISTINCT x.held_agent")}
        agents: dict[str, dict] = {}
        for agent, paused, task, status in rows:
            entry = agents.setdefault(agent, {
                "id": agent, "paused": bool(paused), "status": "released", "tasks": [],
                "claims": sorted({q for q, _ in claims.get(agent, [])}), "held": agent in held,
            })
            if task is not None:
                entry["tasks"].append(task)
                # The liveliest task names the agent: active, then holding, then landed, then released.
                if status in _STANDING and (
                    entry["status"] == "released" or _STANDING.index(status) < _STANDING.index(entry["status"])
                ):
                    entry["status"] = status
        collisions = self._q(
            f"""MATCH (x:Collision)
            RETURN x.id, x.at, x.kind, x.symbol, x.held_agent, x.owner_agent, x.resolution
            ORDER BY x.at DESC, x.seq DESC LIMIT {_STATE_COLLISIONS}"""
        )
        keys = ("id", "at", "kind", "symbol", "held_agent", "owner_agent", "resolution")
        return {
            "now": now,
            "agents": list(agents.values()),
            "collisions": [dict(zip(keys, r)) for r in collisions],
        }

    def radar(self) -> dict:
        now = self.clock()
        # Holding and landed agents stay on the radar until more recently active agents take their place.
        active = [r[0] for r in self._q(
            "MATCH (a:Agent)-[:FLYING]->(t:Task) WHERE t.status IN $standing RETURN DISTINCT a.id ORDER BY a.id",
            {"standing": _STANDING},
        )]
        claims = self._live_claims(now)
        last_event = dict(self._q(
            "MATCH (e:Event) WHERE e.agent IN $agents RETURN e.agent, max(e.at)", {"agents": active}
        )) if active else {}

        def activity(agent: str) -> float:
            claimed = [at for _, at in claims.get(agent, [])]
            return max([float(last_event.get(agent) or 0.0)] + claimed)

        shown = sorted(active, key=lambda a: (-activity(a), a))[:_RADAR_AGENTS]
        agents = []
        names: set[str] = set()
        for agent in shown:
            mine = sorted(claims.get(agent, []), key=lambda c: (-c[1], c[0]))
            claimed = sorted(q for q, _ in mine)
            cone = self._cone_hops(agent, now, set(claimed))
            agents.append({
                "id": agent,
                "center": mine[0][0] if mine else None,
                "claims": claimed,
                "cone": [{"qualname": q, "hop": hop} for q, hop in cone],
            })
            names.update(claimed)
            names.update(q for q, _ in cone)

        collision = self._q(
            """MATCH (x:Collision)
            RETURN x.id, x.symbol, x.caller, x.held_agent, x.owner_agent, x.resolution
            ORDER BY CASE WHEN x.resolution = 'held' THEN 0 ELSE 1 END, x.at DESC, x.seq DESC LIMIT 1"""
        )
        radar_collision = None
        if collision:
            radar_collision = dict(zip(("id", "symbol", "caller", "held_agent", "owner_agent", "resolution"), collision[0]))
            names.update(q for q in (radar_collision["symbol"], radar_collision["caller"]) if q)

        symbols = {}
        edges: list[list[str]] = []
        if names:
            for q, kind, is_test in self._q(
                "MATCH (s:Symbol) WHERE s.qualname IN $names RETURN s.qualname, s.kind, s.is_test",
                {"names": sorted(names)},
            ):
                symbols[q] = {"label": _label(q, kind), "kind": kind, "is_test": bool(is_test)}
            edges = [list(r) for r in self._q(
                f"""MATCH (a:Symbol)-[:{_DEPENDS}]->(b:Symbol)
                WHERE a.qualname IN $names AND b.qualname IN $names
                RETURN DISTINCT a.qualname, b.qualname ORDER BY a.qualname, b.qualname""",
                {"names": sorted(names)},
            )]
        return {"agents": agents, "symbols": symbols, "edges": edges, "collision": radar_collision}

    def _cone_hops(self, agent: str, now: float, claimed: set[str]) -> list[tuple[str, int]]:
        """(qualname, hops to the nearest of the agent's claims), nearest first."""
        rows = self._q(
            f"""MATCH (a:Agent {{id: $agent}})-[:FLYING]->(t:Task)-[:CONE]->(d:Symbol)
            WHERE t.status IN $standing
            MATCH (a)-[:FLYING]->(u:Task)-[c:CLAIMS]->(s:Symbol)
            WHERE c.lease_until > $now AND u.status IN $standing
            WITH d, s, shortestPath((d)-[:{_DEPENDS}*1..{self.cone_depth}]->(s)) AS p
            WHERE p IS NOT NULL
            RETURN d.qualname, min(length(p))""",
            {"agent": agent, "now": now, "standing": _STANDING},
        )
        hops = [(q, int(h)) for q, h in rows if q not in claimed]
        return sorted(hops, key=lambda x: (x[1], x[0]))

    def collision(self, collision_id: str) -> dict | None:
        rows = self._q(f"MATCH (x:Collision {{id: $id}}) RETURN {_COLLISION_FIELDS}", {"id": collision_id})
        if not rows:
            return None
        keys = ("id", "at", "kind", "symbol", "caller", "held_agent", "held_task", "owner_agent", "owner_task",
                "old_sig", "new_sig", "resolution")
        detail = dict(zip(keys, rows[0]))
        detail["path"] = [detail["caller"], detail["symbol"]] if detail["caller"] else [detail["symbol"]]
        order = ("id", "at", "kind", "symbol", "caller", "path", "held_agent", "held_task", "owner_agent",
                 "owner_task", "old_sig", "new_sig", "resolution")
        return {k: detail[k] for k in order}

    def insights(self) -> dict:
        return {
            "hot_zones": memory.hot_zones(self.graph),
            "parallel_groups": memory.parallel_groups(self.graph, self.clock()),
        }
