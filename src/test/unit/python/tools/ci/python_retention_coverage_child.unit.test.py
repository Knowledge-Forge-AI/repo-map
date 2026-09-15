"""Unit tests for child coverage fixture recipe and negative controls."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ci.python_retention_dynamic_coverage import (
    CHILD_CASES,
    coverage_fixture,
)
from ci.python_retention_operations import dynamic_operations

_REPO_ROOT = Path(__file__).resolve().parents[6]
_CHILD_TEST_PATH = "src/test/unit/python/tools/test_runner_coverage_child.unit.test.py"
_EXPORT_TEST_PATH = "src/test/unit/python/tools/test_runner_coverage_child_export.unit.test.py"


def _child_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _CHILD_TEST_PATH).read_text(encoding="utf-8"))


def _export_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _EXPORT_TEST_PATH).read_text(encoding="utf-8"))


def _caller_params(tree: ast.Module) -> tuple[ast.AST, dict[str, object]]:
    spec = CHILD_CASES["caller_mod"]
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == spec["class_name"])
    method = next(n for n in cls_node.body if isinstance(n, ast.FunctionDef) and n.name == spec["method_name"])
    ops = dynamic_operations(method)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "import_module")
    params = {
        "schema": "literal-coverage-fixture-v1",
        "case": "caller_mod",
        "filename": spec["filename"],
        "source_utf8": spec["source_utf8"],
        "symbol": spec["symbol"],
        "chain": chain,
    }
    return call, params


def _decision_params(tree: ast.Module) -> tuple[ast.AST, dict[str, object]]:
    spec = CHILD_CASES["decision_mod"]
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == spec["class_name"])
    method = next(n for n in cls_node.body if isinstance(n, ast.FunctionDef) and n.name == spec["method_name"])
    ops = dynamic_operations(method)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "import_module")
    params = {
        "schema": "literal-coverage-fixture-v1",
        "case": "decision_mod",
        "filename": spec["filename"],
        "source_utf8": spec["source_utf8"],
        "symbol": spec["symbol"],
        "chain": chain,
    }
    return call, params


def test_caller_mod_fixture_resolves_cleanly() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    resolved = coverage_fixture(call, tree, params)
    assert resolved == {("runner_coverage", ""), ("run_tests", "")}


def test_decision_mod_fixture_resolves_cleanly() -> None:
    tree = _export_tree()
    call, params = _decision_params(tree)
    resolved = coverage_fixture(call, tree, params)
    assert resolved == {("runner_coverage", "")}


def test_child_coverage_rejects_unsupported_schema() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    params["schema"] = "invalid-coverage-schema-v0"
    with pytest.raises(ValueError, match="coverage fixture schema mismatch"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_filename_mismatch() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    params["filename"] = "wrong_mod.py"
    with pytest.raises(ValueError, match="child coverage filename differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_source_utf8_mismatch() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    params["source_utf8"] = "def modified(): pass\n"
    with pytest.raises(ValueError, match="child coverage literal source differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_symbol_mismatch() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    params["symbol"] = "wrong.symbol.name"
    with pytest.raises(ValueError, match="child coverage symbol differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_operation_outside_method() -> None:
    tree = _child_tree()
    _, params = _caller_params(tree)
    outside_call = ast.parse("import_module('caller_mod')").body[0]
    assert isinstance(outside_call, ast.Expr)
    with pytest.raises(ValueError, match="coverage operation is outside its fixture"):
        coverage_fixture(outside_call.value, tree, params)


def test_child_coverage_rejects_chain_mismatch() -> None:
    tree = _child_tree()
    call, params = _caller_params(tree)
    params["chain"] = []
    with pytest.raises(ValueError, match="child coverage chain differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_altered_ast_decision_mod() -> None:
    source = (_REPO_ROOT / _EXPORT_TEST_PATH).read_text(encoding="utf-8")
    mutated = source.replace("session.combine(child_runner)", "pass")
    tree = ast.parse(mutated)
    call, params = _decision_params(tree)
    with pytest.raises(ValueError, match="child coverage method AST differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_altered_branch_arc_assertions() -> None:
    source = (_REPO_ROOT / _EXPORT_TEST_PATH).read_text(encoding="utf-8")
    mutated = source.replace("self.assertNotIn((2, 4), arcs)", "pass")
    tree = ast.parse(mutated)
    call, params = _decision_params(tree)
    with pytest.raises(ValueError, match="child coverage method AST differs"):
        coverage_fixture(call, tree, params)


@pytest.mark.parametrize("statement", ["self.addCleanup(session.cleanup)",
                                       "session.cleanup()",
                                       "self.assertIs(coverage.Coverage.current(), parent_cov)"])
def test_decision_fixture_requires_explicit_settlement_and_outer_identity(statement: str) -> None:
    source = (_REPO_ROOT / _EXPORT_TEST_PATH).read_text(encoding="utf-8")
    assert statement in source
    tree = ast.parse(source.replace(statement, "pass"))
    call, params = _decision_params(tree)
    with pytest.raises(ValueError, match="child coverage method AST differs"):
        coverage_fixture(call, tree, params)


def test_child_coverage_rejects_missing_sys_modules_cleanup() -> None:
    source = (_REPO_ROOT / _EXPORT_TEST_PATH).read_text(encoding="utf-8")
    mutated = source.replace('sys.modules.pop("decision_mod", None)', "pass")
    tree = ast.parse(mutated)
    call, params = _decision_params(tree)
    with pytest.raises(ValueError, match="child coverage sys.modules cleanup missing"):
        coverage_fixture(call, tree, params)


@pytest.mark.parametrize("case", ["caller_mod", "decision_mod"])
def test_child_coverage_rejects_unknown_declaration_keys(case: str) -> None:
    tree = _child_tree() if case == "caller_mod" else _export_tree()
    call, params = _caller_params(tree) if case == "caller_mod" else _decision_params(tree)
    params["unrecognized_authority"] = True
    with pytest.raises(ValueError, match="unsupported child coverage parameters"):
        coverage_fixture(call, tree, params)
