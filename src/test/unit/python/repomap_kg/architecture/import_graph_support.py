"""Static production import graph shared by architecture and server owners."""
from __future__ import annotations

import ast
from pathlib import Path


def _source_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src/main/python"
        if candidate.is_dir():
            return candidate
    raise AssertionError("production source root is unavailable")


def _production_modules() -> dict[str, Path]:
    source_root = _source_root()
    module_paths: dict[str, Path] = {}
    for path in (source_root / "repomap_kg").rglob("*.py"):
        parts = list(path.relative_to(source_root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module_paths[".".join(parts)] = path
    return module_paths


def _from_target(
    module: str,
    path: Path,
    level: int,
    imported_module: str | None,
) -> str:
    if level == 0:
        return imported_module or ""
    parts = module.split(".")
    if path.name != "__init__.py":
        parts.pop()
    if level:
        parts = parts[: len(parts) - level + 1]
    if imported_module:
        parts.extend(imported_module.split("."))
    return ".".join(parts)


def _import_graph() -> tuple[dict[str, set[str]], dict[str, ast.AST]]:
    module_paths = _production_modules()
    graph: dict[str, set[str]] = {module: set() for module in module_paths}
    trees: dict[str, ast.AST] = {}
    for module, path in module_paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[module] = tree
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = _from_target(module, path, node.level, node.module)
                targets.append(target)
                targets.extend(f"{target}.{alias.name}" for alias in node.names)
            graph[module].update(
                target for target in targets if target in module_paths and target != module
            )
    return graph, trees


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> set[frozenset[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    components: set[frozenset[str]] = set()

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        low_links[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)
        for dependency in graph[module]:
            if dependency not in indices:
                visit(dependency)
                low_links[module] = min(low_links[module], low_links[dependency])
            elif dependency in on_stack:
                low_links[module] = min(low_links[module], indices[dependency])
        if low_links[module] != indices[module]:
            return
        component: set[str] = set()
        while True:
            dependency = stack.pop()
            on_stack.remove(dependency)
            component.add(dependency)
            if dependency == module:
                break
        if len(component) > 1:
            components.add(frozenset(component))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return components


