"""Python source to ModuleFacts with the standard-library ast: symbols, raw call targets, imports and bases."""

import ast
import dataclasses
import hashlib

from airspace.types import CallFact, ModuleFacts, SymbolFact

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def module_name(rel_path: str) -> str:
    """"blog/views.py" -> "blog.views"; "pkg/__init__.py" -> "pkg"; "src/flask/app.py" -> "flask.app".

    A top-level src/ is a source root (the src layout), not a package: code imports flask, not src.flask.
    """
    parts = rel_path.replace("\\", "/").removesuffix(".py").split("/")
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def _sig_hash(signature: str) -> str:
    return hashlib.sha1(signature.encode()).hexdigest()[:12]


def _is_test_path(rel_path: str) -> bool:
    return "tests" in rel_path.split("/")[:-1]


def _dotted(node: ast.AST) -> str | None:
    """Dotted text of a Name or an Attribute chain rooted at a Name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _call_target(func: ast.AST) -> str | None:
    target = _dotted(func)
    if target is not None:
        return target
    # Tag(name).save(): the receiver is an instance of Tag, so record Tag.save.
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Name):
        return f"{func.value.func.id}.{func.attr}"
    return None


def _package(module: str, rel_path: str) -> list[str]:
    parts = module.split(".")
    return parts if rel_path.endswith("__init__.py") else parts[:-1]


def _imports(tree: ast.Module, module: str, rel_path: str) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports[alias.asname] = alias.name
                else:
                    # "import utils.text" binds only the top-level name.
                    top = alias.name.split(".")[0]
                    imports[top] = top
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg = _package(module, rel_path)
                pkg = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join(p for p in [*pkg, node.module or ""] if p)
            else:
                base = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports[alias.asname or alias.name] = f"{base}.{alias.name}" if base else alias.name
    return imports


def _returns_nothing(node: ast.AST) -> bool:
    """A function whose callers always get None back: no `return value`, no yield, and a real body.

    Part of its contract, because a caller that uses the result breaks when a change drops the return. Dunder
    methods (a constructor's result is the instance), async functions (they return a coroutine), tests (nothing
    calls them) and stubs (a docstring, `...`, `pass` or a raise, as in an abstract method) are left out.
    """
    if isinstance(node, ast.AsyncFunctionDef) or node.name.startswith("test"):
        return False
    if node.name.startswith("__") and node.name.endswith("__"):
        return False
    if node.returns is not None:
        return isinstance(node.returns, ast.Constant) and node.returns.value is None
    body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    if not body or all(isinstance(s, (ast.Pass, ast.Raise)) for s in body):
        return False
    stack = list(node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue  # a nested scope returns for itself
        if isinstance(n, (ast.Yield, ast.YieldFrom)):
            return False
        if isinstance(n, ast.Return) and n.value is not None:
            if not (isinstance(n.value, ast.Constant) and n.value.value is None):
                return False
        stack.extend(ast.iter_child_nodes(n))
    return True


def _signature(node: ast.AST) -> str:
    return f"{node.name}({ast.unparse(node.args)})" + (" -> None" if _returns_nothing(node) else "")


def _call_fact(node: ast.Call, caller: str, target: str, used: bool = True) -> CallFact:
    star = any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords)
    return CallFact(
        caller=caller,
        target=target,
        lineno=node.lineno,
        nargs=sum(1 for a in node.args if not isinstance(a, ast.Starred)),
        kwargs=tuple(k.arg for k in node.keywords if k.arg is not None),
        star=star,
        via_instance=isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call),
        used=used,
        text=ast.unparse(node),
    )


def _constructed(func: ast.AST) -> dict[str, str]:
    """Names this function binds exactly once, to a call such as `app = Flask(__name__)`: name -> the call's target.

    `app.route(...)` then reads as a call on what `Flask(...)` returns, like `Flask(__name__).route(...)`. Resolution
    decides whether that target is a class; a factory function, a parameter or a name bound twice stays unresolved.
    """
    stores: dict[str, int] = {}
    calls: dict[str, str] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores[node.id] = stores.get(node.id, 0) + 1
        elif isinstance(node, ast.arg):
            stores[node.arg] = stores.get(node.arg, 0) + 2  # a parameter: its type is the caller's business
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            if isinstance(value, ast.Call):
                target = _dotted(value.func)
                if target is not None:
                    calls[node.targets[0].id] = target
    return {name: target for name, target in calls.items() if stores.get(name) == 1}


def _calls_in(func: ast.AST, caller: str) -> list[CallFact]:
    found = []
    made = _constructed(func)
    for stmt in func.body:
        # A call that is a whole statement throws its result away; every other call uses it.
        discarded = {id(n.value) for n in ast.walk(stmt) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)}
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                target = _call_target(node.func)
                if target is not None:
                    fact = _call_fact(node, caller, target, used=id(node) not in discarded)
                    head, dot, rest = target.partition(".")
                    if dot and head in made:
                        # app.route(...) after app = Flask(...): a call on the instance, so its first parameter is bound.
                        fact = dataclasses.replace(fact, target=f"{made[head]}.{rest}", via_instance=True)
                    found.append((node.lineno, node.col_offset, fact))
    # ast.walk is breadth-first; sort so the order follows the source.
    return [c for _, _, c in sorted(found, key=lambda t: (t[0], t[1]))]


def parse_module(rel_path: str, source: str) -> ModuleFacts | None:
    """Parse one file. Returns None when the source does not parse (agents often write half-finished code)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    module = module_name(rel_path)
    test_path = _is_test_path(rel_path)
    symbols: list[SymbolFact] = []
    calls: list[CallFact] = []
    bases: list[tuple[str, str]] = []

    def add(node, qualname: str, kind: str, signature: str) -> None:
        symbols.append(
            SymbolFact(
                qualname=qualname,
                name=node.name,
                kind=kind,
                file=rel_path,
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                signature=signature,
                sig_hash=_sig_hash(signature),
                is_test=test_path or node.name.startswith("test_"),
            )
        )

    for node in tree.body:
        if isinstance(node, _FUNCS):
            q = f"{module}.{node.name}"
            add(node, q, "function", _signature(node))
            calls.extend(_calls_in(node, q))
        elif isinstance(node, ast.ClassDef):
            cq = f"{module}.{node.name}"
            add(node, cq, "class", f"{node.name}({', '.join(ast.unparse(b) for b in node.bases)})")
            for base in node.bases:
                text = _dotted(base)
                if text is not None:
                    bases.append((cq, text))
            for item in node.body:
                if isinstance(item, _FUNCS):
                    mq = f"{cq}.{item.name}"
                    add(item, mq, "method", _signature(item))
                    calls.extend(_calls_in(item, mq))

    return ModuleFacts(
        module=module,
        file=rel_path,
        symbols=symbols,
        calls=calls,
        imports=_imports(tree, module, rel_path),
        bases=bases,
    )
