"""
graph_builder.py — Builds a knowledge graph from parsed Python repository data.

Node types: File, Class, Function
Edge types: CONTAINS, CALLS, IMPORTS

The graph is persisted as graph.json with a documented schema (see SCHEMA.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from parser import parse_repo


# ═══════════════════════════════════════════════════════════════════════
# Node & Edge ID generation
# ═══════════════════════════════════════════════════════════════════════


def _file_id(file_path: str) -> str:
    """Generate a unique ID for a File node."""
    return f"file:{file_path}"


def _class_id(file_path: str, class_name: str) -> str:
    """Generate a unique ID for a Class node."""
    return f"class:{file_path}:{class_name}"


def _function_id(file_path: str, func_name: str, class_name: str | None = None) -> str:
    """Generate a unique ID for a Function node."""
    if class_name:
        return f"func:{file_path}:{class_name}.{func_name}"
    return f"func:{file_path}:{func_name}"


# ═══════════════════════════════════════════════════════════════════════
# Import resolution
# ═══════════════════════════════════════════════════════════════════════


def _resolve_relative_import(
    importing_file: str,
    module: str,
    all_file_paths: set[str],
) -> str | None:
    """
    Resolve a relative import (e.g., '.compat' from 'src/requests/auth.py')
    to an actual file path in the repo.

    Returns the matching file path or None if unresolved.
    """
    if not module:
        return None

    # Count leading dots for relative level
    level = 0
    for ch in module:
        if ch == ".":
            level += 1
        else:
            break

    module_part = module[level:]  # e.g., "compat" from ".compat"

    if level == 0:
        # Absolute import — try to find in repo
        candidates = _module_to_paths(module_part)
    else:
        # Relative import — resolve from importing file's directory
        parts = Path(importing_file).parts
        # Go up `level` directories from the file's parent
        if level <= len(parts) - 1:
            base = Path(*parts[: len(parts) - level])
        else:
            return None

        if module_part:
            candidates = [
                str(base / module_part.replace(".", "/")) + ".py",
                str(base / module_part.replace(".", "/") / "__init__.py"),
            ]
        else:
            candidates = [str(base / "__init__.py")]

    for c in candidates:
        if c in all_file_paths:
            return c

    return None


def _module_to_paths(module: str) -> list[str]:
    """Convert a dotted module name to candidate file paths."""
    path_base = module.replace(".", "/")
    return [
        f"{path_base}.py",
        f"{path_base}/__init__.py",
        f"src/{path_base}.py",
        f"src/{path_base}/__init__.py",
    ]


# ═══════════════════════════════════════════════════════════════════════
# Call resolution
# ═══════════════════════════════════════════════════════════════════════


def _resolve_call(
    call_name: str,
    current_file: str,
    current_class: str | None,
    func_index: dict[str, list[str]],
) -> tuple[str | None, bool]:
    """
    Best-effort static resolution of a call target to a function ID.

    Returns (function_id, resolved: bool).
    Resolution strategy:
      1. If call is `self.<method>`, look in current class
      2. If call is a simple name, look in current file, then global index
      3. If call is `module.func`, try to match against known functions
    """
    # Skip built-in / standard library calls
    builtins = {
        "print", "len", "range", "type", "isinstance", "getattr", "setattr",
        "hasattr", "str", "int", "float", "bool", "list", "dict", "tuple",
        "set", "frozenset", "bytes", "bytearray", "super", "object", "zip",
        "map", "filter", "sorted", "reversed", "enumerate", "any", "all",
        "min", "max", "sum", "abs", "repr", "id", "hash", "callable",
        "iter", "next", "open", "format", "chr", "ord", "hex", "oct", "bin",
        "vars", "dir", "globals", "locals", "staticmethod", "classmethod",
        "property", "NotImplementedError", "ValueError", "TypeError",
        "KeyError", "AttributeError", "RuntimeError", "StopIteration",
        "OSError", "IOError",
    }

    # Strip self. prefix for method resolution
    if call_name.startswith("self."):
        method_name = call_name[5:]
        # Remove any further dotted access (e.g., self._thread_local.chal.get → skip)
        if "." in method_name:
            return None, False
        if current_class:
            candidate = _function_id(current_file, method_name, current_class)
            if candidate in func_index.get(method_name, []):
                return candidate, True
        return None, False

    # Simple name (no dots) — look in current file first
    simple_name = call_name.split(".")[-1] if "." in call_name else call_name
    if simple_name in builtins:
        return None, False

    # Try exact match in current file
    candidates = func_index.get(simple_name, [])
    for cid in candidates:
        if current_file in cid:
            return cid, True

    # Try any match
    if candidates:
        return candidates[0], True

    return None, False


# ═══════════════════════════════════════════════════════════════════════
# Graph construction
# ═══════════════════════════════════════════════════════════════════════


def build_graph(parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build a knowledge graph from parsed repository data.

    Returns a dict with keys: nodes, edges, metadata.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    unresolved_calls: list[dict[str, str]] = []

    all_file_paths = {f["file_path"] for f in parsed_files}

    # ── Pass 1: Create all nodes ─────────────────────────────────────
    func_index: dict[str, list[str]] = {}  # name → [function_ids]

    route_dec_keywords = {"route", "get", "post", "put", "delete", "patch", "errorhandler", "before_request", "after_request", "endpoint"}

    for pf in parsed_files:
        fp = pf["file_path"]

        # File node
        nodes.append({
            "id": _file_id(fp),
            "type": "File",
            "name": fp.split("/")[-1],
            "file": fp,
            "line_start": 1,
            "line_end": None,
            "docstring": None,
            "signature": None,
            "config_constants": pf.get("config_constants", []),
        })

        # Class nodes
        for cls in pf["classes"]:
            cls_id = _class_id(fp, cls["name"])
            nodes.append({
                "id": cls_id,
                "type": "Class",
                "name": cls["name"],
                "file": fp,
                "line_start": cls["line_start"],
                "line_end": cls["line_end"],
                "docstring": cls["docstring"],
                "signature": None,
                "bases": cls["bases"],
                "decorators": cls["decorators"],
            })

            # CONTAINS: File → Class
            edges.append({
                "source": _file_id(fp),
                "target": cls_id,
                "type": "CONTAINS",
            })

            # Method nodes (Function type with class_parent)
            for method in cls["methods"]:
                func_id = _function_id(fp, method["name"], cls["name"])
                sig = f"{method['name']}({', '.join(method['args'])})"
                
                # Check route decorators
                route_decs = [
                    d for d in method.get("decorators", [])
                    if any(k in d.split(".") for k in route_dec_keywords)
                ]
                is_route = len(route_decs) > 0
                is_cfg = "config" in cls["name"].lower() or "config" in method["name"].lower()

                nodes.append({
                    "id": func_id,
                    "type": "Function",
                    "name": method["name"],
                    "qualified_name": f"{cls['name']}.{method['name']}",
                    "file": fp,
                    "line_start": method["line_start"],
                    "line_end": method["line_end"],
                    "docstring": method["docstring"],
                    "signature": sig,
                    "class_parent": cls["name"],
                    "is_async": method["is_async"],
                    "decorators": method["decorators"],
                    "args": method["args"],
                    "is_route": is_route,
                    "route_decorators": route_decs,
                    "is_config": is_cfg,
                })

                # CONTAINS: Class → Method
                edges.append({
                    "source": cls_id,
                    "target": func_id,
                    "type": "CONTAINS",
                })

                # Index for call resolution
                func_index.setdefault(method["name"], []).append(func_id)

        # Top-level function nodes
        for func in pf["functions"]:
            func_id = _function_id(fp, func["name"])
            sig = f"{func['name']}({', '.join(func['args'])})"

            route_decs = [
                d for d in func.get("decorators", [])
                if any(k in d.split(".") for k in route_dec_keywords)
            ]
            is_route = len(route_decs) > 0
            is_cfg = "config" in fp.lower() or "config" in func["name"].lower()

            nodes.append({
                "id": func_id,
                "type": "Function",
                "name": func["name"],
                "qualified_name": func["name"],
                "file": fp,
                "line_start": func["line_start"],
                "line_end": func["line_end"],
                "docstring": func["docstring"],
                "signature": sig,
                "class_parent": None,
                "is_async": func["is_async"],
                "decorators": func["decorators"],
                "args": func["args"],
                "is_route": is_route,
                "route_decorators": route_decs,
                "is_config": is_cfg,
            })

            # CONTAINS: File → Function
            edges.append({
                "source": _file_id(fp),
                "target": func_id,
                "type": "CONTAINS",
            })

            func_index.setdefault(func["name"], []).append(func_id)

    # ── Pass 2: IMPORTS edges ────────────────────────────────────────
    for pf in parsed_files:
        fp = pf["file_path"]
        # Deduplicate imported modules per file
        seen_imports: set[str] = set()
        for imp in pf["imports"]:
            mod = imp["module"]
            if mod in seen_imports:
                continue
            seen_imports.add(mod)

            resolved = _resolve_relative_import(fp, mod, all_file_paths)
            if resolved and resolved != fp:
                edges.append({
                    "source": _file_id(fp),
                    "target": _file_id(resolved),
                    "type": "IMPORTS",
                    "module": mod,
                })

    # ── Pass 3: CALLS edges ──────────────────────────────────────────
    for pf in parsed_files:
        fp = pf["file_path"]

        # Top-level functions
        for func in pf["functions"]:
            caller_id = _function_id(fp, func["name"])
            seen_call_edges: set[str] = set()
            for call_name in func.get("calls", []):
                target_id, resolved = _resolve_call(
                    call_name, fp, None, func_index
                )
                if resolved and target_id and target_id != caller_id:
                    edge_key = f"{caller_id}->{target_id}"
                    if edge_key not in seen_call_edges:
                        seen_call_edges.add(edge_key)
                        edges.append({
                            "source": caller_id,
                            "target": target_id,
                            "type": "CALLS",
                            "call_expression": call_name,
                        })
                elif not resolved:
                    unresolved_calls.append({
                        "caller": caller_id,
                        "call_expression": call_name,
                    })

        # Methods
        for cls in pf["classes"]:
            for method in cls["methods"]:
                caller_id = _function_id(fp, method["name"], cls["name"])
                seen_call_edges: set[str] = set()
                for call_name in method.get("calls", []):
                    target_id, resolved = _resolve_call(
                        call_name, fp, cls["name"], func_index
                    )
                    if resolved and target_id and target_id != caller_id:
                        edge_key = f"{caller_id}->{target_id}"
                        if edge_key not in seen_call_edges:
                            seen_call_edges.add(edge_key)
                            edges.append({
                                "source": caller_id,
                                "target": target_id,
                                "type": "CALLS",
                                "call_expression": call_name,
                            })
                    elif not resolved:
                        unresolved_calls.append({
                            "caller": caller_id,
                            "call_expression": call_name,
                        })

    # ── Dedup unresolved calls ───────────────────────────────────────
    seen_unresolved: set[str] = set()
    deduped_unresolved: list[dict[str, str]] = []
    for u in unresolved_calls:
        key = f"{u['caller']}:{u['call_expression']}"
        if key not in seen_unresolved:
            seen_unresolved.add(key)
            deduped_unresolved.append(u)

    # ── Build metadata ───────────────────────────────────────────────
    node_counts = {}
    for n in nodes:
        node_counts[n["type"]] = node_counts.get(n["type"], 0) + 1

    edge_counts = {}
    for e in edges:
        edge_counts[e["type"]] = edge_counts.get(e["type"], 0) + 1

    metadata = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "unresolved_call_count": len(deduped_unresolved),
        "files_parsed": len(parsed_files),
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "unresolved_calls": deduped_unresolved,
        "metadata": metadata,
    }


def save_graph(graph: dict[str, Any], output_path: str = "graph.json") -> None:
    """Persist the graph to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, default=str)
    print(f"✓ Graph saved to {output_path}")


