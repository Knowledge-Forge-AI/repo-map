"""Static import dependency extraction and cohort dependency graph for retention."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping, Sequence

from ci.python_retention_operations import detect_dynamic_calls, dynamic_operations


PACKAGE_ROOTS = (
    "src/main/python", "tools", "src/test/support/python",
    "src/test/unit/python", "src/test/int/python", "",
)
KNOWN_THIRD_PARTY = frozenset({
    "coverage", "docker", "mypy", "psycopg", "psutil",
    "pytest", "requests", "ruff", "setuptools", "typing_extensions", "xdist",
})


def validate_candidate_path(path_str: str, repo_root: Path) -> tuple[Path, str]:
    """Validate relative repository path, preventing directory traversal and aliases."""
    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError(f"invalid candidate path: {path_str!r}")
    posix_path = PurePosixPath(path_str)
    root_resolved = repo_root.resolve()
    if posix_path.is_absolute() or ".." in posix_path.parts:
        raise ValueError(f"path escapes repository root: {path_str}")
    resolved = (repo_root / posix_path).resolve()
    try:
        relative = resolved.relative_to(root_resolved).as_posix()
    except ValueError as error:
        raise ValueError(f"path escapes repository root: {path_str}") from error
    lexical = root_resolved / path_str
    try:
        lexical_relative = lexical.relative_to(root_resolved).as_posix()
    except ValueError as error:
        raise ValueError(f"path alias cannot change checked identity: {path_str}") from error
    if lexical_relative != relative:
        raise ValueError(f"path alias cannot change checked identity: {path_str}")
    if not resolved.is_file():
        raise ValueError(f"path is not an existing file: {path_str}")
    return resolved, relative


FIRST_PARTY_PREFIXES = frozenset({
    "repomap_kg", "ci", "repomap_test_support", "tools",
})


def is_external_name(name: str) -> bool:
    """Return True if top-level module is known stdlib or installed third party."""
    if name == "__main__":
        # Python supplies the already-running entry namespace. Importing this
        # exact name reads that namespace; it does not load repository source.
        return True
    top = name.split(".")[0]
    if top in FIRST_PARTY_PREFIXES:
        return False
    if top in sys.stdlib_module_names or top in KNOWN_THIRD_PARTY:
        return True
    try:
        dist = importlib.metadata.distribution(top)
        if dist.metadata.get("Name") in ("repomap-kg", "repomap_kg"):
            return False
        return True
    except (importlib.metadata.PackageNotFoundError, ValueError):
        pass
    return top.lower().replace("-", "_") in KNOWN_THIRD_PARTY


def map_candidate_modules(
    candidate_paths: Sequence[str],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return module_to_path lookup and parent package __init__ dependencies."""
    module_to_path: dict[str, str] = {}
    ambiguous: set[str] = set()
    package_inits: dict[str, set[str]] = {p: set() for p in candidate_paths}
    candidates_set = set(candidate_paths)

    for p in candidate_paths:
        for root_str in PACKAGE_ROOTS:
            if root_str and not p.startswith(root_str + "/"):
                continue
            rel = p[len(root_str) + 1 :] if root_str else p
            if not rel.endswith(".py"):
                continue
            stem = rel[:-3]
            mod = stem[:-9].replace("/", ".") if stem.endswith("/__init__") else (
                "" if stem == "__init__" else stem.replace("/", ".")
            )
            if mod:
                if mod in module_to_path and module_to_path[mod] != p:
                    ambiguous.add(mod)
                module_to_path[mod] = p

            parts = rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                init_rel = "/".join(parts[:i]) + "/__init__.py"
                init_p = f"{root_str}/{init_rel}" if root_str else init_rel
                if init_p in candidates_set and init_p != p:
                    package_inits[p].add(init_p)
    for module in ambiguous:
        del module_to_path[module]
    return module_to_path, package_inits


def _package_parts_for_path(p: str) -> list[str]:
    for root_str in PACKAGE_ROOTS:
        if root_str and not p.startswith(root_str + "/"):
            continue
        rel = p[len(root_str) + 1 :] if root_str else p
        if not rel.endswith(".py"):
            continue
        stem = rel[:-3]
        if stem.endswith("/__init__"):
            return stem[:-9].split("/") if stem[:-9] else []
        return [] if stem == "__init__" else stem.split("/")[:-1]
    return []


def _detect_dynamic_calls(tree: ast.AST) -> list[str]:
    return detect_dynamic_calls(tree)


def _match_module(
    target: str,
    module_to_path: Mapping[str, str],
    package_inits: Mapping[str, set[str]],
    deps: set[str],
) -> bool:
    if target in module_to_path:
        dep = module_to_path[target]
        deps.add(dep)
        deps.update(package_inits.get(dep, ()))
        return True
    return False


def _resolve_import_from(
    node: ast.ImportFrom,
    path: str,
    module_to_path: Mapping[str, str],
    package_inits: Mapping[str, set[str]],
    deps: set[str],
    unresolved: list[str],
) -> None:
    if node.level > 0:
        pkg_parts = _package_parts_for_path(path)
        if node.level > len(pkg_parts):
            unresolved.append(f"relative import level {node.level} escapes package in {path}")
            return
        base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
        target_mod = ".".join(base + node.module.split(".")) if base and node.module else (
            node.module or ".".join(base)
        )
        for alias in node.names:
            candidate = f"{target_mod}.{alias.name}" if target_mod else alias.name
            if not _match_module(candidate, module_to_path, package_inits, deps) and not (
                target_mod and _match_module(target_mod, module_to_path, package_inits, deps)
            ):
                unresolved.append(candidate)
        return

    mod = node.module or ""
    for alias in node.names:
        candidate = f"{mod}.{alias.name}" if mod else alias.name
        if not _match_module(candidate, module_to_path, package_inits, deps) and not (
            mod and _match_module(mod, module_to_path, package_inits, deps)
        ):
            if not is_external_name(mod or alias.name):
                unresolved.append(candidate)


