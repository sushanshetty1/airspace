"""The hosted side of Airspace: GitHub sign-in, workspaces, and the RPC endpoint remote hooks call.

A Cloud holds what the routes share: the configuration from the environment, one FalkorDB client (opened on first
use, so the server starts while FalkorDB is still coming up), the accounts graph and one engine per workspace.
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("airspace.cloud")

_CONNECT_TIMEOUT = 2.0
_SOCKET_TIMEOUT = 10.0
_MIN_SECRET = 32
# Engines are cheap (a graph handle), but a long-running server should not keep one for every workspace ever seen.
_MAX_ENGINES = 500


@dataclass(frozen=True)
class CloudConfig:
    github_client_id: str = ""
    github_client_secret: str = ""
    secret: str = ""
    public_url: str = ""
    accounts_graph: str = ""

    @classmethod
    def from_env(cls) -> "CloudConfig":
        from airspace.cloud.accounts import accounts_graph_name

        env = os.environ
        return cls(
            github_client_id=env.get("GITHUB_CLIENT_ID", "").strip(),
            github_client_secret=env.get("GITHUB_CLIENT_SECRET", "").strip(),
            secret=env.get("AIRSPACE_SECRET", "").strip(),
            public_url=env.get("AIRSPACE_PUBLIC_URL", "").strip().rstrip("/"),
            accounts_graph=accounts_graph_name(),
        )

    @property
    def sessions(self) -> bool:
        """Whether session cookies can be signed and checked: a secret long enough to trust."""
        return len(self.secret.encode()) >= _MIN_SECRET

    @property
    def signin(self) -> bool:
        """Whether GitHub sign-in can work: an OAuth app and a signing secret."""
        return bool(self.github_client_id and self.github_client_secret and self.sessions)


def _default_connect():
    from falkordb import FalkorDB

    from airspace.config import settings

    s = settings()
    db = FalkorDB(host=s.falkordb_host, port=s.falkordb_port, socket_connect_timeout=_CONNECT_TIMEOUT,
                  socket_timeout=_SOCKET_TIMEOUT)
    db.connection.ping()
    return db


def _default_http():
    import httpx

    return httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))


class Cloud:
    """Shared state for the cloud routes. `connect` opens FalkorDB; `http` makes the client GitHub is called with."""

    def __init__(
        self,
        config: CloudConfig | None = None,
        *,
        connect: Callable[[], Any] | None = None,
        http: Callable[[], Any] | None = None,
        rpc_per_minute: int = 1200,
        rpc_max_bytes: int = 2 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config or CloudConfig()
        self.connect = connect or _default_connect
        self.http = http or _default_http
        self.rpc_per_minute = rpc_per_minute
        self.rpc_max_bytes = rpc_max_bytes
        self.clock = clock
        self._lock = threading.Lock()
        self._db: Any = None
        self._accounts: Any = None
        self._engines: dict[str, Any] = {}
        if self.config.secret and len(self.config.secret.encode()) < _MIN_SECRET:
            log.warning("airspace: AIRSPACE_SECRET is shorter than %d bytes, so sign-in is off", _MIN_SECRET)

    @classmethod
    def from_env(cls) -> "Cloud":
        return cls(CloudConfig.from_env())

    def db(self) -> Any:
        """The FalkorDB client, opened on first use and again after a failed attempt."""
        from airspace.api.app import EngineUnavailable

        with self._lock:
            if self._db is None:
                try:
                    self._db = self.connect()
                except Exception as e:
                    detail = " ".join(str(e).split()) or type(e).__name__
                    raise EngineUnavailable(f"FalkorDB unavailable ({detail})") from e
            return self._db

    def accounts(self):
        from airspace.cloud.accounts import Accounts

        db = self.db()
        with self._lock:
            if self._accounts is None:
                accounts = Accounts(db, self.config.accounts_graph or None, clock=self.clock)
                accounts.ensure_schema()
                self._accounts = accounts
            return self._accounts

    def engine(self, workspace_id: str):
        """The Airspace on the workspace graph, built like open_airspace and kept for later requests."""
        from airspace.admission.engine import Airspace
        from airspace.cloud.accounts import workspace_graph_name
        from airspace.config import settings

        db = self.db()
        with self._lock:
            air = self._engines.get(workspace_id)
            if air is None:
                if len(self._engines) >= _MAX_ENGINES:
                    self._engines.pop(next(iter(self._engines)))
                s = settings()
                # Airspace() runs ensure_schema on the graph.
                air = Airspace(db.select_graph(workspace_graph_name(workspace_id)), lease_seconds=s.lease_seconds,
                               cone_depth=s.cone_depth)
                self._engines[workspace_id] = air
            return air

    def forget(self, workspace_id: str) -> None:
        with self._lock:
            self._engines.pop(workspace_id, None)

    def mount(self, app, *, poll_interval: float = 0.5, ping_interval: float = 15.0,
              max_seconds: float | None = None) -> None:
        from airspace.cloud import auth, rpc, workspaces

        app.include_router(auth.router(self))
        app.include_router(workspaces.router(self))
        app.include_router(
            workspaces.tower_router(self, poll_interval=poll_interval, ping_interval=ping_interval,
                                    max_seconds=max_seconds),
            prefix="/api/w/{workspace_id}",
        )
        app.include_router(rpc.router(self))
