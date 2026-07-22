"""
parser.py — AST-based Python code structure extractor for RepoGraph AI.

Uses Python's `ast` module exclusively (no regex-based parsing) to extract:
  - File path
  - Imports (module + names imported)
  - Classes (name, base classes, docstring, line range)
  - Functions/methods (name, parent class if method, args, line range, docstring, decorators)
  - Route decorators (noted as N/A for psf/requests — it's a library, not a web framework app)
  - Config constants (module-level name = literal assignments)
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


def parse_file(file_path: str, repo_root: str | None = None) -> dict[str, Any]:
    """
    Parse a single Python file and extract its structural metadata.

    Args:
        file_path: Absolute or relative path to the .py file.
        repo_root: If provided, file paths in output are relative to this root.

    Returns:
        A dict with keys: file_path, imports, classes, functions, config_constants,
        route_decorators, notes.
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)

    result: dict[str, Any] = {
        "file_path": rel_path,
        "imports": [],
        "classes": [],
        "functions": [],
        "config_constants": [],
        "route_decorators": [],
        "notes": [],
    }

    # ── Imports ──────────────────────────────────────────────────────────
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "type": "import",
                    "module": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Resolve relative imports: prepend dots for the level
            prefix = "." * (node.level or 0)
            full_module = f"{prefix}{module}" if module else prefix
            for alias in node.names:
                result["imports"].append({
                    "type": "from_import",
                    "module": full_module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                })

    # ── Classes ──────────────────────────────────────────────────────────
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            class_info = _extract_class(node)
            result["classes"].append(class_info)

    # ── Top-level functions ──────────────────────────────────────────────
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_info = _extract_function(node, class_name=None)
            result["functions"].append(func_info)

    # ── Config constants (module-level Name = Literal) ───────────────────
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    const_val = _try_literal(node.value)
                    if const_val is not None:
                        result["config_constants"].append({
                            "name": target.id,
                            "value": const_val,
                            "line": node.lineno,
                        })
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                const_val = _try_literal(node.value)
                if const_val is not None:
                    result["config_constants"].append({
                        "name": node.target.id,
                        "value": const_val,
                        "line": node.lineno,
                    })

    # ── Route decorators ────────────────────────────────────────────────
    # Scan all functions and methods for web framework route decorators
    # e.g., @app.route, @bp.route, @app.get, @app.post, @app.errorhandler, etc.
    route_dec_names = {"route", "get", "post", "put", "delete", "patch", "errorhandler", "before_request", "after_request"}

    def _check_route_decorators(funcs: list[dict[str, Any]]) -> None:
        for fn in funcs:
            for dec in fn.get("decorators", []):
                dec_parts = dec.split(".")
                if any(part in route_dec_names for part in dec_parts):
                    result["route_decorators"].append({
                        "function": fn.get("qualified_name") or fn["name"],
                        "decorator": dec,
                        "line": fn["line_start"],
                    })

    _check_route_decorators(result["functions"])
    for cls in result["classes"]:
        _check_route_decorators(cls.get("methods", []))

    if not result["route_decorators"]:
        result["notes"].append(
            "No web-framework route decorators (@app.route, etc.) defined in this file."
        )

    return result


def _extract_class(node: ast.ClassDef) -> dict[str, Any]:
    """Extract metadata from a class definition, including its methods."""
    bases = []
    for base in node.bases:
        bases.append(_node_to_name(base))

    decorators = [_node_to_name(d) for d in node.decorator_list]
    docstring = ast.get_docstring(node)

    methods: list[dict[str, Any]] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_function(item, class_name=node.name))

    return {
        "name": node.name,
        "bases": bases,
        "decorators": decorators,
        "docstring": docstring,
        "line_start": node.lineno,
        "line_end": node.end_lineno,
        "methods": methods,
    }


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str | None,
) -> dict[str, Any]:
    """Extract metadata from a function or method definition."""
    args = _extract_args(node.args)
    decorators = [_node_to_name(d) for d in node.decorator_list]
    docstring = ast.get_docstring(node)

    # Collect calls made inside this function (best-effort static resolution)
    calls = _collect_calls(node)

    return {
        "name": node.name,
        "class_parent": class_name,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "args": args,
        "decorators": decorators,
        "docstring": docstring,
        "line_start": node.lineno,
        "line_end": node.end_lineno,
        "calls": calls,
    }


