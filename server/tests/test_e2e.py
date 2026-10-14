"""End to end: the website story, through the real hooks, indexer and engine on a real repo copy."""

import subprocess
import sys

import pytest

from airspace.graph.db import repo_graph

SLUGIFY_OLD = "def slugify(value, allow_unicode=False):\n    value = str(value)\n    if allow_unicode:"
SLUGIFY_NEW = "def slugify(value, *, unicode=False):\n    value = str(value)\n    if unicode:"
VIEWS_ANCHOR = "    url = post.get_absolute_url()"
IMPORT_ANCHOR = "from blog.models import Post"


def _views_edit(call: str) -> dict:
    return {
        "file_path": "blog/views.py",
        "edits": [
            {"old_string": IMPORT_ANCHOR, "new_string": IMPORT_ANCHOR + "\nfrom utils.text import slugify"},
            {"old_string": VIEWS_ANCHOR, "new_string": VIEWS_ANCHOR + f"\n    slug = {call}"},
        ],
    }


def _payload(session: str, tool: str, tool_input: dict, repo) -> dict:
    return {"session_id": session, "cwd": str(repo), "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def _apply_on_disk(repo, rel, edits):
    path = repo / rel
    text = path.read_text()
    for old, new in edits:
        assert old in text
        text = text.replace(old, new, 1)
    path.write_text(text)


@pytest.fixture
def indexed_repo(db, blog_repo):
    from airspace.indexer.writer import index_repo

    graph = repo_graph(db, blog_repo)
    index_repo(graph, blog_repo)
    yield blog_repo, graph
    graph.delete()


def _env(repo, agent):
    return {"CLAUDE_PROJECT_DIR": str(repo), "AIRSPACE_AGENT": agent}


def test_hold_brief_clear_through_the_hooks(indexed_repo):
    from airspace.hooks.handlers import default_deps, handle_post, handle_pre

    repo, graph = indexed_repo
    deps = default_deps()

    # agent-a changes slugify's signature inside its own airspace: cleared.
    a_input = {"file_path": "utils/text.py", "old_string": SLUGIFY_OLD, "new_string": SLUGIFY_NEW}
    out = handle_pre(_payload("sess-aaaa", "Edit", a_input, repo), deps, _env(repo, "agent-a"))
    assert out is None or out["hookSpecificOutput"].get("permissionDecision") != "deny"
    _apply_on_disk(repo, "utils/text.py", [(SLUGIFY_OLD, SLUGIFY_NEW)])
    handle_post({**_payload("sess-aaaa", "Edit", a_input, repo), "hook_event_name": "PostToolUse"}, deps, _env(repo, "agent-a"))

    # agent-b adds a call with the old signature: held, with the path and the new signature.
    out = handle_pre(_payload("sess-bbbb", "MultiEdit", _views_edit("slugify(post.title, True)"), repo), deps, _env(repo, "agent-b"))
    assert out is not None
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    reason = hso["permissionDecisionReason"]
    for fact in ("utils.text.slugify", "agent-a", "slugify(value, *, unicode=False)", "blog.views.render_post"):
        assert fact in reason

    # agent-b retries with the new signature: cleared.
    out = handle_pre(_payload("sess-bbbb", "MultiEdit", _views_edit("slugify(post.title, unicode=True)"), repo), deps, _env(repo, "agent-b"))
    assert out is None or out["hookSpecificOutput"].get("permissionDecision") != "deny"

    collisions = graph.query("MATCH (c:Collision) RETURN count(c)").result_set[0][0]
    assert collisions == 1


def _run_fixture_tests(repo) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(repo)], cwd=repo, capture_output=True).returncode


def test_the_collision_is_real(blog_repo):
    """Without Airspace, both edits merge cleanly and the fixture repo's own tests fail. With the briefed call they pass."""
    _apply_on_disk(blog_repo, "utils/text.py", [(SLUGIFY_OLD, SLUGIFY_NEW)])
    _apply_on_disk(blog_repo, "blog/views.py", [(IMPORT_ANCHOR, IMPORT_ANCHOR + "\nfrom utils.text import slugify"), (VIEWS_ANCHOR, VIEWS_ANCHOR + "\n    slug = slugify(post.title, True)")])
    assert _run_fixture_tests(blog_repo) != 0

    views = blog_repo / "blog/views.py"
    views.write_text(views.read_text().replace("slugify(post.title, True)", "slugify(post.title, unicode=True)"))
    assert _run_fixture_tests(blog_repo) == 0