def print_summary(graph: dict[str, Any]) -> None:
    """Print summary statistics for the graph."""
    meta = graph["metadata"]
    print("\n" + "=" * 60)
    print("  KNOWLEDGE GRAPH — SUMMARY STATISTICS")
    print("=" * 60)
    print(f"\n  Files parsed:       {meta['files_parsed']}")
    print(f"  Total nodes:        {meta['total_nodes']}")
    print(f"  Total edges:        {meta['total_edges']}")
    print(f"\n  Node counts by type:")
    for ntype, count in sorted(meta["node_counts"].items()):
        print(f"    {ntype:20s} {count:>5d}")
    print(f"\n  Edge counts by type:")
    for etype, count in sorted(meta["edge_counts"].items()):
        print(f"    {etype:20s} {count:>5d}")
    print(f"\n  Unresolved calls:   {meta['unresolved_call_count']}")
    print("=" * 60 + "\n")


# ═══════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python graph_builder.py <repo_root> [output_path]")
        sys.exit(1)

    repo_root = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "graph.json"

    print(f"Parsing repository: {repo_root}")
    parsed = parse_repo(repo_root)
    print(f"Parsed {len(parsed)} files")

    print("Building knowledge graph...")
    graph = build_graph(parsed)
    print_summary(graph)

    save_graph(graph, output)
