"""Source guards: helper API avoidance, stdlib-only guests, native-free host imports (6.2, 16.1)."""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import replace
from importlib import resources
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot.guest_sources import (
    GUEST_FILES,
    helper_closure_sha256,
    load_guest_sources,
)

PACKAGE = "common_lore_index.extractors.rust_pilot"
FORBIDDEN = frozenset({
    "start_point", "end_point", "range", "Point", "Range", "row", "column", "Query", "QueryCursor", "edit",
    "parent", "child_with_descendant", "descendant_for_point_range", "named_descendant_for_point_range",
    "print_dot_graph", "print_dot_graphs", "logger", "included_ranges", "progress_callback", "text", "copy",
    "reset", "eval", "exec", "__import__", "compile",
})
SRC = Path(__file__).resolve().parents[5].parent / "main" / "python"


def _guest(name: str) -> str:
    return resources.files(f"{PACKAGE}.guest").joinpath(name).read_text(encoding="ascii")


def helper_violations(source: str) -> list[str]:
    """The spec 6.2 guard: forbidden names, one bytes parse, one root walk, one import site."""

    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        names = [getattr(node, attr) for attr in ("id", "attr", "arg", "name") if isinstance(getattr(node, attr, None), str)]
        found += [f"forbidden:{name}" for name in names if name in FORBIDDEN]
    calls: list[tuple[ast.Call, ast.Attribute]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.append((node, node.func))
    parses = [call for call, function in calls if function.attr == "parse"]
    if len(parses) != 1 or parses[0].keywords or [ast.dump(arg) for arg in parses[0].args] != [
            ast.dump(ast.Name("data", ast.Load()))]:
        found.append("parse_shape")
    sources = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "data" for t in node.targets)]
    if len(sources) != 1 or not (isinstance(sources[0].value, ast.Call) and isinstance(sources[0].value.func, ast.Name)
                                 and sources[0].value.func.id == "bytes"):
        found.append("parse_argument_not_bytes")
    walks = [(call, function) for call, function in calls if function.attr == "walk"]
    if len(walks) != 1 or not (isinstance(walks[0][1].value, ast.Name)
                               and walks[0][1].value.id == "tree"):
        found.append("walk_shape")
    if len([call for call, function in calls if function.attr == "import_module"]) != 1:
        found.append("dynamic_import_sites")
    return found


def test_parse_helper_passes_the_api_avoidance_guard() -> None:
    assert helper_violations(_guest("parse_helper.py")) == []


@pytest.mark.parametrize(("needle", "replacement", "violation"), [
    ("span(node):\n    return [node.start_byte, node.end_byte]", "span(node):\n    return node.start_point",
     "forbidden:start_point"),
    ("tree = parser.parse(data)", "tree = parser.parse(data)\n    tree = parser.parse(data)", "parse_shape"),
    ("tree = parser.parse(data)", "tree = parser.parse(lambda offset, point: data)", "parse_shape"),
    ("cursor = tree.walk()", "cursor = tree.root_node.walk()", "walk_shape"),
    ("    data = bytes(buffer)", "    data = buffer", "parse_argument_not_bytes"),
    ("if cursor.node.has_error", "if cursor.node.parent", "forbidden:parent"),
])
def test_the_guard_rejects_each_forbidden_shape(needle: str, replacement: str, violation: str) -> None:
    source = _guest("parse_helper.py")
    assert source.count(needle) == 1
    assert violation in helper_violations(source.replace(needle, replacement))


def _imports(tree: ast.AST) -> set[str]:
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    return names | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


@pytest.mark.parametrize("name", GUEST_FILES)
def test_guests_are_standalone_stdlib_without_import_side_effects(name: str) -> None:
    source = _guest(name)
    tree = ast.parse(source, feature_version=(3, 12))
    assert {item.split(".")[0] for item in _imports(tree)} <= set(sys.stdlib_module_names)
    assert source.count('RUNTIME_ROOT = "/opt/repomap-rust"') == 1 and "environ[" not in source
    for statement in tree.body:
        allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef)
        if isinstance(statement, ast.AnnAssign):
            assert not any(isinstance(node, ast.Call) for node in ast.walk(statement))
        elif isinstance(statement, ast.If):
            assert ast.unparse(statement.test) == "__name__ == '__main__'"
        elif isinstance(statement, ast.Expr):
            assert isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
        else:
            assert isinstance(statement, allowed), (name, ast.dump(statement)[:60])


def test_host_modules_never_import_guests_or_the_native_pair() -> None:
    host = resources.files(PACKAGE)
    for entry in host.iterdir():
        if entry.name.endswith(".py"):
            imported = _imports(ast.parse(entry.read_text(encoding="ascii")))
            forbidden = ("tree_sitter", "tree_sitter_rust", f"{PACKAGE}.guest")
            assert not any(item == prefix or item.startswith(prefix + ".")
                           for item in imported for prefix in forbidden), entry.name


def test_core_and_pilot_host_modules_import_with_the_native_pair_blocked() -> None:
    modules = sorted(f"{PACKAGE}.{entry.name[:-3]}" for entry in resources.files(PACKAGE).iterdir()
                     if entry.name.endswith(".py") and entry.name != "__init__.py")
    script = (f"import sys\nsys.path.insert(0, {str(SRC)!r})\n"
              "for name in ('tree_sitter', 'tree_sitter_rust'):\n    sys.modules[name] = None\n"
              "import importlib, common_lore_index\n"
              f"for module in {modules!r}:\n    importlib.import_module(module)\n"
              "assert not any(name.endswith('.guest.parse_helper') for name in sys.modules)\n"
              "print(len([m for m in sys.modules if m.startswith('common_lore_index')]) > 0)\n")
    completed = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=120, check=False)
    assert completed.returncode == 0 and completed.stdout.strip() == b"True"


def test_guest_closure_identity_tracks_every_guest_byte() -> None:
    sources = load_guest_sources()
    digest = helper_closure_sha256(sources, "0" * 64)
    assert digest == helper_closure_sha256(load_guest_sources(), "0" * 64)
    assert digest != helper_closure_sha256(replace(sources, parse_helper=sources.parse_helper + b"\n"), "0" * 64)
    assert digest != helper_closure_sha256(sources, "1" * 64)
    assert all(len(getattr(sources, name[:-3])) < 98_304 for name in GUEST_FILES)
