"""Contract checks through the real hooks, indexer and engine on a fixture copy: call shapes against new signatures,
changes recorded at the pre hook, callers that land first, method and constructor calls, removals."""

import pytest

from airspace.graph.db import repo_graph
from bench_refs import REFS, Agent, is_deny

SLUGIFY = "utils.text.slugify"
NEW_SIG = "slugify(value, *, unicode=False)"
SLUGIFY_EDIT = {
    "file_path": "utils/text.py",
    "old_string": "def slugify(value, allow_unicode=False):\n    value = str(value)\n    if allow_unicode:",
    "new_string": "def slugify(value, *, unicode=False):\n    value = str(value)\n    if unicode:",
}
ANCHOR = "    url = post.get_absolute_url()"


def _views_call(call: str) -> dict:
    return {
        "file_path": "blog/views.py",
        "edits": [
            {"old_string": "from blog.models import Post", "new_string": "from blog.models import Post\nfrom utils.text import slugify"},
            {"old_string": ANCHOR, "new_string": ANCHOR + f"\n    slug = {call}"},
        ],
    }


@pytest.fixture
def indexed(db, blog_repo, monkeypatch):
    from airspace.hooks.handlers import default_deps
    from airspace.indexer.writer import index_repo

    monkeypatch.delenv("AIRSPACE_GRAPH", raising=False)
    graph = repo_graph(db, blog_repo)
    index_repo(graph, blog_repo)
    deps = default_deps()
    yield graph, Agent(blog_repo, "agent-a", "sess-aaaa", deps), Agent(blog_repo, "agent-b", "sess-bbbb", deps)
    graph.delete()


def _changes(graph, q=SLUGIFY):
    return graph.query(
        "MATCH (cc:ContractChange {qualname: $q}) RETURN cc.old_sig, cc.new_sig", {"q": q}
    ).result_set


def _collisions(graph):
    return graph.query(
        "MATCH (x:Collision) RETURN x.kind, x.held_agent, x.owner_agent, x.symbol, x.caller, x.new_sig, x.resolution"
    ).result_set


def test_pre_records_signature_change_before_write(indexed):
    graph, a, b = indexed

    out = a.pre("Edit", SLUGIFY_EDIT)

    assert not is_deny(out)
    assert "allow_unicode" in (a.repo / "utils/text.py").read_text()  # nothing written yet
    assert _changes(graph) == [["slugify(value, allow_unicode=False)", NEW_SIG]]
    # A concurrent agent is held before agent-a's write lands.
    assert is_deny(b.pre("MultiEdit", _views_call("slugify(post.title, True)")))


def test_post_does_not_double_record(indexed):
    graph, a, _ = indexed

    assert a.edit("utils/text.py", "Edit", SLUGIFY_EDIT)

    assert _changes(graph) == [["slugify(value, allow_unicode=False)", NEW_SIG]]
    contract_events = graph.query("MATCH (e:Event {kind: 'contract'}) RETURN count(e)").result_set[0][0]
    assert contract_events == 1


def test_repeated_incompatible_call_stays_held_through_the_hooks(indexed):
    graph, a, b = indexed
    a.edit("utils/text.py", "Edit", SLUGIFY_EDIT)

    first = b.pre("MultiEdit", _views_call("slugify(post.title, True)"))
    second = b.pre("MultiEdit", _views_call("slugify(post.title, True)"))

    assert is_deny(first) and is_deny(second)
    for out in (first, second):
        assert NEW_SIG in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert not is_deny(b.pre("MultiEdit", _views_call("slugify(post.title, unicode=True)")))
    assert [row[-1] for row in _collisions(graph)] == ["resolved"]


def test_compatible_call_clears_without_briefing_through_the_hooks(indexed):
    graph, a, b = indexed
    a.edit("utils/text.py", "Edit", SLUGIFY_EDIT)

    assert b.edit("blog/views.py", "MultiEdit", _views_call("slugify(post.title, unicode=True)"))
    assert _collisions(graph) == []


