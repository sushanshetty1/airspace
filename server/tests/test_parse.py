from pathlib import Path

from airspace.indexer.parse import module_name, parse_module

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "blog"


def _parse(rel: str):
    return parse_module(rel, (FIXTURE_REPO / rel).read_text())


def _targets(facts, caller: str) -> list[str]:
    return [c.target for c in facts.calls if c.caller == caller]


def test_module_name():
    assert module_name("blog/views.py") == "blog.views"
    assert module_name("utils/text.py") == "utils.text"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("top.py") == "top"
    assert module_name("a/b/__init__.py") == "a.b"


def test_parse_slugify_signature():
    facts = _parse("utils/text.py")
    by_q = {s.qualname: s for s in facts.symbols}
    slug = by_q["utils.text.slugify"]
    assert slug.signature == "slugify(value, allow_unicode=False)"
    assert slug.kind == "function"
    assert (slug.lineno, slug.end_lineno) == (5, 12)
    assert slug.file == "utils/text.py"
    assert slug.is_test is False
    assert len(slug.sig_hash) == 12


def test_parse_syntax_error_returns_none():
    assert parse_module("broken.py", "def f(:\n    pass\n") is None


def test_parse_records_calls_and_imports():
    facts = _parse("blog/views.py")
    assert facts.module == "blog.views"
    assert facts.imports["Post"] == "blog.models.Post"
    assert _targets(facts, "blog.views.render_post") == ["post.get_absolute_url"]
    assert _targets(facts, "blog.views.post_list") == ["render_post"]


def test_parse_records_call_on_constructor_result():
    facts = _parse("tags/views.py")
    assert sorted(_targets(facts, "tags.views.tag_create")) == ["Tag", "Tag.save"]


def test_parse_classes_methods_and_bases():
    src = (
        "import utils.text as text\n"
        "import os.path\n"
        "from a import b as c\n"
        "from .models import Post\n"
        "from . import sibling\n"
        "\n"
        "class Base:\n"
        "    pass\n"
        "\n"
        "class Child(Base, mixins.Thing):\n"
        "    async def run(self, x, *args, **kw):\n"
        "        self.helper()\n"
        "        def inner():\n"
        "            return text.slugify(x)\n"
        "        return [inner() for _ in args]\n"
        "\n"
        "    def helper(self):\n"
        "        pass\n"
        "\n"
        "helper_at_module_level()\n"
    )
    facts = parse_module("pkg/mod.py", src)
    kinds = {s.qualname: (s.kind, s.signature) for s in facts.symbols}
    assert kinds == {
        "pkg.mod.Base": ("class", "Base()"),
        "pkg.mod.Child": ("class", "Child(Base, mixins.Thing)"),
        "pkg.mod.Child.run": ("method", "run(self, x, *args, **kw)"),
        "pkg.mod.Child.helper": ("method", "helper(self)"),
    }
    assert facts.imports == {
        "text": "utils.text",
        "os": "os",
        "c": "a.b",
        "Post": "pkg.models.Post",
        "sibling": "pkg.sibling",
    }
    assert facts.bases == [("pkg.mod.Child", "Base"), ("pkg.mod.Child", "mixins.Thing")]
    # Nested function bodies count toward the enclosing method; module-level calls are ignored.
    assert sorted(_targets(facts, "pkg.mod.Child.run")) == ["inner", "self.helper", "text.slugify"]
    assert all(c.caller != "pkg.mod" for c in facts.calls)


def test_parse_relative_import_in_package_init():
    facts = parse_module("pkg/__init__.py", "from .models import Post\nfrom ..up import x\n")
    assert facts.imports["Post"] == "pkg.models.Post"
    assert facts.imports["x"] == "up.x"


def test_parse_is_test_flags():
    facts = _parse("tests/test_text.py")
    assert [s.is_test for s in facts.symbols] == [True]
    other = parse_module("app/checks.py", "def test_thing():\n    pass\n\ndef helper():\n    pass\n")
    assert {s.name: s.is_test for s in other.symbols} == {"test_thing": True, "helper": False}
    nested = parse_module("app/tests/util.py", "def helper():\n    pass\n")
    assert nested.symbols[0].is_test is True


def _call(facts, caller, target):
    return next(c for c in facts.calls if c.caller == caller and c.target == target)


def test_parse_records_call_shapes():
    src = (
        "def f(xs, kw):\n"
        "    slugify(xs, True)\n"
        "    slugify(xs, unicode=True)\n"
        "    g(*xs)\n"
        "    h(1, **kw)\n"
        "    k()\n"
    )
    facts = parse_module("m.py", src)
    shapes = [(c.target, c.nargs, c.kwargs, c.star) for c in facts.calls]
    assert shapes == [
        ("slugify", 2, (), False),
        ("slugify", 1, ("unicode",), False),
        ("g", 0, (), True),
        ("h", 1, (), True),
        ("k", 0, (), False),
    ]


def test_parse_marks_calls_on_a_constructed_instance():
    facts = _parse("tags/views.py")
    assert _call(facts, "tags.views.tag_create", "Tag.save").via_instance is True
    assert _call(facts, "tags.views.tag_create", "Tag").via_instance is False
    assert _call(facts, "tags.views.tag_create", "Tag").nargs == 1


def test_call_fact_shape_fields_default():
    from airspace.types import CallFact

    c = CallFact("m.f", "g", 3)
    assert (c.nargs, c.kwargs, c.star, c.via_instance) == (0, (), False, False)


def test_a_function_that_never_returns_a_value_carries_none_in_its_signature():
    src = (
        "def save(self):\n    self.x = 1\n\n"
        "def get(self):\n    return self.x\n\n"
        "def maybe(self):\n    if self.x:\n        return\n    return None\n\n"
        "def gen(self):\n    yield 1\n\n"
        "def outer():\n    def inner():\n        return 1\n    inner()\n\n"
        "def stub():\n    '''Doc.'''\n    ...\n\n"
        "def abstract():\n    raise NotImplementedError\n\n"
        "def annotated() -> None:\n    return\n\n"
        "def typed() -> int:\n    pass\n\n"
        "async def fetch():\n    pass\n\n"
        "def test_thing():\n    assert True\n\n"
        "class C:\n    def __init__(self):\n        self.x = 1\n"
    )
    sigs = {s.name: s.signature for s in parse_module("m.py", src).symbols}
    assert sigs["save"] == "save(self) -> None"
    assert sigs["get"] == "get(self)"
    assert sigs["maybe"] == "maybe(self) -> None"
    assert sigs["gen"] == "gen(self)"
    assert sigs["outer"] == "outer() -> None"  # the nested return belongs to inner
    assert sigs["stub"] == "stub()" and sigs["abstract"] == "abstract()"
    assert sigs["annotated"] == "annotated() -> None" and sigs["typed"] == "typed()"
    assert sigs["fetch"] == "fetch()" and sigs["test_thing"] == "test_thing()" and sigs["__init__"] == "__init__(self)"


def test_a_call_records_whether_its_result_is_used():
    src = "def f(t):\n    t.save()\n    x = t.save()\n    return g(t.save())\n"
    calls = [(c.target, c.used) for c in parse_module("m.py", src).calls]
    assert calls == [("t.save", False), ("t.save", True), ("g", True), ("t.save", True)]
