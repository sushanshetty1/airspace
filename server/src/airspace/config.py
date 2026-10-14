"""Settings read from the environment, with local-development defaults."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.environ.get("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.environ.get("FALKORDB_PORT", "6379"))
    lease_seconds: int = int(os.environ.get("AIRSPACE_LEASE_SECONDS", "900"))
    cone_depth: int = int(os.environ.get("AIRSPACE_CONE_DEPTH", "2"))


def settings() -> Settings:
    return Settings()