def test_caller_first_then_change_briefs_on_next_tool(indexed):
    graph, a, b = indexed

    # agent-b writes the call first: nothing has changed yet, so it is cleared.
    assert b.edit("blog/views.py", "MultiEdit", _views_call("slugify(post.title, True)"))
    # agent-a changes the signature: pre records it, post finds it already recorded.
    assert a.edit("utils/text.py", "Edit", SLUGIFY_EDIT)
    assert len(_changes(graph)) == 1

    # agent-b only runs its tests next, and hears about it there.
    out = b.other_tool("Bash", {"command": "python -m pytest -q"})

    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert NEW_SIG in context and "agent-a" in context
    assert f"The call blog.views.render_post makes no longer fits {NEW_SIG}." in context
    assert chr(0x2014) not in context and chr(0x2013) not in context
    assert _collisions(graph) == [
        ["contract", "agent-b", "agent-a", SLUGIFY, "blog.views.render_post", NEW_SIG, "held"]
    ]
    # Tower shows agent-b held.
    from airspace.admission.engine import Airspace

    state = Airspace(graph).state()
    assert next(x for x in state["agents"] if x["id"] == "agent-b")["held"] is True
    assert b.other_tool("Read", {"file_path": "blog/views.py"}) is None

    # agent-b fixes the call: cleared, and the collision is resolved.
    fix = {"file_path": "blog/views.py", "old_string": "slugify(post.title, True)", "new_string": "slugify(post.title, unicode=True)"}
    assert b.edit("blog/views.py", "Edit", fix)
    assert [row[-1] for row in _collisions(graph)] == ["resolved"]


def test_method_call_through_object_is_checked(indexed):
    graph, a, b = indexed
    ref_a, ref_b = REFS["rename-absolute-url"]
    assert a.apply(ref_a)

    assert b.apply(ref_b) is False

    reason = b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert "blog.models.Post.get_absolute_url is being renamed or removed by agent-a" in reason
    assert "blog.feeds.LatestPosts.item_link" in reason


def test_constructor_call_checked_against_init(indexed):
    graph, a, b = indexed
    ref_a, ref_b = REFS["post-requires-author"]
    assert a.apply(ref_a)

    assert b.apply(ref_b) is False

    reason = b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert "blog.models.Post.__init__" in reason and "__init__(self, title, body, author)" in reason
    # The same test written with the author argument is cleared.
    fixed = REFS["post-requires-author"][1]["tests/test_feeds.py"].replace("Post('Hi', 'x')", "Post('Hi', 'x', 'ana')")
    assert b.edit("tests/test_feeds.py", "Write", {"file_path": "tests/test_feeds.py", "content": fixed})


def test_removed_symbol_holds_callers(indexed):
    graph, a, b = indexed
    models = a.repo / "blog/models.py"
    method = "\n    def get_absolute_url(self):\n        return f\"/posts/{self.slug}/\"\n"
    assert method in models.read_text()

    # agent-a deletes the method outright: no symbol left in the new source is touched, but the removal is recorded.
    assert a.edit("blog/models.py", "Edit", {"file_path": "blog/models.py", "old_string": method, "new_string": ""})
    assert _changes(graph, "blog.models.Post.get_absolute_url") == [["get_absolute_url(self)", ""]]

    feeds_add = {
        "file_path": "blog/feeds.py",
        "old_string": "        return truncate_words(render_post(post), 40)\n",
        "new_string": "        return truncate_words(render_post(post), 40)\n\n    def item_link(self, post):\n        return post.get_absolute_url()\n",
    }
    out = b.pre("Edit", feeds_add)
    assert is_deny(out)
    assert "removed by agent-a" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_dropped_return_is_a_contract_change(indexed):
    # Tag.save stops returning self. Its parameters stay the same, but its contract becomes save(self) -> None,
    # and agent-b's Tag(name).save().slug uses the result.
    graph, a, b = indexed
    ref_a, ref_b = REFS["tag-save-returns-none"]

    assert a.apply(ref_a)
    assert b.apply(ref_b) is False
    assert "save(self) -> None" in b.holds[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert graph.query("MATCH (cc:ContractChange) RETURN cc.new_sig").result_set == [["save(self) -> None"]]