def _resolve_import(
    node: ast.Import,
    module_to_path: Mapping[str, str],
    package_inits: Mapping[str, set[str]],
    deps: set[str],
    unresolved: list[str],
) -> None:
    for alias in node.names:
        if not _match_module(alias.name, module_to_path, package_inits, deps):
            if not is_external_name(alias.name):
                unresolved.append(alias.name)


def build_dependency_graph(
    repo_root: Path,
    candidate_paths: Sequence[str],
) -> dict[str, Any]:
    """Build complete static source import graph without executing target code."""
    module_to_path, package_inits = map_candidate_modules(candidate_paths)
    dependencies: dict[str, list[str]] = {}
    dynamic_uncertainty: dict[str, list[str]] = {}
    dynamic_operations_map: dict[str, list[dict[str, Any]]] = {}
    unresolved_imports: dict[str, list[str]] = {}
    errors: dict[str, str] = {}

    for p in candidate_paths:
        try:
            full_path, rel = validate_candidate_path(p, repo_root)
        except Exception as error:
            errors[p] = f"path validation failed: {error}"
            dependencies[p] = []
            continue
        try:
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except Exception as error:
            errors[rel] = f"parse error: {error}"
            dependencies[rel] = []
            continue

        dyn_ops = dynamic_operations(tree)
        if dyn_ops:
            dynamic_operations_map[rel] = dyn_ops
        dyn = _detect_dynamic_calls(tree)
        if dyn:
            dynamic_uncertainty[rel] = dyn

        file_deps: set[str] = set()
        file_unresolved: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                _resolve_import(node, module_to_path, package_inits, file_deps, file_unresolved)
            elif isinstance(node, ast.ImportFrom):
                _resolve_import_from(
                    node, rel, module_to_path, package_inits, file_deps, file_unresolved
                )

        file_deps.update(package_inits.get(rel, ()))
        file_deps.discard(rel)
        dependencies[rel] = sorted(file_deps)
        if file_unresolved:
            unresolved_imports[rel] = sorted(file_unresolved)

    from ci.python_retention_dynamic import apply_dynamic_boundaries

    return apply_dynamic_boundaries(repo_root, candidate_paths, {
        "dependencies": dependencies,
        "static_dependencies": {p: list(edges) for p, edges in dependencies.items()},
        "dynamic_uncertainty": dynamic_uncertainty,
        "dynamic_operations": dynamic_operations_map,
        "unresolved_imports": unresolved_imports,
        "errors": errors,
        "module_to_path": module_to_path,
        "package_inits": {p: sorted(package_inits[p]) for p in package_inits},
    })


def cohort_leaving_dependencies(
    cohort_members: Sequence[str],
    graph_dependencies: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return sorted unique repository dependencies leaving the cohort."""
    members_set = set(cohort_members)
    leaving: set[str] = set()
    for m in cohort_members:
        for dep in graph_dependencies.get(m, ()):
            if dep not in members_set:
                leaving.add(dep)
    return sorted(leaving)


def find_cross_cohort_cycles(
    cohorts: Sequence[Mapping[str, Any]],
    graph_dependencies: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    """Detect circular dependencies between distinct cohorts using Tarjan's SCC."""
    path_to_cohort: dict[str, str] = {}
    cohort_ids: set[str] = set()
    for c in cohorts:
        cid = str(c.get("id", ""))
        cohort_ids.add(cid)
        for m in c.get("members", []):
            path_to_cohort[str(m)] = cid

    cohort_deps: dict[str, set[str]] = {cid: set() for cid in cohort_ids}
    for c in cohorts:
        cid = str(c.get("id", ""))
        leaving = cohort_leaving_dependencies(c.get("members", []), graph_dependencies)
        for dep in leaving:
            other_id = path_to_cohort.get(dep)
            if other_id is not None and other_id != cid:
                cohort_deps[cid].add(other_id)

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: dict[str, list[str]] = {}

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for succ in sorted(cohort_deps.get(node, ())):
            if succ not in indices:
                strongconnect(succ)
                lowlinks[node] = min(lowlinks[node], lowlinks[succ])
            elif succ in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[succ])

        if lowlinks[node] == indices[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == node:
                    break
            if len(scc) > 1:
                sorted_scc = sorted(scc)
                for member in sorted_scc:
                    cycles[member] = sorted_scc

    for cid in sorted(cohort_ids):
        if cid not in indices:
            strongconnect(cid)

    return cycles


def bind_source_identities(
    repo_root: Path, paths: Sequence[str]
) -> dict[str, str]:
    """Compute deterministic SHA-256 digests for exact paths."""
    digests: dict[str, str] = {}
    for p in sorted(paths):
        full_path, rel = validate_candidate_path(p, repo_root)
        digests[rel] = hashlib.sha256(full_path.read_bytes()).hexdigest()
    return digests


def verify_source_identities(
    repo_root: Path, expected_digests: Mapping[str, str]
) -> None:
    """Verify that candidate paths have not drifted from expected digests."""
    for p in sorted(expected_digests):
        expected = expected_digests[p]
        full_path, rel = validate_candidate_path(p, repo_root)
        actual = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"source identity binding mismatch for {p}")
