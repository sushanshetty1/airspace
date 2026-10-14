from helpers import BLOG_SYMBOLS

from airspace.hooks.edit_analysis import analyze_edit, apply_tool_input
from airspace.types import EditAnalysis

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
