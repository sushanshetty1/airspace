from helpers import BLOG_SYMBOLS

from airspace.hooks.edit_analysis import analyze_edit, apply_tool_input, calls_in_file
from airspace.types import CallSite, EditAnalysis, SignatureChange

KNOWN = {row[0] for row in BLOG_SYMBOLS}

ADD_SLUGIFY_CALL = [
    {"old_string": "    url = post.get_absolute_url()", "new_string": "    url = post.get_absolute_url()\n    slug = slugify(post.title, True)"},
    {"old_string": "from blog.models import Post\n", "new_string": "from blog.models import Post\nfrom utils.text import slugify\n"},
]


def test_apply_edit_replaces_first_occurrence():
    out = apply_tool_input("Edit", {"file_path": "a.py", "old_string": "x", "new_string": "y"}, "x = x\n")
    assert out == "y = x\n"


def test_apply_edit_replace_all():
    tool_input = {"file_path": "a.py", "old_string": "x", "new_string": "y", "replace_all": True}
    assert apply_tool_input("Edit", tool_input, "x = x\n") == "y = y\n"


def test_apply_multiedit_sequential():
    edits = [{"old_string": "a", "new_string": "b"}, {"old_string": "b", "new_string": "c", "replace_all": True}]
    assert apply_tool_input("MultiEdit", {"file_path": "a.py", "edits": edits}, "a b\n") == "c c\n"


def test_apply_write_returns_content():
    assert apply_tool_input("Write", {"file_path": "a.py", "content": "z = 1\n"}, None) == "z = 1\n"
    assert apply_tool_input("Write", {"file_path": "a.py", "content": "z = 1\n"}, "old\n") == "z = 1\n"


def test_apply_returns_none_when_not_applicable():
    assert apply_tool_input("Edit", {"file_path": "a.py", "old_string": "q", "new_string": "r"}, "x\n") is None
    assert apply_tool_input("Edit", {"file_path": "a.py", "old_string": "q", "new_string": "r"}, None) is None
    edits = [{"old_string": "x", "new_string": "y"}, {"old_string": "missing", "new_string": "z"}]
    assert apply_tool_input("MultiEdit", {"file_path": "a.py", "edits": edits}, "x\n") is None
    assert apply_tool_input("MultiEdit", {"file_path": "a.py", "edits": edits}, None) is None
    assert apply_tool_input("Read", {"file_path": "a.py"}, "x\n") is None


def test_analyze_edit_finds_touched_and_new_call(blog_repo):
    tool_input = {"file_path": str(blog_repo / "blog" / "views.py"), "edits": ADD_SLUGIFY_CALL}
    result = analyze_edit(blog_repo, "MultiEdit", tool_input, KNOWN)
    assert result.file == "blog/views.py"
    assert result.parse_ok is True
    assert result.touched == ["blog.views.render_post"]
    assert result.new_calls == [("blog.views.render_post", "utils.text.slugify")]


def test_analyze_edit_relative_path(blog_repo):
    tool_input = {"file_path": "blog/views.py", "edits": ADD_SLUGIFY_CALL}
    result = analyze_edit(blog_repo, "MultiEdit", tool_input, KNOWN)
    assert result.new_calls == [("blog.views.render_post", "utils.text.slugify")]


def test_analyze_edit_existing_call_is_not_new(blog_repo):
    # Changing the line that already calls slugify touches Post.save but adds no new call.
    tool_input = {
        "file_path": str(blog_repo / "blog" / "models.py"),
        "old_string": "self.slug = slugify(self.title)",
        "new_string": "self.slug = slugify(self.title or 'untitled')",
    }
    result = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert result.touched == ["blog.models.Post.save"]
    assert result.new_calls == []


def test_analyze_edit_class_line_touches_class(blog_repo):
    tool_input = {"file_path": str(blog_repo / "tags" / "models.py"), "old_string": "class Tag:", "new_string": "class Tag(object):"}
    result = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert result.touched == ["tags.models.Tag"]


def test_analyze_edit_deleted_line_touches_its_symbol(blog_repo):
    tool_input = {"file_path": str(blog_repo / "blog" / "models.py"), "old_string": "        return self\n", "new_string": ""}
    result = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert result.touched == ["blog.models.Post.save"]


def test_analyze_edit_ignores_non_python(blog_repo):
    tool_input = {"file_path": str(blog_repo / "README.md"), "content": "# hi\n"}
    assert analyze_edit(blog_repo, "Write", tool_input, KNOWN) is None


def test_analyze_edit_ignores_files_outside_repo(blog_repo, tmp_path):
    tool_input = {"file_path": str(tmp_path / "elsewhere.py"), "content": "def f():\n    pass\n"}
    assert analyze_edit(blog_repo, "Write", tool_input, KNOWN) is None


