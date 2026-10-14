import json

from airspace.indexer.parse import parse_module
from airspace.types import Briefing, CallSite, SignatureChange, Verdict
from airspace.wire import decode, encode


def _round(value):
    return decode(json.loads(json.dumps(encode(value))))


def test_engine_values_survive_the_wire():
    verdict = Verdict("hold", "Airspace hold: ...", ["a.b", "c.d"], "agent-a", "x1",
                      [Briefing("id", "utils.text.slugify", "slugify(value)", "slugify(value, *, unicode=False)", "agent-a")])
    assert _round(verdict) == verdict
    site = CallSite("blog.views.render_post", 1, ("unicode",), False, False, True, text="slugify(x, unicode=True)")
    back = _round(site)
    assert back == site and back.kwargs == ("unicode",) and back.text == site.text
    assert _round([SignatureChange("a", "a(x)", "", "b", "b(x)")]) == [SignatureChange("a", "a(x)", "", "b", "b(x)")]
    assert _round(("caller", "callee", site)) == ["caller", "callee", site]
    assert _round({"x", "a"}) == ["a", "x"]


def test_parsed_facts_survive_the_wire():
    facts = parse_module("m.py", "class C(B):\n    def f(self, x):\n        return g(x, k=1)\n")
    back = _round(facts)
    assert back == facts
    assert back.calls[0].kwargs == ("k",)
    assert back.bases == [["m.C", "B"]] or back.bases == [("m.C", "B")]
