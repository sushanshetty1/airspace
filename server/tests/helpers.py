"""Test helpers shared by every task. The seeded graph matches what the indexer produces for tests/fixtures/blog."""

import hashlib

# (qualname, kind, file, lineno, end_lineno, signature, is_test)
BLOG_SYMBOLS = [
    ("utils.text.slugify", "function", "utils/text.py", 5, 12, "slugify(value, allow_unicode=False)", False),
    ("utils.text.truncate_words", "function", "utils/text.py", 15, 17, "truncate_words(text, count=30)", False),
    ("blog.models.Post", "class", "blog/models.py", 4, 15, "Post()", False),
    ("blog.models.Post.__init__", "method", "blog/models.py", 5, 8, "__init__(self, title, body)", False),
    ("blog.models.Post.save", "method", "blog/models.py", 10, 12, "save(self)", False),
    ("blog.models.Post.get_absolute_url", "method", "blog/models.py", 14, 15, "get_absolute_url(self)", False),
    ("blog.views.render_post", "function", "blog/views.py", 4, 6, "render_post(post)", False),
    ("blog.views.post_list", "function", "blog/views.py", 9, 10, "post_list(posts)", False),
    ("blog.feeds.LatestPosts", "class", "blog/feeds.py", 5, 7, "LatestPosts()", False),
    ("blog.feeds.LatestPosts.item_description", "method", "blog/feeds.py", 6, 7, "item_description(self, post)", False),
    ("tags.models.Tag", "class", "tags/models.py", 4, 11, "Tag()", False),
    ("tags.models.Tag.__init__", "method", "tags/models.py", 5, 7, "__init__(self, name)", False),
    ("tags.models.Tag.save", "method", "tags/models.py", 9, 11, "save(self)", False),
    ("tags.views.tag_create", "function", "tags/views.py", 4, 5, "tag_create(name)", False),
    ("tests.test_text.test_slugify", "function", "tests/test_text.py", 4, 5, "test_slugify()", True),
    ("tests.test_models.test_post_save", "function", "tests/test_models.py", 4, 5, "test_post_save()", True),
    ("tests.test_views.test_render_post", "function", "tests/test_views.py", 5, 7, "test_render_post()", True),
]

# Resolved edges the indexer finds. Receivers of unknown type (post.get_absolute_url()) stay unresolved.
BLOG_CALLS = [
    ("blog.models.Post.save", "utils.text.slugify"),
    ("blog.views.post_list", "blog.views.render_post"),
    ("blog.feeds.LatestPosts.item_description", "blog.views.render_post"),
    ("blog.feeds.LatestPosts.item_description", "utils.text.truncate_words"),
    ("tags.models.Tag.save", "utils.text.slugify"),
    ("tags.views.tag_create", "tags.models.Tag"),
    ("tags.views.tag_create", "tags.models.Tag.save"),
]
BLOG_COVERS = [
    ("tests.test_text.test_slugify", "utils.text.slugify"),
    ("tests.test_models.test_post_save", "blog.models.Post"),
    ("tests.test_models.test_post_save", "blog.models.Post.save"),
    ("tests.test_views.test_render_post", "blog.models.Post"),
    ("tests.test_views.test_render_post", "blog.models.Post.save"),
    ("tests.test_views.test_render_post", "blog.views.render_post"),
]


def sig_hash(signature: str) -> str:
    return hashlib.sha1(signature.encode()).hexdigest()[:12]


def seed_blog_graph(graph) -> None:
    """Write the fixture repo's code graph straight into FalkorDB, without the indexer."""
    for q, kind, file, lineno, end, sig, is_test in BLOG_SYMBOLS:
        graph.query(
            """MERGE (f:File {path: $file})
            MERGE (s:Symbol {qualname: $q})
            SET s.name = $name, s.kind = $kind, s.file = $file, s.lineno = $lineno, s.end_lineno = $end,
                s.signature = $sig, s.sig_hash = $hash, s.is_test = $is_test
            MERGE (f)-[:DEFINES]->(s)""",
            {"file": file, "q": q, "name": q.rsplit(".", 1)[1], "kind": kind, "lineno": lineno, "end": end,
             "sig": sig, "hash": sig_hash(sig), "is_test": is_test},
        )
    for rel, pairs in (("CALLS", BLOG_CALLS), ("COVERS", BLOG_COVERS)):
        for a, b in pairs:
            graph.query(
                f"MATCH (a:Symbol {{qualname: $a}}), (b:Symbol {{qualname: $b}}) MERGE (a)-[:{rel}]->(b)",
                {"a": a, "b": b},
            )
