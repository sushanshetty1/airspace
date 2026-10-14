"""call_fits: can a call of a given shape bind to a signature, by Python's own binding rules."""

import pytest

from airspace.admission.compat import call_fits, parse_shape, shape_key


def fits(sig, nargs=0, kwargs=(), star=False, bound=False):
    return call_fits(sig, nargs, kwargs, star, bound)


# One test per benchmark task set, old and new signatures, with the calls each side would write.


def test_call_fits_slugify_keyword_only():
    old, new = "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)"
    assert fits(old, 1) and fits(old, 2) and fits(old, 1, ["allow_unicode"])
    assert fits(new, 1) and fits(new, 1, ["unicode"])
    assert not fits(new, 2)  # slugify(post.title, True)
    assert not fits(new, 1, ["allow_unicode"])  # slugify(post.title, allow_unicode=True)


def test_call_fits_truncate_words_limit():
    old, new = "truncate_words(text, count=30)", "truncate_words(text, *, limit=30)"
    assert fits(old, 2) and fits(old, 1, ["count"])
    assert fits(new, 1) and fits(new, 1, ["limit"])
    assert not fits(new, 2)  # truncate_words(name, 3)
    assert not fits(new, 1, ["count"])


def test_call_fits_rename_absolute_url():
    old = "get_absolute_url(self)"
    assert fits(old, 0, bound=True)
    assert not fits(old, 1, bound=True)
    # Renamed: the old name has no signature any more.
    assert not fits("", 0, bound=True)
    assert fits("url(self)", 0, bound=True)


def test_call_fits_render_post_show_body():
    old, new = "render_post(post)", "render_post(post, *, show_body)"
    assert fits(old, 1)
    assert not fits(new, 1)  # render_post(post)
    assert fits(new, 1, ["show_body"])
    assert not fits(new, 2)


def test_call_fits_post_requires_author():
    old, new = "__init__(self, title, body)", "__init__(self, title, body, author)"
    assert fits(old, 2, bound=True)
    assert not fits(new, 2, bound=True)  # Post('Hi', 'x')
    assert fits(new, 3, bound=True)
    assert fits(new, 2, ["author"], bound=True)


def test_call_fits_tag_save_returns_none():
    # A behaviour change keeps the signature, so every call still fits.
    assert fits("save(self)", 0, bound=True)


# Binding rules.


def test_star_call_always_fits():
    assert fits("f(a, *, b)", 0, star=True)
    assert fits("f()", 5, ["x"], star=True)


def test_removed_symbol_never_fits():
    assert not fits("", 0)
    assert not fits("", 0, star=True)


def test_too_many_or_too_few_positional():
    assert not fits("f(a, b)", 1)
    assert not fits("f(a, b)", 3)
    assert fits("f(a, b=1)", 1)
    assert fits("f(a, *args)", 7)


def test_keywords():
    assert fits("f(a, b)", 0, ["a", "b"])
    assert not fits("f(a, b)", 1, ["a"])  # a given twice
    assert not fits("f(a)", 1, ["z"])
    assert fits("f(a, **kw)", 1, ["z"])
    assert fits("f(a, *, k)", 1, ["k"])
    assert not fits("f(a, *, k)", 1)
    assert fits("f(a, *, k=1)", 1)


def test_positional_only():
    assert fits("f(a, /, b)", 2)
    assert not fits("f(a, /, b)", 0, ["a", "b"])
    assert fits("f(a, /, b, **kw)", 1, ["a", "b"])  # "a" lands in **kw
    assert fits("f(a=1, /)", 0)


def test_bound_drops_the_first_parameter():
    assert fits("save(self)", 0, bound=True)
    assert not fits("save(self)", 0)
    assert fits("m(self, x=1)", 1, bound=True)
    assert not fits("m(self, x=1)", 2, bound=True)
    assert fits("m(*args)", 3, bound=True)
    assert not fits("m()", 0, bound=True)
    assert fits("m(self, /, x)", 0, ["x"], bound=True)


def test_annotations_and_defaults_parse():
    assert fits("f(x: int, y: str = 'a', *rest: int, z: bool = False, **kw: str)", 1)
    assert not fits("f(x: int)", 0)


def test_unparseable_signature_fits():
    # The class signature "Post(Base)" is not a def; nothing can be judged, so nothing is held.
    assert fits("not a ( signature", 1)


def test_shape_key_round_trip():
    assert shape_key(1, (), False, False) == "1|"
    assert shape_key(2, (), False, False) == "2|"
    assert shape_key(1, ("unicode",), False, False) == "1|unicode"
    assert shape_key(1, ("b", "a"), False, False) == "1|a,b"
    assert shape_key(3, ("x",), True, False) == "*"
    assert shape_key(0, (), False, True) == "b:0|"
    for key in ("1|", "1|unicode", "2|a,b", "*", "b:0|", "b:2|k"):
        assert shape_key(*parse_shape(key)) == key
    assert parse_shape("b:1|k") == (1, ("k",), False, True, False)
    assert parse_shape("*") == (0, (), True, False, False)
    assert shape_key(0, (), False, True, True) == "v:b:0|"
    assert shape_key(1, (), True, False, True) == "v:*"
    for key in ("v:1|", "v:b:0|", "v:*"):
        assert shape_key(*parse_shape(key)) == key
    assert parse_shape("v:b:1|k") == (1, ("k",), False, True, True)


def test_a_used_result_does_not_fit_a_function_that_returns_nothing():
    assert call_fits("save(self) -> None", 0, (), False, True, used=False)
    assert not call_fits("save(self) -> None", 0, (), False, True, used=True)
    assert not call_fits("run(*args) -> None", 0, (), True, False, used=True)
    assert call_fits("save(self)", 0, (), False, True, used=True)


@pytest.mark.parametrize("bad", ["", "x|", "b:|", "1"])
def test_parse_shape_rejects_garbage(bad):
    assert parse_shape(bad) is None
