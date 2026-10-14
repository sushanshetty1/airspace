"""The accounts graph: users signed in with GitHub, the workspaces they own and each workspace's key.

    (:User {id, github_id, login, name, avatar_url, created_at})
    (:User)-[:OWNS]->(:Workspace {id, name, graph, created_at})
    (:Workspace)-[:HAS_KEY]->(:Key {hash, prefix, created_at, last_used_at})

Accounts live in their own graph (airspace_accounts unless AIRSPACE_ACCOUNTS_GRAPH says otherwise), apart from the
workspace graphs (ws_<id>) the engine writes, so a workspace can be deleted by deleting its graph. A key is only
ever stored as its SHA-256 hash: the server cannot show it again, so rotating is the way to get a new one.
"""

import hashlib
import logging
import os
import secrets
import time
from collections.abc import Callable

log = logging.getLogger("airspace.cloud")

ACCOUNTS_GRAPH = "airspace_accounts"
ENV_GRAPH = "AIRSPACE_ACCOUNTS_GRAPH"
MAX_WORKSPACES = 5
MAX_NAME = 60
KEY_PREFIX = "ask_"
# last_used_at is a hint for the owner, so one write a minute per key is plenty.
_TOUCH_SECONDS = 60

_INDEXES = [("User", "id"), ("User", "github_id"), ("Workspace", "id"), ("Key", "hash")]


class LimitReached(Exception):
    pass


def accounts_graph_name() -> str:
    return os.environ.get(ENV_GRAPH, "").strip() or ACCOUNTS_GRAPH


def workspace_graph_name(workspace_id: str) -> str:
    return f"ws_{workspace_id}"


def new_key() -> str:
    return KEY_PREFIX + secrets.token_hex(20)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def looks_like_key(key: str) -> bool:
    body = key[len(KEY_PREFIX):]
    return key.startswith(KEY_PREFIX) and len(body) == 40 and all(c in "0123456789abcdef" for c in body)


def clean_name(name: str) -> str:
    """The workspace name, trimmed. Raises ValueError unless it is 1 to 60 characters on one line."""
    name = " ".join((name or "").split())
    if not 1 <= len(name) <= MAX_NAME:
        raise ValueError(f"A workspace name is 1 to {MAX_NAME} characters.")
    return name


