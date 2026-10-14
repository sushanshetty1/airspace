"""The admission engine: flight plans, leases, impact cones, clearance, contract changes and briefings.

Every decision is deterministic Cypher plus the rules in check_edit. All state lives in the FalkorDB graph,
so any number of hook processes can share one Airspace view of the repo. That includes what Tower controls
(paused agents, messages, released holds), the append-only Event log and the read models Tower renders.

Agents are the unit of conflict. One agent can fly several tasks (a task per Claude session from the hooks,
"<agent>:mcp" from the MCP server), and an agent's own tasks never hold each other.
"""

import time
import uuid
from typing import Callable

from airspace.admission import insights as memory
from airspace.admission import text
from airspace.graph.db import ensure_schema
from airspace.types import Briefing, SignatureChange, Verdict

# Edges along which a change to one symbol can break another. Read as "dependent -> dependency".
_DEPENDS = "CALLS|COVERS|INHERITS"

# Atomic lease. Writes to one graph are serialised, so check-and-set in one query cannot race.
# Every node is matched before the count: a MATCH after an aggregation loses rows in FalkorDB.
# Only another agent's live claim blocks; the agent's other tasks may hold the same symbol.
_LEASE = """
MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
OPTIONAL MATCH (oa:Agent)-[:FLYING]->(:Task)-[c:CLAIMS]->(s) WHERE oa.id <> $agent AND c.lease_until > $now
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


def _label(qualname: str, kind: str | None) -> str:
    parts = qualname.split(".")
    # A method reads better with its class: "Post.save", not "save".
    return ".".join(parts[-2:]) if kind == "method" and len(parts) > 1 else parts[-1]


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
        # A task that edits again is flying again, so a released task becomes active on its next edit.
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

    def check_edit(self, task_id: str, touched: list[str], new_calls: list[tuple[str, str]]) -> Verdict:
        me = self._ensure_known(task_id)
        now = self.clock()
        touched = list(dict.fromkeys(touched))
        callees = [callee for _, callee in new_calls]
        subject = touched[0] if touched else (new_calls[0][0] if new_calls else "")

        # Rule 0: an agent paused from Tower is held whatever it edits.
        if self._q("MATCH (a:Agent {id: $agent}) WHERE a.paused = true RETURN a.id", {"agent": me}):
            self._event("hold", me, task_id, subject, now)
            return Verdict(kind="hold", reason=text.paused_hold(me))

        # Rule 1: a new call into a contract another agent's active task is changing, not yet briefed to this task.
        for caller, callee in new_calls:
            rows = self._q(
                """MATCH (me:Task {id: $task})
                MATCH (a:Agent)-[:FLYING]->(o:Task {status: 'active'})-[:CHANGED]->(cc:ContractChange)
                      -[:ON]->(:Symbol {qualname: $callee})
                WHERE a.id <> $agent AND NOT (cc)-[:BRIEFED]->(me)
                RETURN cc.id, cc.qualname, cc.old_sig, cc.new_sig, o.id, a.id
                ORDER BY cc.at""",
                {"task": task_id, "agent": me, "callee": callee},
            )
            if not rows:
                continue
            briefings = [Briefing(r[0], r[1], r[2], r[3], r[5]) for r in rows]
            for b in briefings:
                self._brief(b.id, task_id, now)
            other_task, other_agent = rows[-1][4], rows[-1][5]
            old_sig, new_sig = briefings[0].old_signature, briefings[-1].new_signature
            cid = self._collide(
                "contract", now, me, task_id, other_agent, other_task, callee,
                caller=caller, old_sig=old_sig, new_sig=new_sig,
            )
            self._event("hold", me, task_id, caller, now)
            self._event("briefed", me, task_id, callee, now)
            return Verdict(
                kind="hold",
                reason=text.contract_hold(callee, caller, other_agent, old_sig, new_sig),
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
        # Dynamic scope: whatever the task touches becomes its claim if free.
        self._claim(task_id, touched)
        self.refresh_cone(task_id)
        if subject:
            self._event("cleared", me, task_id, subject, now)
        self._resolve(me, task_id, touched + [caller for caller, _ in new_calls] + callees, now)
        return Verdict(kind="cleared", reason="")

    def _resolve(self, agent: str, task_id: str, qualnames: list[str], now: float) -> None:
        # A cleared edit by the held task on the contested symbol means the collision has been worked out.
        if not qualnames:
            return
        rows = self._q(
            """MATCH (x:Collision {held_task: $task, resolution: 'held'})
            WHERE x.symbol IN $qs OR x.caller IN $qs
            SET x.resolution = 'resolved', x.resolved_at = $now
            RETURN x.symbol ORDER BY x.at, x.seq""",
            {"task": task_id, "qs": list(dict.fromkeys(qualnames)), "now": now},
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
    ) -> str:
        # Append-only: collisions are history the planner learns hot zones from.
        cid = uuid.uuid4().hex
        self._q(
            f"""MATCH (me:Task {{id: $held_task}}), (o:Task {{id: $owner_task}}), (s:Symbol {{qualname: $symbol}})
            {_NEXT_SEQ}
            CREATE (x:Collision {{id: $id, at: $now, seq: n.value, kind: $kind, resolution: 'held',
                    held_agent: $held_agent, held_task: $held_task, owner_agent: $owner_agent, owner_task: $owner_task,
                    symbol: $symbol, caller: $caller, old_sig: $old_sig, new_sig: $new_sig}})
            CREATE (x)-[:BETWEEN]->(me), (x)-[:BETWEEN]->(o), (x)-[:AT]->(s)""",
            {"seq_name": "collision", "id": cid, "now": now, "kind": kind, "held_agent": held_agent,
             "held_task": held_task, "owner_agent": owner_agent, "owner_task": owner_task, "symbol": symbol,
             "caller": caller, "old_sig": old_sig, "new_sig": new_sig},
        )
        return cid

    # Contract changes and briefings

    def record_changes(self, task_id: str, changes: list[SignatureChange]) -> list[str]:
        agent = self._ensure_known(task_id)
        ids = []
        for ch in changes:
            now = self.clock()
            rows = self._q(
                """MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
                CREATE (cc:ContractChange {id: $id, qualname: $q, old_sig: $old, new_sig: $new, at: $now})
                CREATE (t)-[:CHANGED]->(cc), (cc)-[:ON]->(s)
                RETURN cc.id""",
                {"task": task_id, "q": ch.qualname, "id": uuid.uuid4().hex, "old": ch.old_signature,
                 "new": ch.new_signature, "now": now},
            )
            if rows:
                self._event("contract", agent, task_id, ch.qualname, now)
            ids.extend(r[0] for r in rows)
        return ids

    def pending_briefings(self, task_id: str) -> list[Briefing]:
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
        briefings = []
        for r in rows:
            if any(b.id == r[0] for b in briefings):
                continue
            self._brief(r[0], task_id, now)
            self._event("briefed", agent, task_id, r[1], now)
            briefings.append(Briefing(r[0], r[1], r[2], r[3], r[4]))
        return briefings

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
            # The held task now counts as briefed on every change to that contract, so its retry is cleared.
            self._q(
                """MATCH (a:Agent)-[:FLYING]->(:Task)-[:CHANGED]->(cc:ContractChange)-[:ON]->(:Symbol {qualname: $q})
                MATCH (t:Task {id: $task})
                WHERE a.id <> $agent
                MERGE (cc)-[b:BRIEFED]->(t)
                ON CREATE SET b.at = $now""",
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
        """agent id -> [(qualname, claimed at)] for live claims of active tasks."""
        rows = self._q(
            """MATCH (a:Agent)-[:FLYING]->(:Task {status: 'active'})-[c:CLAIMS]->(s:Symbol)
            WHERE c.lease_until > $now
            RETURN a.id, s.qualname, max(coalesce(c.at, 0.0))""",
            {"now": now},
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
                if status == "active":
                    entry["status"] = "active"
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
        active = memory.active_agents(self.graph)
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
            f"""MATCH (a:Agent {{id: $agent}})-[:FLYING]->(:Task {{status: 'active'}})-[:CONE]->(d:Symbol)
            MATCH (a)-[:FLYING]->(:Task {{status: 'active'}})-[c:CLAIMS]->(s:Symbol)
            WHERE c.lease_until > $now
            WITH d, s, shortestPath((d)-[:{_DEPENDS}*1..{self.cone_depth}]->(s)) AS p
            WHERE p IS NOT NULL
            RETURN d.qualname, min(length(p))""",
            {"agent": agent, "now": now},
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
