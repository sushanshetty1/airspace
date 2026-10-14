"""Whether a call of a given shape can bind to a signature, by Python's own binding rules. Pure functions.

A call's shape is what the parser can see without running anything: how many positional arguments, which
keyword names, whether it unpacks *args or **kwargs, and whether it is bound (called through an instance, so
the first parameter is already filled). The graph stores shapes on CALLS and COVERS edges as short strings:
"2|" (two positional), "1|unicode" (one positional, keyword unicode), "b:0|" (bound, no arguments), "*" (star).
"""

import ast
from collections.abc import Sequence

Shape = tuple[int, tuple[str, ...], bool, bool]  # (nargs, kwargs, star, bound)


def shape_key(nargs: int, kwargs: Sequence[str], star: bool, bound: bool) -> str:
    if star:
        return "*"
    return f"{'b:' if bound else ''}{nargs}|{','.join(sorted(kwargs))}"


def parse_shape(key: str) -> Shape | None:
    """The shape a key stands for, or None when the key is not one."""
    if key == "*":
        return (0, (), True, False)
    bound = key.startswith("b:")
    body = key[2:] if bound else key
    count, sep, names = body.partition("|")
    if not sep or not count.isdigit():
        return None
    return (int(count), tuple(n for n in names.split(",") if n), False, bound)


def call_fits(signature: str, nargs: int, kwargs: Sequence[str], star: bool, bound: bool) -> bool:
    """True when a call with this shape can bind to `signature` ("name(params)").

    An empty signature means the symbol was removed, so nothing fits it. A star call may unpack anything, so it
    always fits. A signature that does not parse as a def (a class line such as "Post(Base)") cannot be judged and
    is taken to fit: the check never holds on a guess.
    """
    if not signature:
        return False
    if star:
        return True
    try:
        tree = ast.parse(f"def {signature}: pass")
        fn = tree.body[0]
    except (SyntaxError, ValueError, IndexError):
        return True
    if not isinstance(fn, ast.FunctionDef):
        return True
    args = fn.args

    # Positional parameters in order, each with whether it has a default (defaults align to the end).
    positional = [(a.arg, True) for a in args.posonlyargs] + [(a.arg, False) for a in args.args]
    n_defaults = len(args.defaults)
    params = [
        {"name": name, "posonly": posonly, "default": i >= len(positional) - n_defaults}
        for i, (name, posonly) in enumerate(positional)
    ]
    if bound:
        if params:
            params = params[1:]
        elif args.vararg is None:
            return False  # nowhere for the instance to go

    if nargs > len(params) and args.vararg is None:
        return False
    filled = {p["name"] for p in params[:nargs]}

    kwonly = {a.arg: d is not None for a, d in zip(args.kwonlyargs, args.kw_defaults)}
    by_name = {p["name"]: p for p in params}
    for kw in kwargs:
        p = by_name.get(kw)
        if p is not None and not p["posonly"]:
            if kw in filled:
                return False  # given twice
            filled.add(kw)
        elif kw in kwonly:
            filled.add(kw)
        elif args.kwarg is None:
            return False  # no such parameter, and no **kwargs to take it

    if any(not p["default"] and p["name"] not in filled for p in params):
        return False
    return all(has_default or name in filled for name, has_default in kwonly.items())