def test_analyze_edit_inapplicable_edit_is_none(blog_repo):
    tool_input = {"file_path": str(blog_repo / "blog" / "views.py"), "old_string": "nope", "new_string": "x"}
    assert analyze_edit(blog_repo, "Edit", tool_input, KNOWN) is None


def test_analyze_edit_new_file(blog_repo):
    content = "from utils.text import slugify\n\n\nclass Search:\n    def run(self, q):\n        return slugify(q)\n"
    tool_input = {"file_path": str(blog_repo / "blog" / "search.py"), "content": content}
    result = analyze_edit(blog_repo, "Write", tool_input, KNOWN)
    assert result.file == "blog/search.py"
    assert result.parse_ok is True
    assert result.touched == ["blog.search.Search", "blog.search.Search.run"]
    assert result.new_calls == [("blog.search.Search.run", "utils.text.slugify")]


def test_analyze_edit_syntax_error(blog_repo):
    tool_input = {"file_path": str(blog_repo / "utils" / "text.py"), "old_string": "def slugify(value, allow_unicode=False):", "new_string": "def slugify(value, *, unicode=False:"}
    assert analyze_edit(blog_repo, "Edit", tool_input, KNOWN) == EditAnalysis("utils/text.py", [], [], parse_ok=False)


# Agents often add a call before its import, in separate edits. Neither order may let a collision through.

def _known():
    from helpers import BLOG_SYMBOLS

    return {s[0] for s in BLOG_SYMBOLS}


def test_call_without_import_resolves_by_unique_name(blog_repo):
    tool_input = {
        "file_path": "blog/views.py",
        "old_string": "    url = post.get_absolute_url()",
        "new_string": "    url = post.get_absolute_url()\n    slug = slugify(post.title, True)",
    }
    analysis = analyze_edit(blog_repo, "Edit", tool_input, _known())
    assert ("blog.views.render_post", "utils.text.slugify") in analysis.new_calls


def test_import_first_then_call(blog_repo):
    known = _known()
    add_import = {"file_path": "blog/views.py", "old_string": "from blog.models import Post", "new_string": "from blog.models import Post\nfrom utils.text import slugify"}
    assert analyze_edit(blog_repo, "Edit", add_import, known).new_calls == []
    views = blog_repo / "blog/views.py"
    views.write_text(apply_tool_input("Edit", add_import, views.read_text()))
    add_call = {
        "file_path": "blog/views.py",
        "old_string": "    url = post.get_absolute_url()",
        "new_string": "    url = post.get_absolute_url()\n    slug = slugify(post.title, True)",
    }
    assert analyze_edit(blog_repo, "Edit", add_call, known).new_calls == [("blog.views.render_post", "utils.text.slugify")]


def test_ambiguous_bare_name_is_not_guessed(blog_repo):
    tool_input = {
        "file_path": "blog/views.py",
        "old_string": "    url = post.get_absolute_url()",
        "new_string": "    url = post.get_absolute_url()\n    save()",
    }
    analysis = analyze_edit(blog_repo, "Edit", tool_input, _known())
    assert all(callee.rsplit(".", 1)[1] != "save" for _, callee in analysis.new_calls)


# Call shapes, signature changes and the clearance-only resolution of method and constructor calls.

SLUGIFY = "utils.text.slugify"
RENDER = "blog.views.render_post"


def test_analysis_reports_call_shapes(blog_repo):
    tool_input = {"file_path": "blog/views.py", "edits": ADD_SLUGIFY_CALL}
    analysis = analyze_edit(blog_repo, "MultiEdit", tool_input, KNOWN)
    assert analysis.call_shapes == {SLUGIFY: [CallSite(RENDER, 2, (), False, False)]}
    assert analysis.signature_changes == []


def test_reshaped_call_counts_as_new(blog_repo):
    tool_input = {
        "file_path": "blog/models.py",
        "old_string": "self.slug = slugify(self.title)",
        "new_string": "self.slug = slugify(self.title, unicode=True)",
    }
    analysis = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert analysis.new_calls == [("blog.models.Post.save", SLUGIFY)]
    assert analysis.call_shapes == {SLUGIFY: [CallSite("blog.models.Post.save", 1, ("unicode",), False, False)]}


def test_changed_signature_is_reported(blog_repo):
    tool_input = {
        "file_path": "utils/text.py",
        "old_string": "def slugify(value, allow_unicode=False):",
        "new_string": "def slugify(value, *, unicode=False):",
    }
    analysis = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert analysis.signature_changes == [
        SignatureChange(SLUGIFY, "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")
    ]


def test_removed_symbol_is_reported_with_an_empty_signature(blog_repo):
    tool_input = {"file_path": "blog/models.py", "old_string": "def get_absolute_url(self):", "new_string": "def url(self):"}
    analysis = analyze_edit(blog_repo, "Edit", tool_input, KNOWN)
    assert analysis.touched == ["blog.models.Post.url"]
    assert analysis.signature_changes == [SignatureChange("blog.models.Post.get_absolute_url", "get_absolute_url(self)", "")]


