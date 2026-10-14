"""Files written outside the edit tools, through the real hooks, indexer and engine on a git copy of the fixture.

The truncate benchmark pair failed this way: agent B wrote tags/views.py with `cat > ... <<EOF`, no edit hook ran,
its task claimed nothing and it landed at once with a call that no longer fit.
"""

import os
import subprocess
import time

import pytest

from airspace.admission.engine import Airspace
from airspace.graph.db import repo_graph
from airspace.hooks.reconcile import changed_python_files
from bench_refs import REFS, Agent, never

A_PATCH = REFS["truncate-words-limit"][0]
TRUNCATE = "utils.text.truncate_words"
B_VIEWS = '''from tags.models import Tag
from utils.text import truncate_words


def create_tag(name):
    return Tag(name).save()


def tag_label(name):
    return truncate_words(name, 3)
'''


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=airspace", "-c", "user.email=airspace@example.invalid",
                    *args], check=True, capture_output=True)


@pytest.fixture
def repo(blog_repo):
    _git(blog_repo, "init", "-q", "-b", "main")
    _git(blog_repo, "add", "-A")
    _git(blog_repo, "commit", "-q", "-m", "fixture")
    return blog_repo


@pytest.fixture
def indexed(db, repo, monkeypatch):
    from airspace.hooks.handlers import default_deps
    from airspace.indexer.writer import index_repo

    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    graph = repo_graph(db, repo)
    index_repo(graph, repo)
    deps = default_deps()
    yield graph, Agent(repo, "agent-a", "sess-aaaa", deps), Agent(repo, "agent-b", "sess-bbbb", deps)
    graph.delete()


def _views(repo) -> str:
    return (repo / "tags" / "views.py").read_text()


def _context(out) -> str:
    return out["hookSpecificOutput"]["additionalContext"] if out else ""


def test_changed_python_files_lists_modified_untracked_and_renamed(repo):
    (repo / "utils" / "text.py").write_text((repo / "utils" / "text.py").read_text() + "\n# note\n")
    (repo / "tags" / "extra.py").write_text("X = 1\n")
    (repo / "notes.txt").write_text("not python\n")
    _git(repo, "mv", "blog/feeds.py", "blog/rss.py")
    assert changed_python_files(repo) == ["blog/rss.py", "tags/extra.py", "utils/text.py"]


def test_changed_python_files_outside_git_is_empty(blog_repo):
    assert changed_python_files(blog_repo) == []


def test_shell_write_after_a_contract_change_is_reported_and_blocks_landing(indexed):
    graph, a, b = indexed
    assert a.apply(A_PATCH)

    out = b.shell_write("tags/views.py", B_VIEWS)
    text = _context(out)
    assert "tags/views.py was written outside the edit tools." in text
    assert "truncate_words(text, *, limit=30)" in text

    # B's task now owns the file it wrote, so its landing check reads the call there.
    assert Airspace(graph).edited_files(b.session) == ["tags/views.py"]
    assert a.stop(sleep=never) is None  # A lands; B no longer waits on it
    stop = b.stop(sleep=never)
    assert stop is not None and stop["decision"] == "block"


def test_shell_write_before_the_contract_change_still_blocks_landing(indexed):
    graph, a, b = indexed
    b.shell_write("tags/views.py", B_VIEWS)
    claimed = graph.query("MATCH (:Task {id: 'sess-bbbb'})-[:CLAIMS]->(s:Symbol) RETURN s.qualname").result_set
    assert ["tags.views.tag_label"] in claimed

    assert a.apply(A_PATCH)
    assert a.stop(sleep=never) is None
    stop = b.stop(sleep=never)
    assert stop is not None and stop["decision"] == "block"
    assert "truncate_words(name, 3)" in stop["reason"]


def test_stop_reconciles_a_write_no_hook_saw(indexed):
    graph, a, b = indexed
    assert a.apply(A_PATCH)
    assert a.stop(sleep=never) is None
    (b.repo / "tags" / "views.py").write_text(B_VIEWS)  # a script, a formatter: not even a Bash hook ran

    stop = b.stop(sleep=never)
    assert stop is not None and stop["decision"] == "block"


def test_edit_tool_changes_are_not_taken_again_by_another_agents_command(indexed):
    graph, a, b = indexed
    assert a.apply(A_PATCH)
    assert _context(b.shell_write("notes.md", "nothing python\n")) == ""
    # The shared working copy shows A's edits to git, but A's hooks saw them: B claims none of them.
    assert graph.query("MATCH (t:Task {id: 'sess-bbbb'}) RETURN count(t)").result_set == [[0]]


def test_changes_from_before_the_task_started_are_left_alone(indexed):
    graph, _, b = indexed
    stale = b.repo / "utils" / "text.py"
    stale.write_text(stale.read_text().replace("count=30", "count=31"))
    old = time.time() - 3600
    os.utime(stale, (old, old))

    b.shell_write("notes.md", "nothing python\n")
    assert graph.query("MATCH (t:Task {id: 'sess-bbbb'}) RETURN count(t)").result_set == [[0]]


def test_a_same_task_shell_write_after_its_own_edit_is_not_a_conflict(indexed):
    graph, a, _ = indexed
    assert a.apply(A_PATCH)
    text = (a.repo / "utils" / "text.py").read_text()
    out = a.shell_write("utils/text.py", text + "\n\ndef shout(text):\n    return text.upper()\n")
    assert "outside the edit tools" not in _context(out)
    owned = graph.query("MATCH (:Task {id: 'sess-aaaa'})-[:CLAIMS]->(s:Symbol) RETURN s.qualname").result_set
    assert ["utils.text.shout"] in owned
