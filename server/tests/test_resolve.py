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


# Real-repo shapes: the src layout, package re-exports, base classes, and instances made in the same function.

from airspace.indexer.resolve import Known, class_bases, exports  # noqa: E402

PKG = {
    "src/shop/__init__.py": "from .app import App as App\nfrom .helpers import url_for\n",
    "src/shop/scaffold.py": "class Scaffold:\n    def route(self, rule):\n        return rule\n",
    "src/shop/app.py": (
        "from .scaffold import Scaffold\n\n\n"
        "class App(Scaffold):\n    def run(self):\n        return self.route('/')\n"
    ),
    "src/shop/helpers.py": "def url_for(endpoint):\n    return endpoint\n",
    "tests/test_app.py": (
        "import shop\nfrom shop import url_for\n\n\n"
        "def test_index():\n    app = shop.App()\n    app.route('/x')\n    assert url_for('index')\n\n\n"
        "def test_param(app):\n    app.route('/y')\n"
    ),
}


def _pkg():
    facts = {rel: parse_module(rel, src) for rel, src in PKG.items()}
    known = Known({s.qualname for f in facts.values() for s in f.symbols},
                  {k: v for f in facts.values() for k, v in exports(f).items()})
    for f in facts.values():
        known.bases.update(class_bases(f, known))
    return facts, known


def test_src_layout_is_a_source_root_not_a_package():
    facts, _ = _pkg()
    assert [s.qualname for s in facts["src/shop/helpers.py"].symbols] == ["shop.helpers.url_for"]
    assert facts["src/shop/helpers.py"].file == "src/shop/helpers.py"


def test_package_re_exports_resolve_to_where_a_name_is_defined():
    facts, known = _pkg()
    assert known.aliases == {"shop.App": "shop.app.App", "shop.url_for": "shop.helpers.url_for"}
    t = facts["tests/test_app.py"]
    assert resolve_target("url_for", t, "tests.test_app.test_index", known) == "shop.helpers.url_for"
    assert resolve_target("shop.App", t, "tests.test_app.test_index", known) == "shop.app.App"


def test_members_a_base_class_defines_resolve_through_the_bases():
    facts, known = _pkg()
    assert known.bases == {"shop.app.App": ["shop.scaffold.Scaffold"]}
    app = facts["src/shop/app.py"]
    assert resolve_target("self.route", app, "shop.app.App.run", known) == "shop.scaffold.Scaffold.route"


def test_an_instance_made_in_the_same_function_is_a_bound_call_on_its_class():
    facts, known = _pkg()
    t = facts["tests/test_app.py"]
    made = [c for c in t.calls if c.caller == "tests.test_app.test_index" and c.target.endswith(".route")]
    assert [(c.target, c.via_instance) for c in made] == [("shop.App.route", True)]
    assert resolve_target(made[0].target, t, made[0].caller, known) == "shop.scaffold.Scaffold.route"
    # A parameter's type is the caller's business: test_param's app.route stays unresolved.
    param = [c for c in t.calls if c.caller == "tests.test_app.test_param"]
    assert [resolve_target(c.target, t, c.caller, known) for c in param] == [None]


def test_known_names_round_trip_the_wire_with_their_re_exports_and_bases():
    _, known = _pkg()
    back = Known.decoded(known.encoded())
    assert set(back) == set(known) and back.aliases == known.aliases and back.bases == known.bases
    merged = {"x.y"} | back
    assert isinstance(merged, Known) and merged.aliases == known.aliases and "x.y" in merged
