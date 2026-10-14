import shutil
import uuid
from pathlib import Path

import pytest

from airspace.graph.db import connect, ensure_schema

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "blog"


@pytest.fixture(autouse=True)
def _private_config(tmp_path_factory, monkeypatch):
    """No test reads the developer's own remotes.json or seen cache: a connected repo there must not change a test."""
    home = tmp_path_factory.mktemp("airspace-home")
    monkeypatch.setenv("AIRSPACE_CONFIG_DIR", str(home / "config"))
    monkeypatch.setenv("AIRSPACE_CACHE_DIR", str(home / "cache"))


@pytest.fixture(scope="session")
def db():
    try:
        conn = connect()
        conn.connection.ping()
    except Exception:
        pytest.skip("FalkorDB is not running on localhost:6379 (docker compose up -d falkordb)")
    return conn


@pytest.fixture
def graph(db):
    """A fresh, uniquely named graph per test, deleted afterwards. Safe for parallel agents sharing one FalkorDB."""
    g = db.select_graph(f"test_{uuid.uuid4().hex[:12]}")
    ensure_schema(g)
    yield g
    try:
        g.delete()
    except Exception:
        pass


@pytest.fixture
def blog_repo(tmp_path) -> Path:
    """A writable copy of the fixture repo."""
    dest = tmp_path / "blog"
    shutil.copytree(FIXTURE_REPO, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dest
