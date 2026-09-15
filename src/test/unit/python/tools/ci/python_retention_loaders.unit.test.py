"""Unit tests for the file loader specification recipe and negative controls."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from ci.python_retention_dynamic_loaders import file_loader_spec, CASES
from ci.python_retention_operations import dynamic_operations

_REPO_ROOT = Path(__file__).resolve().parents[6]
_HELPER_BRANCHES_PATH = "src/test/unit/python/repomap_kg/ingestion_api_bulk/helper_branches.unit.test.py"
_ISO1_RUNNER_PATH = "src/test/unit/python/tools/test_iso1_runner.unit.test.py"


def _helper_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _HELPER_BRANCHES_PATH).read_text(encoding="utf-8"))


def _runner_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _ISO1_RUNNER_PATH).read_text(encoding="utf-8"))


def _probe_params(tree: ast.Module) -> tuple[ast.AST, dict[str, object], dict[str, str]]:
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_contract_module")
    ops = dynamic_operations(fn)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module")
    target_path = CASES["helper_contract_probe"]["target_path"]
    target_sha = hashlib.sha256((_REPO_ROOT / target_path).read_bytes()).hexdigest()
    params = {
        "schema": "file-loader-spec-v1",
        "case": "helper_contract_probe",
        "runtime_names": ["repomap_helper_contract_Selected", "repomap_helper_contract_Missing"],
        "target_path": target_path,
        "target_sha256": target_sha,
        "chain": chain,
    }
    modules = {CASES["helper_contract_probe"]["module_name"]: target_path}
    return call, params, modules


def _runner_params(tree: ast.Module, case: str) -> tuple[ast.AST, dict[str, object], dict[str, str]]:
    spec = CASES[case]
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == spec["symbol"])
    ops = dynamic_operations(fn)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module")
    target_path = spec["target_path"]
    target_sha = hashlib.sha256((_REPO_ROOT / target_path).read_bytes()).hexdigest()
    params = {
        "schema": "file-loader-spec-v1",
        "case": case,
        "runtime_names": spec["runtime_names"],
        "target_path": target_path,
        "target_sha256": target_sha,
        "chain": chain,
    }
    modules = {spec["module_name"]: target_path}
    return call, params, modules


def test_helper_contract_probe_resolves_cleanly() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    resolved = file_loader_spec(call, tree, params, _REPO_ROOT, modules)
    assert resolved == {("repomap_test_support.contract_loader_fixtures.nested.probe", "Selected")}


@pytest.mark.parametrize("case", ["conftest_refusal", "conftest_inspection"])
def test_conftest_loader_cases_resolve_cleanly(case: str) -> None:
    tree = _runner_tree()
    call, params, modules = _runner_params(tree, case)
    resolved = file_loader_spec(call, tree, params, _REPO_ROOT, modules)
    assert resolved == {("conftest", "")}


def test_loader_rejects_unsupported_schema() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    params["schema"] = "invalid-schema-v0"
    with pytest.raises(ValueError, match="unsupported file loader schema"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_unsupported_case() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    params["case"] = "nonexistent_case"
    with pytest.raises(ValueError, match="unsupported file loader case"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_target_path_mismatch() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    params["target_path"] = "src/test/other/path.py"
    with pytest.raises(ValueError, match="loader target path differs"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_module_mapping_mismatch() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    modules.update({CASES["helper_contract_probe"]["module_name"]: "src/test/differing.py"})
    with pytest.raises(ValueError, match="loader target module does not map"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_runtime_names_mismatch() -> None:
    tree = _runner_tree()
    call, params, modules = _runner_params(tree, "conftest_inspection")
    params["runtime_names"] = "wrong_runtime_names"
    with pytest.raises(ValueError, match="loader runtime name differs"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_target_source_drift() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    params["target_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="loader target source drift"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_missing_target_file(tmp_path: Path) -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    with pytest.raises(ValueError, match="loader target path does not exist"):
        file_loader_spec(call, tree, params, tmp_path, modules)


def test_loader_rejects_symlink_target_file(tmp_path: Path) -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    target_rel = str(params["target_path"])
    full_target = tmp_path / target_rel
    full_target.parent.mkdir(parents=True, exist_ok=True)
    real_file = tmp_path / "real_file.py"
    real_file.write_bytes((_REPO_ROOT / target_rel).read_bytes())
    full_target.symlink_to(real_file)
    with pytest.raises(ValueError, match="loader target path alias or symlink"):
        file_loader_spec(call, tree, params, tmp_path, modules)


def test_loader_rejects_operation_outside_owning_function() -> None:
    tree = _helper_tree()
    _, params, modules = _probe_params(tree)
    outside_call = ast.parse("exec_module(mod)").body[0]
    assert isinstance(outside_call, ast.Expr)
    with pytest.raises(ValueError, match="loader operation is outside"):
        file_loader_spec(outside_call.value, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_altered_ast_structure() -> None:
    # Mutate the source by omitting finally cleanup
    source = (_REPO_ROOT / _HELPER_BRANCHES_PATH).read_text(encoding="utf-8")
    mutated = source.replace("spec.loader.exec_module(module)", "pass")
    tree = ast.parse(mutated)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_contract_module")
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call))
    target_path = CASES["helper_contract_probe"]["target_path"]
    target_sha = hashlib.sha256((_REPO_ROOT / target_path).read_bytes()).hexdigest()
    params = {
        "schema": "file-loader-spec-v1",
        "case": "helper_contract_probe",
        "runtime_names": ["repomap_helper_contract_Selected", "repomap_helper_contract_Missing"],
        "target_path": target_path,
        "target_sha256": target_sha,
        "chain": [],
    }
    modules = {CASES["helper_contract_probe"]["module_name"]: target_path}
    with pytest.raises(ValueError, match="file loader AST structure differs"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_swapped_runtime_namess_in_ast() -> None:
    # Mutate test_iso1_runner to swap "conftest" into conftest_inspection
    source = (_REPO_ROOT / _ISO1_RUNNER_PATH).read_text(encoding="utf-8")
    mutated = source.replace("'repomap_int_conftest_inspection'", "'conftest'")
    assert mutated != source
    tree = ast.parse(mutated)
    call, params, modules = _runner_params(tree, "conftest_inspection")
    with pytest.raises(ValueError, match="file loader AST structure differs"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)


def test_loader_rejects_chain_mismatch() -> None:
    tree = _helper_tree()
    call, params, modules = _probe_params(tree)
    params["chain"] = []
    with pytest.raises(ValueError, match="loader chain declaration differs"):
        file_loader_spec(call, tree, params, _REPO_ROOT, modules)
