from pathlib import Path

from helpers import BLOG_CALLS, BLOG_COVERS, BLOG_SYMBOLS

from airspace.indexer.writer import IndexStats, index_repo, known_qualnames, reindex_file
from airspace.types import SignatureChange

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "blog"

NEW_SLUGIFY = '''import re
import unicodedata


def slugify(value, *, unicode=False):
    value = str(value)
    if unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\\w\\s-]", "", value.lower())
    return re.sub(r"[-\\s]+", "-", value).strip("-_")


def truncate_words(text, count=30):
    words = text.split()
    return " ".join(words[:count]) + ("..." if len(words) > count else "")
'''


def _symbols(graph) -> set[tuple]:
    rows = graph.query(
        """MATCH (f:File)-[:DEFINES]->(s:Symbol)
        RETURN s.qualname, s.kind, f.path, s.lineno, s.end_lineno, s.signature, s.is_test"""
    ).result_set
    return {tuple(r) for r in rows}


def _edges(graph, rel: str) -> set[tuple[str, str]]:
    rows = graph.query(f"MATCH (a:Symbol)-[:{rel}]->(b:Symbol) RETURN a.qualname, b.qualname").result_set
    return {tuple(r) for r in rows}


def _counts(graph) -> tuple:
    nodes = graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
    rels = graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return nodes, rels


def _snapshot(graph) -> tuple:
    rows = graph.query("MATCH (s:Symbol) RETURN s.qualname, s.sig_hash, s.lineno, s.end_lineno").result_set
    return (
        {tuple(r) for r in rows},
        _edges(graph, "CALLS"),
        _edges(graph, "COVERS"),
        _edges(graph, "INHERITS"),
        _counts(graph),
    )


def test_index_repo_matches_seed(graph):
    stats = index_repo(graph, FIXTURE_REPO)
    assert _symbols(graph) == set(BLOG_SYMBOLS)
    assert _edges(graph, "CALLS") == set(BLOG_CALLS)
    assert _edges(graph, "COVERS") == set(BLOG_COVERS)
    assert stats.files == 13
    assert stats.symbols == 17
    assert stats.calls == len(BLOG_CALLS) + len(BLOG_COVERS)
    assert stats.unresolved > 0
    hashes = dict(graph.query("MATCH (s:Symbol) RETURN s.qualname, s.sig_hash").result_set)
    assert len(hashes["utils.text.slugify"]) == 12


def test_index_repo_is_idempotent(graph):
    first = index_repo(graph, FIXTURE_REPO)
    snap = _snapshot(graph)
    second = index_repo(graph, FIXTURE_REPO)
    assert first == second
    assert _snapshot(graph) == snap


def test_known_qualnames(graph):
    assert known_qualnames(graph) == set()
    index_repo(graph, FIXTURE_REPO)
    assert known_qualnames(graph) == {row[0] for row in BLOG_SYMBOLS}


def test_index_repo_skips_ignored_dirs_and_broken_files(graph, tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "base.py").write_text("class Base:\n    pass\n")
    (tmp_path / "pkg" / "child.py").write_text("from pkg.base import Base\n\nclass Child(Base):\n    pass\n")
    (tmp_path / "pkg" / "broken.py").write_text("def nope(:\n")
    for skipped in (".venv", ".git", "__pycache__", "venv", "node_modules", "build", "dist"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "junk.py").write_text("def junk():\n    pass\n")
    stats = index_repo(graph, tmp_path)
    assert stats == IndexStats(files=2, symbols=2, calls=0, unresolved=0)
    assert known_qualnames(graph) == {"pkg.base.Base", "pkg.child.Child"}
    assert _edges(graph, "INHERITS") == {("pkg.child.Child", "pkg.base.Base")}


def test_reindex_detects_signature_change(graph, blog_repo):
    index_repo(graph, blog_repo)
    (blog_repo / "utils" / "text.py").write_text(NEW_SLUGIFY)
    changes = reindex_file(graph, blog_repo, "utils/text.py")
    assert changes == [
        SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")
    ]
    sig = graph.query("MATCH (s:Symbol {qualname: 'utils.text.slugify'}) RETURN s.signature").result_set[0][0]
    assert sig == "slugify(value, *, unicode=False)"
    # Incoming edges from other files survive the rewrite.
    assert ("blog.models.Post.save", "utils.text.slugify") in _edges(graph, "CALLS")
    assert ("tags.models.Tag.save", "utils.text.slugify") in _edges(graph, "CALLS")
    assert ("tests.test_text.test_slugify", "utils.text.slugify") in _edges(graph, "COVERS")
    assert _edges(graph, "CALLS") == set(BLOG_CALLS)
    # Unchanged again: no changes reported.
    assert reindex_file(graph, blog_repo, "utils/text.py") == []


