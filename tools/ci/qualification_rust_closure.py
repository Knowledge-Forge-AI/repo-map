"""Resolve the complete local source closure without importing project code."""

from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOTS = ("src/main/python", "tools", "src/test/support/python")
FORBIDDEN = frozenset({"psycopg", "psycopg2", "psycopg_c", "psycopg_binary", "sqlalchemy", "sqlite3",
                       "tree_sitter", "tree_sitter_rust"})
FORBIDDEN_PRODUCT = ("common_lore_index.storage", "common_lore_index.coordinator.worker",
                     "common_lore_index.ops.rust_pilot_publication")
GUEST_PREFIX = "common_lore_index.extractors.rust_pilot.guest"
ENTRYPOINTS = ("ci.rust_pilot_qualification", "ci.d12_hosted_evidence")
CALL_ROOTS = frozenset({
    "common_lore_index.canonicalization.main",
    "common_lore_index.canonicalization.rust_pilot_family",
    "common_lore_index.graph.discovery", "common_lore_index.graph.discovery_extractors",
    "ci.d12_hosted_evidence",
})


class ClosureRefused(ValueError):
    def __init__(self, code: str, module: str | None = None) -> None:
        super().__init__(code)
        self.module = module


def module_path(root: Path, module: str) -> Path | None:
    if module.split(".", 1)[0] in FORBIDDEN or any(
            module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_PRODUCT):
        raise ClosureRefused("forbidden_host_import", module)
    for directory in ROOTS:
        base = root / directory / Path(*module.split("."))
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                if candidate.resolve() != candidate or not candidate.is_relative_to(root):
                    raise ClosureRefused("source_alias")
                return candidate
    return None


def module_identity(root: Path, path: Path) -> tuple[str, bool]:
    for directory in ROOTS:
        source = root / directory
        if path.is_relative_to(source):
            parts = list(path.relative_to(source).with_suffix("").parts)
            package = parts[-1] == "__init__"
            if package:
                parts.pop()
            return ".".join(parts), package
    raise ClosureRefused("source_outside_roots")


def imported_modules(root: Path, path: Path) -> tuple[tuple[str, bool], ...]:
    module, package = module_identity(root, path)
    parent = module.split(".") if package else module.split(".")[:-1]
    tree = ast.parse(path.read_bytes(), filename=str(path))
    result: list[tuple[str, bool]] = []
    qualification_owner = (module == "ci.rust_pilot_qualification"
                           or module.startswith("ci.qualification_rust_")
                           or module.startswith("common_lore_index.extractors.rust_pilot.")
                           or module in CALL_ROOTS)
    nodes: list[ast.AST] = list(tree.body)
    while nodes:
        node = nodes.pop()
        if not qualification_owner and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (not qualification_owner and isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"):
            nodes.extend(node.orelse)
            continue
        nodes.extend(ast.iter_child_nodes(node))
        if isinstance(node, ast.Import):
            result.extend((alias.name, False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(parent):
                    raise ClosureRefused("relative_import_outside_package")
                prefix = parent[:len(parent) - node.level + 1]
                base = ".".join([*prefix, *([] if node.module is None else node.module.split("."))])
            else:
                base = node.module or ""
            if not base:
                raise ClosureRefused("unresolved_import")
            result.append((base, False))
            result.extend((base + "." + alias.name, True) for alias in node.names if alias.name != "*")
    return tuple(result)


def required_sources(root: Path) -> set[str]:
    """Initialization closure plus explicit qualification call imports and package initializers.

    Guest programs are explicit text payloads, never host import targets.
    Deferred imports in qualification owners become explicit roots. Unrelated
    functions in legacy D12 helpers are not called or treated as imports; the
    runtime guard enforces the exclusion during every actual qualification call.
    Only standard-library modules may remain outside the local closure.
    """

    root = root.resolve()
    pending = [(name, False) for name in ENTRYPOINTS]
    seen: set[str] = set()
    paths: set[str] = set()
    while pending:
        module, optional = pending.pop()
        if module in seen:
            continue
        if module == GUEST_PREFIX or module.startswith(GUEST_PREFIX + "."):
            raise ClosureRefused("guest_host_import", module)
        path = module_path(root, module)
        if path is None:
            top = module.split(".", 1)[0]
            if optional or top in sys.stdlib_module_names or top == "__future__":
                continue
            raise ClosureRefused("unresolved_host_import", module)
        seen.add(module)
        relative = path.relative_to(root).as_posix()
        if relative in paths:
            continue
        paths.add(relative)
        parts = module.split(".")
        for length in range(1, len(parts)):
            parent = ".".join(parts[:length])
            parent_path = module_path(root, parent)
            if parent_path is not None and parent_path.name == "__init__.py":
                pending.append((parent, False))
        pending.extend(imported_modules(root, path))
    return paths
