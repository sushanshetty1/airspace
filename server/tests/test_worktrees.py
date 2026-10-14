"""Two agents on separate worktrees of one repo, sharing one graph, as the benchmark and hosted workspaces run.

Found on Flask: agent A renamed a parameter of get_flashed_messages, then agent B appended a new function to its
own copy of helpers.py, which still had the old parameter. Re-indexing B's copy read as B renaming it back, and A
was held for a change nobody made.
"""

import shutil
import uuid

import pytest

from airspace.graph.db import connect
from bench_refs import Agent

TEXT = "utils/text.py"
NEW_SIG = "def slugify(value, *, unicode=False):\n    value = str(value)\n    if unicode:"
OLD_SIG = "def slugify(value, allow_unicode=False):\n    value = str(value)\n    if allow_unicode:"


@pytest.fixture
def worktrees(db, blog_repo, tmp_path, monkeypatch):
    from airspace.cli import main
    from airspace.hooks.handlers import default_deps

    graph = f"test_wt_{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("AIRSPACE_GRAPH", graph)
    a_root, b_root = tmp_path / "a", tmp_path / "b"
    shutil.copytree(blog_repo, a_root)
    shutil.copytree(blog_repo, b_root)
    assert main(["index", "--root", str(a_root)]) == 0
    deps = default_deps()
    yield db.select_graph(graph), Agent(a_root, "agent-a", "sess-a", deps), Agent(b_root, "agent-b", "sess-b", deps)
    connect().select_graph(graph).delete()


def _sig(graph) -> str:
    return graph.query("MATCH (s:Symbol {qualname: 'utils.text.slugify'}) RETURN s.signature").result_set[0][0]


def test_an_edit_to_a_stale_copy_of_the_file_is_not_a_contract_change(worktrees):
    graph, a, b = worktrees
    assert a.edit(TEXT, "Edit", {"file_path": TEXT, "old_string": OLD_SIG, "new_string": NEW_SIG})
    assert _sig(graph) == "slugify(value, *, unicode=False)"

    # B appends to its own copy of the same file, which still has the old slugify.
    source = (b.repo / TEXT).read_text()
    assert b.edit(TEXT, "Write", {"file_path": TEXT, "content": source + "\n\ndef shout(text):\n    return text.upper()\n"})

    # The graph keeps A's contract, and nothing is recorded against B.
    assert _sig(graph) == "slugify(value, *, unicode=False)"
    changes = graph.query("MATCH (t:Task)-[:CHANGED]->(c:ContractChange) RETURN t.id, c.new_sig").result_set
    assert changes == [["sess-a", "slugify(value, *, unicode=False)"]]
    # So A goes on editing callers with the new keyword, unheld.
    views = "blog/views.py"
    assert a.edit(views, "Edit", {"file_path": views, "old_string": "from blog.models import Post\n",
                                  "new_string": "from blog.models import Post\nfrom utils.text import slugify\n"})
    assert a.holds == []


def test_a_real_change_from_the_other_worktree_still_counts(worktrees):
    graph, a, b = worktrees
    assert a.edit(TEXT, "Edit", {"file_path": TEXT, "old_string": OLD_SIG, "new_string": NEW_SIG})
    # B changes truncate_words in its copy: that is B's own change and is recorded for B.
    old = "def truncate_words(text, count=30):"
    assert b.edit(TEXT, "Edit", {"file_path": TEXT, "old_string": old, "new_string": "def truncate_words(text, *, count=30):"})
    rows = graph.query("MATCH (t:Task)-[:CHANGED]->(c:ContractChange) RETURN t.id, c.qualname ORDER BY t.id").result_set
    assert rows == [["sess-a", "utils.text.slugify"], ["sess-b", "utils.text.truncate_words"]]
    assert _sig(graph) == "slugify(value, *, unicode=False)"