def test_reindex_removes_deleted_symbol(graph, blog_repo):
    index_repo(graph, blog_repo)
    text = (blog_repo / "utils" / "text.py").read_text()
    (blog_repo / "utils" / "text.py").write_text(text.split("\n\ndef truncate_words")[0] + "\n")
    assert reindex_file(graph, blog_repo, "utils/text.py") == []
    assert "utils.text.truncate_words" not in known_qualnames(graph)
    assert ("blog.feeds.LatestPosts.item_description", "utils.text.truncate_words") not in _edges(graph, "CALLS")
    assert "utils.text.slugify" in known_qualnames(graph)


def test_reindex_rewrites_outgoing_edges(graph, blog_repo):
    index_repo(graph, blog_repo)
    (blog_repo / "blog" / "views.py").write_text(
        "from utils.text import slugify\n\n\n"
        "def render_post(post):\n    return slugify(post.title)\n\n\n"
        "def post_list(posts):\n    return list(posts)\n"
    )
    assert reindex_file(graph, blog_repo, "blog/views.py") == []
    calls = _edges(graph, "CALLS")
    assert ("blog.views.render_post", "utils.text.slugify") in calls
    assert ("blog.views.post_list", "blog.views.render_post") not in calls
    # Incoming edges into this file from elsewhere are kept.
    assert ("blog.feeds.LatestPosts.item_description", "blog.views.render_post") in calls
    assert ("tests.test_views.test_render_post", "blog.views.render_post") in _edges(graph, "COVERS")


def test_reindex_syntax_error_changes_nothing(graph, blog_repo):
    index_repo(graph, blog_repo)
    before = _snapshot(graph)
    (blog_repo / "utils" / "text.py").write_text("def slugify(value, *, unicode=False:\n    pass\n")
    assert reindex_file(graph, blog_repo, "utils/text.py") == []
    assert _snapshot(graph) == before


def test_reindex_missing_file_deletes_its_symbols(graph, blog_repo):
    index_repo(graph, blog_repo)
    (blog_repo / "tags" / "views.py").unlink()
    assert reindex_file(graph, blog_repo, "tags/views.py") == []
    assert "tags.views.tag_create" not in known_qualnames(graph)
    assert "tags.models.Tag.save" in known_qualnames(graph)
    assert graph.query("MATCH (f:File {path: 'tags/views.py'}) RETURN count(f)").result_set[0][0] == 0


def test_reindex_new_file(graph, blog_repo):
    index_repo(graph, blog_repo)
    (blog_repo / "blog" / "search.py").write_text(
        "from utils.text import slugify\n\n\ndef search(q):\n    return slugify(q)\n"
    )
    assert reindex_file(graph, blog_repo, "blog/search.py") == []
    assert ("blog.search.search", "utils.text.slugify") in _edges(graph, "CALLS")


def _shapes(graph, rel: str) -> dict[tuple[str, str], list[str]]:
    rows = graph.query(f"MATCH (a:Symbol)-[r:{rel}]->(b:Symbol) RETURN a.qualname, b.qualname, r.shapes").result_set
    return {(a, b): s for a, b, s in rows}


def test_edges_store_call_shapes(graph):
    index_repo(graph, FIXTURE_REPO)
    calls = _shapes(graph, "CALLS")
    # "v:": the result is used (assigned, returned, passed on), so a callee that stops returning breaks the call.
    assert calls[("blog.models.Post.save", "utils.text.slugify")] == ["v:1|"]
    assert calls[("blog.feeds.LatestPosts.item_description", "utils.text.truncate_words")] == ["v:2|"]
    assert calls[("tags.views.tag_create", "tags.models.Tag")] == ["v:1|"]
    # Tag(name).save() is called on the new instance, so it is bound.
    assert calls[("tags.views.tag_create", "tags.models.Tag.save")] == ["v:b:0|"]
    covers = _shapes(graph, "COVERS")
    assert covers[("tests.test_views.test_render_post", "blog.models.Post")] == ["v:2|"]


def test_edge_shapes_merge_across_call_sites(graph, blog_repo):
    index_repo(graph, blog_repo)
    (blog_repo / "blog" / "search.py").write_text(
        "from utils.text import slugify\n\n\n"
        "class Search:\n"
        "    def run(self, q, opts):\n"
        "        self.clean(q)\n"
        "        return slugify(q) + slugify(q, unicode=True) + slugify(q) + slugify(*opts)\n\n"
        "    def clean(self, q):\n"
        "        return q\n"
    )
    reindex_file(graph, blog_repo, "blog/search.py")
    calls = _shapes(graph, "CALLS")
    assert sorted(calls[("blog.search.Search.run", "utils.text.slugify")]) == ["v:*", "v:1|", "v:1|unicode"]
    # A bare statement throws the result away.
    assert calls[("blog.search.Search.run", "blog.search.Search.clean")] == ["b:1|"]
