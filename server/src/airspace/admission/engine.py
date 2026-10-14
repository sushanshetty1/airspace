"""The admission engine: flight plans, leases, impact cones, clearance, contract changes and briefings.

Every decision is deterministic Cypher plus the rules in check_edit. All state lives in the FalkorDB graph,
so any number of hook processes can share one Airspace view of the repo.
"""

import time
import uuid
from typing import Callable

from airspace.admission import text
from airspace.graph.db import ensure_schema
from airspace.types import Briefing, SignatureChange, Verdict

# Edges along which a change to one symbol can break another. Read as "dependent -> dependency".
_DEPENDS = "CALLS|COVERS|INHERITS"

# Atomic lease. Writes to one graph are serialised, so check-and-set in one query cannot race.
# Every node is matched before the count: a MATCH after an aggregation loses rows in FalkorDB.
_LEASE = """
MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
OPTIONAL MATCH (o:Task)-[c:CLAIMS]->(s) WHERE o.id <> $task AND c.lease_until > $now
WITH t, s, count(c) AS held
WHERE held = 0
MERGE (t)-[k:CLAIMS]->(s)
SET k.lease_until = $now + $ttl, k.fence = coalesce(k.fence, 0) + 1
RETURN k.fence
"""


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
            MERGE (t:Task {id: $task})
            ON CREATE SET t.started_at = $now, t.intent = $intent
            SET t.status = 'active', t.intent = CASE WHEN $intent = '' THEN coalesce(t.intent, '') ELSE $intent END
            MERGE (a)-[:FLYING]->(t)""",
            {"agent": agent_id, "task": task_id, "intent": intent, "now": self.clock()},
        )

    def _ensure_known(self, task_id: str) -> None:
        if self.agent_of(task_id) is None:
            self.ensure_task(task_id, task_id)

    def agent_of(self, task_id: str) -> str | None:
        rows = self._q("MATCH (a:Agent)-[:FLYING]->(:Task {id: $task}) RETURN a.id LIMIT 1", {"task": task_id})
        return rows[0][0] if rows else None

    def claim(self, task_id: str, qualnames: list[str]) -> list[str]:
        held = []
        now = self.clock()
        for q in dict.fromkeys(qualnames):
            if self._q(_LEASE, {"task": task_id, "q": q, "now": now, "ttl": self.lease_seconds}):
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
        self._q("MATCH (:Task {id: $task})-[k:CLAIMS|CONE]->() DELETE k", {"task": task_id})
        self._q(
            "MATCH (t:Task {id: $task}) SET t.status = 'released', t.released_at = $now",
            {"task": task_id, "now": self.clock()},
        )

    # Clearance

    def check_edit(self, task_id: str, touched: list[str], new_calls: list[tuple[str, str]]) -> Verdict:
        self._ensure_known(task_id)
        now = self.clock()

        # Rule 1: a new call into a contract another active task is changing, not yet briefed to this task.
        for caller, callee in new_calls:
            rows = self._q(
                """MATCH (me:Task {id: $task})
                MATCH (o:Task {status: 'active'})-[:CHANGED]->(cc:ContractChange)-[:ON]->(:Symbol {qualname: $callee})
                WHERE o.id <> $task AND NOT (cc)-[:BRIEFED]->(me)
                OPTIONAL MATCH (a:Agent)-[:FLYING]->(o)
                RETURN cc.id, cc.qualname, cc.old_sig, cc.new_sig, o.id, a.id
                ORDER BY cc.at""",
                {"task": task_id, "callee": callee},
            )
            if not rows:
                continue
            briefings = [Briefing(r[0], r[1], r[2], r[3], r[5] or r[4]) for r in rows]
            for b in briefings:
                self._brief(b.id, task_id, now)
            other_task, other_agent = rows[-1][4], rows[-1][5] or rows[-1][4]
            reason = text.contract_hold(
                callee, caller, other_agent, briefings[0].old_signature, briefings[-1].new_signature
            )
            return Verdict(
                kind="hold",
                reason=reason,
                path=[caller, callee],
                other_agent=other_agent,
                collision_id=self._collide(task_id, other_task, callee, "contract", now),
                briefings=briefings,
            )

        # Rule 2: a touched symbol another active task holds under a live lease.
        for q in dict.fromkeys(touched):
            rows = self._q(
                """MATCH (o:Task {status: 'active'})-[c:CLAIMS]->(:Symbol {qualname: $q})
                WHERE o.id <> $task AND c.lease_until > $now
                OPTIONAL MATCH (a:Agent)-[:FLYING]->(o)
                RETURN o.id, a.id LIMIT 1""",
                {"task": task_id, "q": q, "now": now},
            )
            if not rows:
                continue
            other_task, other_agent = rows[0][0], rows[0][1] or rows[0][0]
            return Verdict(
                kind="hold",
                reason=text.claim_hold(q, other_agent, other_task),
                path=[q],
                other_agent=other_agent,
                collision_id=self._collide(task_id, other_task, q, "claim", now),
            )

        # Rule 3: cleared. Dynamic scope: whatever the task touches becomes its claim if free.
        self.claim(task_id, touched)
        self.refresh_cone(task_id)
        return Verdict(kind="cleared", reason="")

    def _brief(self, change_id: str, task_id: str, now: float) -> None:
        self._q(
            """MATCH (cc:ContractChange {id: $id}), (t:Task {id: $task})
            MERGE (cc)-[b:BRIEFED]->(t)
            ON CREATE SET b.at = $now""",
            {"id": change_id, "task": task_id, "now": now},
        )

    def _collide(self, task_id: str, other_task: str, qualname: str, kind: str, now: float) -> str:
        # Append-only: collisions are history the planner learns hot zones from.
        cid = uuid.uuid4().hex
        self._q(
            """MATCH (me:Task {id: $task}), (o:Task {id: $other}), (s:Symbol {qualname: $q})
            CREATE (x:Collision {id: $id, at: $now, kind: $kind, resolution: 'held'})
            CREATE (x)-[:BETWEEN]->(me), (x)-[:BETWEEN]->(o), (x)-[:AT]->(s)""",
            {"task": task_id, "other": other_task, "q": qualname, "id": cid, "now": now, "kind": kind},
        )
        return cid

    # Contract changes and briefings

    def record_changes(self, task_id: str, changes: list[SignatureChange]) -> list[str]:
        self._ensure_known(task_id)
        ids = []
        for ch in changes:
            rows = self._q(
                """MATCH (t:Task {id: $task}), (s:Symbol {qualname: $q})
                CREATE (cc:ContractChange {id: $id, qualname: $q, old_sig: $old, new_sig: $new, at: $now})
                CREATE (t)-[:CHANGED]->(cc), (cc)-[:ON]->(s)
                RETURN cc.id""",
                {"task": task_id, "q": ch.qualname, "id": uuid.uuid4().hex, "old": ch.old_signature,
                 "new": ch.new_signature, "now": self.clock()},
            )
            ids.extend(r[0] for r in rows)
        return ids

    def pending_briefings(self, task_id: str) -> list[Briefing]:
        now = self.clock()
        rows = self._q(
            f"""MATCH (me:Task {{id: $task}})-[c:CLAIMS]->(mine:Symbol) WHERE c.lease_until > $now
            MATCH (mine)-[:{_DEPENDS}*1..{self.cone_depth}]->(s:Symbol)<-[:ON]-(cc:ContractChange)<-[:CHANGED]-(o:Task)
            WHERE o.id <> $task AND NOT (cc)-[:BRIEFED]->(me)
            OPTIONAL MATCH (a:Agent)-[:FLYING]->(o)
            RETURN DISTINCT cc.id, cc.qualname, cc.old_sig, cc.new_sig, coalesce(a.id, o.id), cc.at
            ORDER BY cc.at""",
            {"task": task_id, "now": now},
        )
        briefings = []
        for r in rows:
            if any(b.id == r[0] for b in briefings):
                continue
            self._brief(r[0], task_id, now)
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