class Accounts:
    """Users, workspaces and keys. `db` is a FalkorDB client; the accounts graph is created on first use."""

    def __init__(self, db, graph_name: str | None = None, clock: Callable[[], float] = time.time):
        self.db = db
        self.graph = db.select_graph(graph_name or accounts_graph_name())
        self.clock = clock

    def _q(self, cypher: str, params: dict | None = None) -> list[list]:
        return self.graph.query(cypher, params or {}).result_set

    def _now(self) -> float:
        # Milliseconds survive FalkorDB's float formatting, so a time read back equals the time written.
        return round(self.clock(), 3)

    def ensure_schema(self) -> None:
        """Range indexes on every property a lookup starts from. Safe to call repeatedly."""
        existing = set()
        try:
            for label, props in self._q("CALL db.indexes() YIELD label, properties RETURN label, properties"):
                existing.update((label, p) for p in props)
        except Exception:
            # A brand-new graph has no key yet; creating the first index creates it.
            pass
        for label, prop in _INDEXES:
            if (label, prop) not in existing:
                try:
                    self._q(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
                except Exception as e:  # another process created it first
                    if "already indexed" not in str(e).lower():
                        raise

    # Users

    def upsert_user(self, profile: dict) -> str:
        """The user for a GitHub profile ({id, login, name, avatar_url}), created on first sign-in. Returns its id."""
        rows = self._q(
            """MERGE (u:User {github_id: $gid})
            ON CREATE SET u.id = $id, u.created_at = $now
            SET u.login = $login, u.name = $name, u.avatar_url = $avatar
            RETURN u.id""",
            {
                "gid": int(profile["id"]),
                "id": secrets.token_hex(8),
                "now": self._now(),
                "login": str(profile.get("login") or ""),
                "name": str(profile.get("name") or profile.get("login") or ""),
                "avatar": str(profile.get("avatar_url") or ""),
            },
        )
        return rows[0][0]

    def user(self, user_id: str) -> dict | None:
        rows = self._q(
            "MATCH (u:User {id: $id}) RETURN u.login, u.name, u.avatar_url", {"id": user_id}
        )
        if not rows:
            return None
        login, name, avatar = rows[0]
        return {"login": login, "name": name, "avatar_url": avatar}

    # Workspaces

    def agents_flying(self, workspace_id: str) -> int:
        """Active tasks in the workspace graph. A graph that is gone or unreadable counts as none flying."""
        graph = self.db.select_graph(workspace_graph_name(workspace_id))
        try:
            rows = graph.query("MATCH (t:Task {status: 'active'}) RETURN count(t)").result_set
        except Exception as e:
            log.warning("airspace: agents flying unknown for %s (%s)", workspace_id, type(e).__name__)
            return 0
        return int(rows[0][0]) if rows else 0

    def _view(self, row: list) -> dict:
        wid, name, created_at, prefix = row
        return {
            "id": wid,
            "name": name,
            "created_at": created_at,
            "key_prefix": prefix,
            "agents_flying": self.agents_flying(wid),
        }

    def workspaces(self, user_id: str) -> list[dict]:
        rows = self._q(
            """MATCH (:User {id: $user})-[:OWNS]->(w:Workspace)
            OPTIONAL MATCH (w)-[:HAS_KEY]->(k:Key)
            RETURN w.id, w.name, w.created_at, k.prefix
            ORDER BY w.created_at, w.id""",
            {"user": user_id},
        )
        return [self._view(r) for r in rows]

    def workspace(self, user_id: str, workspace_id: str) -> dict | None:
        """The workspace when this user owns it, else None: a foreign workspace looks the same as a missing one."""
        rows = self._q(
            """MATCH (:User {id: $user})-[:OWNS]->(w:Workspace {id: $ws})
            OPTIONAL MATCH (w)-[:HAS_KEY]->(k:Key)
            RETURN w.id, w.name, w.created_at, k.prefix""",
            {"user": user_id, "ws": workspace_id},
        )
        return self._view(rows[0]) if rows else None

    def create_workspace(self, user_id: str, name: str) -> tuple[dict, str] | None:
        """(workspace, key) for a new workspace, or None when the user does not exist.

        Raises ValueError for a bad name and LimitReached at MAX_WORKSPACES. The count and the create are one
        query, and writes to one graph are serialised, so two requests at once cannot pass the limit.
        """
        name = clean_name(name)
        key = new_key()
        wid = secrets.token_hex(6)
        now = self._now()
        rows = self._q(
            """MATCH (u:User {id: $user})
            OPTIONAL MATCH (u)-[:OWNS]->(w:Workspace)
            WITH u, count(w) AS n
            WHERE n < $max
            CREATE (u)-[:OWNS]->(ws:Workspace {id: $id, name: $name, graph: $graph, created_at: $now})
                  -[:HAS_KEY]->(:Key {hash: $hash, prefix: $prefix, created_at: $now})
            RETURN ws.id""",
            {
                "user": user_id, "max": MAX_WORKSPACES, "id": wid, "name": name, "graph": workspace_graph_name(wid),
                "now": now, "hash": key_hash(key), "prefix": key[:12],
            },
        )
        if not rows:
            if not self._q("MATCH (u:User {id: $user}) RETURN u.id", {"user": user_id}):
                return None
            raise LimitReached(f"You have {MAX_WORKSPACES} workspaces, the most allowed. Delete one first.")
        # Create the graph and its indexes now, so it exists before the first agent flies.
        from airspace.graph.db import ensure_schema

        ensure_schema(self.db.select_graph(workspace_graph_name(wid)))
        workspace = {"id": wid, "name": name, "created_at": now, "key_prefix": key[:12], "agents_flying": 0}
        return workspace, key

    def rotate_key(self, user_id: str, workspace_id: str) -> str | None:
        """A new key for the workspace, replacing the old one, or None when the user does not own it."""
        key = new_key()
        h = key_hash(key)
        rows = self._q(
            """MATCH (:User {id: $user})-[:OWNS]->(w:Workspace {id: $ws})
            CREATE (w)-[:HAS_KEY]->(:Key {hash: $hash, prefix: $prefix, created_at: $now})
            RETURN w.id""",
            {"user": user_id, "ws": workspace_id, "hash": h, "prefix": key[:12], "now": self._now()},
        )
        if not rows:
            return None
        self._q(
            "MATCH (:Workspace {id: $ws})-[:HAS_KEY]->(k:Key) WHERE k.hash <> $hash DETACH DELETE k",
            {"ws": workspace_id, "hash": h},
        )
        return key

    def delete_workspace(self, user_id: str, workspace_id: str) -> bool:
        """Delete the workspace, its key and its graph. False when the user does not own it."""
        if self.workspace(user_id, workspace_id) is None:
            return False
        # The key goes first, so nothing can write to the graph while it is being deleted.
        self._q("MATCH (:Workspace {id: $ws})-[:HAS_KEY]->(k:Key) DETACH DELETE k", {"ws": workspace_id})
        self._q("MATCH (w:Workspace {id: $ws}) DETACH DELETE w", {"ws": workspace_id})
        try:
            self.db.select_graph(workspace_graph_name(workspace_id)).delete()
        except Exception as e:
            log.warning("airspace: graph for workspace %s not deleted (%s)", workspace_id, e)
        return True

    # Keys

    def workspace_for_key(self, key: str) -> dict | None:
        """{id, name, graph} of the workspace this key opens, or None for an unknown or malformed key."""
        if not looks_like_key(key):
            return None
        h = key_hash(key)
        rows = self._q(
            "MATCH (w:Workspace)-[:HAS_KEY]->(k:Key {hash: $hash}) RETURN w.id, w.name, w.graph, k.last_used_at",
            {"hash": h},
        )
        if not rows:
            return None
        wid, name, graph, last_used = rows[0]
        now = self._now()
        if last_used is None or now - last_used >= _TOUCH_SECONDS:
            self._q("MATCH (k:Key {hash: $hash}) SET k.last_used_at = $now", {"hash": h, "now": now})
        return {"id": wid, "name": name, "graph": graph}