def _extract_args(arguments: ast.arguments) -> list[str]:
    """Extract argument names from a function's arguments node."""
    names: list[str] = []
    # positional-only
    for arg in arguments.posonlyargs:
        names.append(arg.arg)
    # regular positional
    for arg in arguments.args:
        names.append(arg.arg)
    # *args
    if arguments.vararg:
        names.append(f"*{arguments.vararg.arg}")
    # keyword-only
    for arg in arguments.kwonlyargs:
        names.append(arg.arg)
    # **kwargs
    if arguments.kwarg:
        names.append(f"**{arguments.kwarg.arg}")
    return names


def _collect_calls(node: ast.AST) -> list[str]:
    """Walk a function body and collect all call targets as strings (best-effort)."""
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _node_to_name(child.func)
            if name:
                calls.append(name)
    return calls


def _node_to_name(node: ast.AST) -> str:
    """
    Convert an AST node to a dotted name string (best-effort).
    Handles Name, Attribute chains, Call, Subscript, etc.
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        parent = _node_to_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    elif isinstance(node, ast.Call):
        return _node_to_name(node.func)
    elif isinstance(node, ast.Subscript):
        return _node_to_name(node.value)
    elif isinstance(node, ast.Starred):
        return _node_to_name(node.value)
    elif isinstance(node, ast.Constant):
        return repr(node.value)
    return ""


def _try_literal(node: ast.expr) -> Any | None:
    """Try to evaluate an AST expression as a literal. Returns None if not a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# Full repo parsing
# ═══════════════════════════════════════════════════════════════════════

# Default exclusion patterns — directories to skip during repo ingestion.
# ext/ contains vendored C extensions, docs/ contains Sphinx config tooling.
# Hidden directories (.*) and __pycache__ are always skipped.
DEFAULT_EXCLUSIONS: list[str] = [
    "ext",
    "docs",
    "__pycache__",
]


def parse_repo(
    repo_root: str,
    exclusions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Walk a repository and parse every .py file, returning a list of
    parsed file structures.

    Args:
        repo_root: Path to the repository root.
        exclusions: Directory names to skip (matched against any path component).
                    Defaults to DEFAULT_EXCLUSIONS.

    Returns:
        A list of parse_file() results, one per successfully parsed file.
    """
    root = Path(repo_root)
    skip = set(exclusions if exclusions is not None else DEFAULT_EXCLUSIONS)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for py_file in sorted(root.rglob("*.py")):
        # Skip hidden directories and excluded directory names
        parts = py_file.relative_to(root).parts
        if any(p.startswith(".") for p in parts):
            continue
        if any(p in skip for p in parts):
            continue

        try:
            parsed = parse_file(str(py_file), repo_root=str(root))
            results.append(parsed)
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            errors.append({
                "file": str(py_file.relative_to(root)),
                "error": f"{type(exc).__name__}: {exc}",
            })

    if errors:
        import sys as _sys
        print(f"⚠ Skipped {len(errors)} unparseable files:", file=_sys.stderr)
        for e in errors:
            print(f"  {e['file']}: {e['error']}", file=_sys.stderr)

    return results


# ═══════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python parser.py <file_path> [repo_root]   — parse one file")
        print("  python parser.py --repo <repo_root>        — parse entire repo")
        sys.exit(1)

    if sys.argv[1] == "--repo":
        repo = sys.argv[2] if len(sys.argv) > 2 else "."
        results = parse_repo(repo)
        print(json.dumps(results, indent=2, default=str))
    else:
        fpath = sys.argv[1]
        root = sys.argv[2] if len(sys.argv) > 2 else None
        result = parse_file(fpath, repo_root=root)
        print(json.dumps(result, indent=2, default=str))
