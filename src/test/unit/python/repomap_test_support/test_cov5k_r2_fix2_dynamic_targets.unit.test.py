"""Unit tests for FIX2 closed dynamic resolver domain (REVISE39, ADR0066)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys

import pytest
import repomap_test_support.test_cov5k_r2_fix2_evidence as evidence_module

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
import repomap_test_support.test_cov5k_r2_fix2_dynamic_targets as dynamic_targets_module
from repomap_test_support.test_cov5k_r2_fix2_dynamic_targets import (
    EXTERNAL_TARGETS,
    PYTHON_TARGETS,
)
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    _module_name,
    _python_identity,
    _resolve_symbol,
)


def test_closed_target_domain_exactly_equals_catalog_enumeration() -> None:
    expected_python: set[tuple[str, str]] = set()
    expected_external: set[str] = set()

    for entry in build_closed_catalog():
        if entry.owner.source_path.startswith("tool:"):
            expected_external.add(entry.owner.source_path)
        else:
            expected_python.add((
                _module_name(entry.owner.source_path),
                entry.owner.registered_runtime_symbol,
            ))
        expected_python.add((
            _module_name(entry.executor_source_path),
            entry.executor_symbol,
        ))

    assert isinstance(PYTHON_TARGETS, tuple)
    assert isinstance(EXTERNAL_TARGETS, tuple)
    assert all(
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], str)
        and isinstance(item[1], str)
        for item in PYTHON_TARGETS
    )
    assert all(isinstance(item, str) for item in EXTERNAL_TARGETS)

    assert PYTHON_TARGETS == tuple(sorted(set(PYTHON_TARGETS)))
    assert EXTERNAL_TARGETS == tuple(sorted(set(EXTERNAL_TARGETS)))

    assert PYTHON_TARGETS == tuple(sorted(expected_python))
    assert EXTERNAL_TARGETS == tuple(sorted(expected_external))

    assert len(PYTHON_TARGETS) == 48
    assert len(EXTERNAL_TARGETS) == 5


def test_external_targets_are_pure_tool_identifiers() -> None:
    assert all(target.startswith("tool:") for target in EXTERNAL_TARGETS)
    assert EXTERNAL_TARGETS == (
        "tool:docker:rm",
        "tool:docker:start",
        "tool:docker:stats",
        "tool:docker:stop",
        "tool:psql",
    )
    python_symbols = {sym for _, sym in PYTHON_TARGETS}
    for target in EXTERNAL_TARGETS:
        assert target not in python_symbols


def test_supported_resolutions_independently_succeed() -> None:
    supported_pure_targets = (
        ("run_tests", "main"),
        ("repomap_kg.cli.dispatch", "dispatch_command"),
        ("repomap_test_support.test_cov5k_r2_fix2_administrative", "execute_backup"),
        ("scale15_actual_path_readback", "read_scale15_terminal_state"),
        ("scale15_actual_path_readback", "read_terminal_backend_summary"),
        ("repomap_test_support.test_cov5k_r2_fix2_gate_executor", "execute_complete_gate"),
        (
            "repomap_test_support.test_cov5k_r2_fix2_process_recorder",
            "execute_zero_process_boundary",
        ),
        (
            "actual_refresh_failure_causality",
            "FailureCausalityAuthority.record_code",
        ),
        ("process_rss_monitor", "ProcessRssMonitor.run"),
    )
    for module_name, symbol in supported_pure_targets:
        resolved = _resolve_symbol(module_name, symbol)
        assert callable(resolved)


def test_runner_identity_refuses_source_drift_during_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tools" / "run_tests.py"
    source.parent.mkdir()
    source.write_text("def main(): return 0\n", encoding="utf-8")
    monkeypatch.setattr(evidence_module, "_repository_root", lambda: tmp_path)

    def resolve_with_drift(module_name: str, symbol: str):
        assert (module_name, symbol) == ("run_tests", "main")
        source.write_text("def main(): return 1\n", encoding="utf-8")
        return resolve_with_drift

    monkeypatch.setattr(evidence_module, "_resolve_symbol", resolve_with_drift)
    with pytest.raises(ExecutorEvidenceError, match="source changed during identity resolution"):
        _python_identity("tools/run_tests.py", "main")


def test_all_domain_targets_pass_guard_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyModule:
        def __getattr__(self, name: str):
            return self

    imported_modules: list[str] = []

    def mock_import(name: str):
        imported_modules.append(name)
        return DummyModule()

    monkeypatch.setattr("importlib.import_module", mock_import)

    for module_name, symbol in PYTHON_TARGETS:
        result = _resolve_symbol(module_name, symbol)
        assert result is not None

    assert len(imported_modules) == len(PYTHON_TARGETS)


def test_undeclared_module_and_symbol_refuses_without_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def poison_import(name: str):
        raise AssertionError(
            f"importlib.import_module must not be called for undeclared target: {name}"
        )

    monkeypatch.setattr("importlib.import_module", poison_import)

    undeclared_cases = (
        ("os", "system"),
        ("sys", "exit"),
        ("builtins", "eval"),
        ("subprocess", "run"),
        ("unregistered_test_module", "some_func"),
        ("repomap_kg.cli.dispatch", "unregistered_symbol"),
        ("run_tests", "unregistered_entrypoint"),
        ("tools.run_tests", "main"),
        ("", ""),
    )
    for module_name, symbol in undeclared_cases:
        with pytest.raises(
            ExecutorEvidenceError,
            match="registered symbol outside closed resolver domain",
        ):
            _resolve_symbol(module_name, symbol)


def test_undeclared_input_never_populates_sys_modules() -> None:
    sentinel_module = "repomap_sentinel_unloaded_module_test"
    assert sentinel_module not in sys.modules

    with pytest.raises(
        ExecutorEvidenceError,
        match="registered symbol outside closed resolver domain",
    ):
        _resolve_symbol(sentinel_module, "arbitrary_function")

    assert sentinel_module not in sys.modules


def test_static_ast_proves_guard_exact_and_precedes_importlib() -> None:
    source = inspect.getsource(_resolve_symbol)
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    assert func.name == "_resolve_symbol"

    guard = func.body[0]
    assert isinstance(guard, ast.If)

    assert isinstance(guard.test, ast.Compare)
    assert isinstance(guard.test.left, ast.Tuple)
    assert len(guard.test.left.elts) == 2
    tuple_names = [elt.id for elt in guard.test.left.elts if isinstance(elt, ast.Name)]
    assert tuple_names == ["module_name", "symbol"]
    assert len(guard.test.ops) == 1
    assert isinstance(guard.test.ops[0], ast.NotIn)
    assert len(guard.test.comparators) == 1
    assert isinstance(guard.test.comparators[0], ast.Name)
    assert guard.test.comparators[0].id == "PYTHON_TARGETS"

    assert len(guard.body) == 1
    raise_node = guard.body[0]
    assert isinstance(raise_node, ast.Raise)
    assert isinstance(raise_node.exc, ast.Call)
    assert isinstance(raise_node.exc.func, ast.Name)
    assert raise_node.exc.func.id == "ExecutorEvidenceError"
    assert len(raise_node.exc.args) == 1
    assert isinstance(raise_node.exc.args[0], ast.Constant)
    assert (
        raise_node.exc.args[0].value
        == "registered symbol outside closed resolver domain"
    )

    import_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
        and node.func.attr == "import_module"
    ]
    assert len(import_calls) == 1
    assert guard.lineno < import_calls[0].lineno


def test_support_module_contains_only_documented_literal_targets() -> None:
    source_path = Path(dynamic_targets_module.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    allowed_targets = {"PYTHON_TARGETS", "EXTERNAL_TARGETS"}
    found_targets: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom):
            assert node.module == "__future__"
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found_targets.add(node.target.id)
            assert isinstance(node.value, ast.Tuple)
            continue
        if isinstance(node, ast.Assign):
            for target_name in node.targets:
                if isinstance(target_name, ast.Name):
                    found_targets.add(target_name.id)
            assert isinstance(node.value, ast.Tuple)
            continue
        pytest.fail(
            f"Unexpected AST node in dynamic targets module: {type(node).__name__}"
        )

    assert found_targets == allowed_targets
    assert dynamic_targets_module.__doc__ is not None
    assert len(dynamic_targets_module.__doc__.strip()) > 0


def test_preserves_independent_re_resolution_and_identities() -> None:
    module_name, qualified, src_digest, code_id = _python_identity(
        "tools/run_tests.py", "main"
    )
    assert module_name == "run_tests"
    assert qualified == "run_tests.main"
    assert len(src_digest) == 64
    assert len(code_id) == 64

    with pytest.raises(
        ExecutorEvidenceError,
        match="registered symbol outside closed resolver domain",
    ):
        _python_identity("tools/run_tests.py", "unregistered_symbol")

    with pytest.raises(
        ExecutorEvidenceError,
        match="registered owner module path is unsupported",
    ):
        _python_identity("unsupported/path.py", "main")
# v0.0.2 dynamic target re-attestation.
