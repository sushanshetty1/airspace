"""Python source to ModuleFacts with the standard-library ast: symbols, raw call targets, imports and bases."""

import ast
import hashlib

from airspace.types import CallFact, ModuleFacts, SymbolFact

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def module_name(rel_path: str) -> str:
    """"blog/views.py" -> "blog.views"; "pkg/__init__.py" -> "pkg"."""
    parts = rel_path.replace("\\", "/").removesuffix(".py").split("/")
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


def _calls_in(func: ast.AST, caller: str) -> list[CallFact]:
    found = []
    for stmt in func.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                target = _call_target(node.func)
                if target is not None:
                    found.append((node.lineno, node.col_offset, CallFact(caller, target, node.lineno)))
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
            add(node, q, "function", f"{node.name}({ast.unparse(node.args)})")
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
                    add(item, mq, "method", f"{item.name}({ast.unparse(item.args)})")
                    calls.extend(_calls_in(item, mq))

    return ModuleFacts(
        module=module,
        file=rel_path,
        symbols=symbols,
        calls=calls,
        imports=_imports(tree, module, rel_path),
        bases=bases,
    )
