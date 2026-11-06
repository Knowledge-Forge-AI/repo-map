"""Static source resolution of legacy extractor names and dispatch calls.

The resolver parses RepoMap's own product source with :mod:`ast`; it never
imports or executes the modules it inspects. For every ``RawObservation(...)``
construction it resolves the ``extractor=`` value through the forms the
product actually uses: literals, module constants, import aliases,
``_extractor_name()`` helpers that ``getattr`` a constant from a fixed module,
and helper parameters supplied by callers. Anything else is reported as
unresolved so that the registry cannot silently miss an owner.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

PACKAGE = "common_lore_index"
DISPATCH_MODULE = "common_lore_index.graph.discovery"
DISPATCH_FUNCTION = "extract_observations_from_repository_files"
_MAX_DEPTH = 8
NON_LEGACY_PRODUCT_PREFIXES = (f"{PACKAGE}.extractors.rust_pilot",)


def product_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src/main/python"
        if (candidate / PACKAGE).is_dir():
            return candidate
    raise AssertionError("product source root is unavailable")


def product_trees(root: Path | None = None) -> dict[str, ast.Module]:
    base = root or product_root()
    trees: dict[str, ast.Module] = {}
    for path in sorted((base / PACKAGE).rglob("*.py")):
        parts = list(path.relative_to(base).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        if any(module == prefix or module.startswith(prefix + ".")
               for prefix in NON_LEGACY_PRODUCT_PREFIXES):
            continue
        trees[module] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return trees


def _is_raw_observation_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "RawObservation") or (
        isinstance(func, ast.Attribute) and func.attr == "RawObservation"
    )


def _innermost_functions(tree: ast.Module) -> dict[int, ast.FunctionDef]:
    owners: dict[int, ast.FunctionDef] = {}
    for function in ast.walk(tree):  # breadth-first: inner definitions override outer
        if isinstance(function, ast.FunctionDef):
            for node in ast.walk(function):
                owners[id(node)] = function
    return owners


class _Resolver:
    def __init__(self, trees: dict[str, ast.Module]) -> None:
        self.trees = trees
        self.unresolved: set[str] = set()

    def _top(self, module: str, name: str) -> tuple[ast.AST | None, str | None]:
        found: tuple[ast.AST | None, str | None] = (None, None)
        for node in self.trees[module].body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets
            ):
                found = (node, None)
            elif isinstance(node, ast.FunctionDef) and node.name == name:
                found = (node, None)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if (alias.asname or alias.name) == name:
                        found = (alias, node.module)
        return found

    def constant(self, module: str, name: str, depth: int) -> set[str]:
        if depth > _MAX_DEPTH or module not in self.trees:
            self.unresolved.add(f"{module}:{name}")
            return set()
        node, source = self._top(module, name)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            return {node.value.value}
        if isinstance(node, ast.alias) and source is not None:
            return self.constant(source, node.name, depth + 1)
        if isinstance(node, ast.FunctionDef):
            values: set[str] = set()
            for item in ast.walk(node):
                if isinstance(item, ast.Return) and item.value is not None:
                    values |= self.expression(module, item.value, node, depth + 1)
            return values
        self.unresolved.add(f"{module}:{name}")
        return set()

    def _getattr_helper(self, module: str, call: ast.Call, depth: int) -> set[str]:
        if not isinstance(call.func, ast.Name) or len(call.args) != 1:
            return set()
        argument = call.args[0]
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            return set()
        attribute = argument.value
        helper, _ = self._top(module, call.func.id)
        if not isinstance(helper, ast.FunctionDef):
            return set()
        imported = {
            alias.asname or alias.name: f"{node.module}.{alias.name}"
            for node in ast.walk(helper) if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        for node in ast.walk(helper):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and node.args):
                continue
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id in imported:
                return self.constant(imported[target.id], attribute, depth + 1)
        return set()

    def expression(self, module: str, value: ast.expr, function: ast.FunctionDef | None,
                   depth: int = 0) -> set[str]:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.Name):
            parameters = set() if function is None else {
                arg.arg for arg in (*function.args.args, *function.args.kwonlyargs)
            }
            if function is not None and value.id in parameters:
                return self.callers(module, function.name, value.id, depth + 1)
            return self.constant(module, value.id, depth)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and not value.args:
            return self.constant(module, value.func.id, depth)
        if isinstance(value, ast.Call):
            resolved = self._getattr_helper(module, value, depth)
            if resolved:
                return resolved
        self.unresolved.add(f"{module}:{ast.unparse(value)}")
        return set()

    def callers(self, module: str, function: str, parameter: str, depth: int) -> set[str]:
        values: set[str] = set()
        for caller, tree in self.trees.items():
            local_names = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == module
                for alias in node.names if alias.name == function
            }
            if not local_names:
                continue
            functions = _innermost_functions(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id in local_names:
                    for keyword in node.keywords:
                        if keyword.arg == parameter:
                            values |= self.expression(caller, keyword.value,
                                                      functions.get(id(node)), depth)
        if not values:
            self.unresolved.add(f"{module}:{function}({parameter})")
        return values


def resolve_extractor_owners(
    trees: dict[str, ast.Module] | None = None,
) -> tuple[dict[str, frozenset[str]], tuple[str, ...]]:
    """Return extractor name -> emitting modules, plus unresolved expressions.

    Every ``extractor=`` value is resolved; an attribute such as
    ``module.CONST`` or ``record.extractor`` is reported as unresolved rather
    than skipped, so a new emitter cannot hide behind attribute access.
    """

    source = trees or product_trees()
    resolver = _Resolver(source)
    owners: defaultdict[str, set[str]] = defaultdict(set)
    for module, tree in source.items():
        functions = _innermost_functions(tree)
        for node in ast.walk(tree):
            if not _is_raw_observation_call(node):
                continue
            assert isinstance(node, ast.Call)
            for keyword in node.keywords:
                if keyword.arg != "extractor":
                    continue
                for name in resolver.expression(module, keyword.value, functions.get(id(node))):
                    owners[name].add(module)
    return ({name: frozenset(modules) for name, modules in owners.items()},
            tuple(sorted(resolver.unresolved)))


def raw_observation_calls_without_extractor(
    trees: dict[str, ast.Module] | None = None,
) -> tuple[str, ...]:
    """Return constructions without an explicit ``extractor=`` keyword.

    A ``**mapping`` splat does not count: its extractor cannot be resolved.
    """

    source = trees or product_trees()
    return tuple(sorted(
        f"{module}:{node.lineno}"
        for module, tree in source.items() for node in ast.walk(tree)
        if _is_raw_observation_call(node) and isinstance(node, ast.Call)
        and not any(keyword.arg == "extractor" for keyword in node.keywords)
    ))


def implementation_module(trees: dict[str, ast.Module], dotted: str) -> str:
    """Return the longest product module prefix of a dotted implementation name."""

    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in trees:
            return candidate
    raise AssertionError(f"implementation module is unknown: {dotted}")


def import_closure(trees: dict[str, ast.Module], module: str) -> frozenset[str]:
    """Return product modules statically reachable through ``from`` imports."""

    seen: set[str] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current in seen or current not in trees:
            continue
        seen.add(current)
        for node in ast.walk(trees[current]):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PACKAGE):
                pending.append(node.module)
                pending.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
    return frozenset(seen)


def reachable_extractor_names(
    trees: dict[str, ast.Module], owners: dict[str, frozenset[str]], dotted: str
) -> frozenset[str]:
    """Upper bound of names an implementation can emit via its import closure."""

    closure = import_closure(trees, implementation_module(trees, dotted))
    return frozenset(name for name, modules in owners.items() if modules & closure)


def dispatch_call_names(trees: dict[str, ast.Module] | None = None) -> frozenset[str]:
    """Return every observation-producing call name in the discovery dispatch."""

    source = trees or product_trees()
    function = next(
        node for node in source[DISPATCH_MODULE].body
        if isinstance(node, ast.FunctionDef) and node.name == DISPATCH_FUNCTION
    )
    owners = {"to_observation": "FileInfo", "from_python_paths": "PythonModuleIndex"}
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id.startswith(("extract_", "markdown_")):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in owners:
            names.add(f"{owners[node.func.attr]}.{node.func.attr}")
    return frozenset(names)


def dispatch_import_sources(trees: dict[str, ast.Module] | None = None) -> dict[str, str]:
    """Map each name bound by a ``from`` import in the discovery module to its source."""

    source = trees or product_trees()
    return {
        alias.asname or alias.name: node.module
        for node in source[DISPATCH_MODULE].body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
