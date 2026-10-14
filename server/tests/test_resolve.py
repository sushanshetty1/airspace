from pathlib import Path

from helpers import BLOG_CALLS, BLOG_COVERS, BLOG_SYMBOLS

from airspace.indexer.parse import parse_module
from airspace.indexer.resolve import resolve_calls, resolve_target

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "blog"
KNOWN = {row[0] for row in BLOG_SYMBOLS}


def _parse(rel: str):
    return parse_module(rel, (FIXTURE_REPO / rel).read_text())


def test_resolve_imported_function():
    facts = _parse("blog/models.py")
    assert resolve_target("slugify", facts, "blog.models.Post.save", KNOWN) == "utils.text.slugify"


def test_resolve_self_method():
    src = "class Post:\n    def save(self):\n        return self.clean()\n\n    def clean(self):\n        pass\n"
    facts = parse_module("blog/models.py", src)
    # Defined in this module, so it resolves even before the graph knows it.
    assert resolve_target("self.clean", facts, "blog.models.Post.save", set()) == "blog.models.Post.clean"
    assert resolve_target("cls.clean", facts, "blog.models.Post.save", set()) == "blog.models.Post.clean"
    assert resolve_target("self.missing", facts, "blog.models.Post.save", set()) is None


def test_resolve_local_module_name():
    facts = _parse("blog/views.py")
    assert resolve_target("render_post", facts, "blog.views.post_list", KNOWN) == "blog.views.render_post"


def test_resolve_receiver_of_unknown_type_is_none():
    facts = _parse("blog/views.py")
    assert resolve_target("post.get_absolute_url", facts, "blog.views.render_post", KNOWN) is None


def test_resolve_unknown_returns_none():
    facts = _parse("utils/text.py")
    assert resolve_target("nowhere", facts, "utils.text.slugify", KNOWN) is None
    assert resolve_target("str", facts, "utils.text.slugify", KNOWN) is None
    assert resolve_target("re.sub", facts, "utils.text.slugify", KNOWN) is None


def test_resolve_imported_class_method():
    facts = _parse("tags/views.py")
    assert resolve_target("Tag.save", facts, "tags.views.tag_create", KNOWN) == "tags.models.Tag.save"
    assert resolve_target("Tag", facts, "tags.views.tag_create", KNOWN) == "tags.models.Tag"


def test_resolve_module_alias_and_exact_known():
    facts = parse_module("app/x.py", "import utils.text as text\n\ndef f():\n    text.slugify(1)\n")
    assert resolve_target("text.slugify", facts, "app.x.f", KNOWN) == "utils.text.slugify"
    assert resolve_target("utils.text.truncate_words", facts, "app.x.f", KNOWN) == "utils.text.truncate_words"


def test_resolve_calls_over_fixture_matches_seed():
    pairs = set()
    for path in sorted(FIXTURE_REPO.rglob("*.py")):
        pairs |= set(resolve_calls(_parse(path.relative_to(FIXTURE_REPO).as_posix()), KNOWN))
    assert pairs == set(BLOG_CALLS) | set(BLOG_COVERS)


def test_resolve_calls_dedupes_in_order():
    src = "from utils.text import slugify, truncate_words\n\ndef f():\n    truncate_words(slugify(1))\n    slugify(2)\n"
    facts = parse_module("app/x.py", src)
    assert resolve_calls(facts, KNOWN) == [("app.x.f", "utils.text.truncate_words"), ("app.x.f", "utils.text.slugify")]