FEEDS_ANCHOR = "        return truncate_words(render_post(post), 40)\n"


def _add_feeds_method(body: str) -> dict:
    return {"file_path": "blog/feeds.py", "old_string": FEEDS_ANCHOR, "new_string": FEEDS_ANCHOR + "\n    def item_link(self, post):\n" + body}


def test_attribute_call_resolves_by_unique_method_name(blog_repo):
    analysis = analyze_edit(blog_repo, "Edit", _add_feeds_method("        return post.get_absolute_url()\n"), KNOWN)
    url = "blog.models.Post.get_absolute_url"
    assert ("blog.feeds.LatestPosts.item_link", url) in analysis.new_calls
    assert analysis.call_shapes[url] == [CallSite("blog.feeds.LatestPosts.item_link", 0, (), False, True)]


def test_ambiguous_method_name_is_not_guessed(blog_repo):
    # Post.save and Tag.save share the name, so post.save() resolves to neither.
    analysis = analyze_edit(blog_repo, "Edit", _add_feeds_method("        return post.save()\n"), KNOWN)
    assert all(not callee.endswith(".save") for _, callee in analysis.new_calls)


def test_constructor_call_pairs_with_init(blog_repo):
    content = "from blog.models import Post\n\n\ndef test_it():\n    assert Post('Hi', 'x').save()\n"
    analysis = analyze_edit(blog_repo, "Write", {"file_path": "tests/test_new.py", "content": content}, KNOWN)
    caller = "tests.test_new.test_it"
    assert (caller, "blog.models.Post") in analysis.new_calls
    assert (caller, "blog.models.Post.__init__") in analysis.new_calls
    assert analysis.call_shapes["blog.models.Post.__init__"] == [CallSite(caller, 2, (), False, True)]
    assert analysis.call_shapes["blog.models.Post"] == [CallSite(caller, 2, (), False, False)]
    assert analysis.call_shapes["blog.models.Post.save"] == [CallSite(caller, 0, (), False, True)]


def test_removed_symbol_in_known_still_resolves(blog_repo):
    # After a rename the old name is gone from the code graph, but the hook adds removed names to `known`.
    known = KNOWN | {"blog.models.Post.url"}
    models = blog_repo / "blog" / "models.py"
    models.write_text(models.read_text().replace("def get_absolute_url(self):", "def url(self):"))
    analysis = analyze_edit(blog_repo, "Edit", _add_feeds_method("        return post.get_absolute_url()\n"), known)
    assert ("blog.feeds.LatestPosts.item_link", "blog.models.Post.get_absolute_url") in analysis.new_calls


def test_calls_in_file_resolves_methods_and_constructors(blog_repo):
    # The file as it is on disk now, resolved like an edit: unique method names through objects, constructors
    # paired with __init__, and a bare name used before its import.
    (blog_repo / "blog" / "feeds.py").write_text(
        "from blog.models import Post\n\n\n"
        "class LatestPosts:\n"
        "    def item_link(self, post):\n"
        "        return post.get_absolute_url()\n\n"
        "    def item_new(self):\n"
        "        return Post('Hi', body='x')\n\n"
        "    def item_slug(self, post):\n"
        "        return slugify(post.title,\n                       allow_unicode=True)\n"
    )
    calls = calls_in_file(blog_repo, "blog/feeds.py", KNOWN)
    found = {(caller, callee): site for caller, callee, site in calls}

    link = found[("blog.feeds.LatestPosts.item_link", "blog.models.Post.get_absolute_url")]
    assert link == CallSite("blog.feeds.LatestPosts.item_link", 0, (), False, True)
    assert link.text == "post.get_absolute_url()"
    assert found[("blog.feeds.LatestPosts.item_new", "blog.models.Post")] == CallSite(
        "blog.feeds.LatestPosts.item_new", 1, ("body",), False, False)
    init = found[("blog.feeds.LatestPosts.item_new", "blog.models.Post.__init__")]
    assert init == CallSite("blog.feeds.LatestPosts.item_new", 1, ("body",), False, True)
    assert init.text == "Post('Hi', body='x')"
    # A call written over two lines reads as one.
    assert found[("blog.feeds.LatestPosts.item_slug", "utils.text.slugify")].text == (
        "slugify(post.title, allow_unicode=True)"
    )
    assert all(isinstance(c, tuple) and len(c) == 3 for c in calls)


def test_calls_in_file_missing_or_broken_file_is_empty(blog_repo):
    assert calls_in_file(blog_repo, "blog/gone.py", KNOWN) == []
    (blog_repo / "blog" / "broken.py").write_text("def f(:\n")
    assert calls_in_file(blog_repo, "blog/broken.py", KNOWN) == []
