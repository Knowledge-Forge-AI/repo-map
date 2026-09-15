"""Unit tests for optional import substitution recipe and negative controls."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from ci.python_retention_dynamic_substitution import (
    CASES,
    _derive_blocked_domain,
    optional_import_substitution,
)
from ci.python_retention_operations import dynamic_operations

_REPO_ROOT = Path(__file__).resolve().parents[6]
_DEP_BOUNDARY_PATH = "src/test/unit/python/tools/scale28_r1_dependency_boundary.unit.test.py"
_PSUTIL_READERS_PATH = "src/test/unit/python/tools/scale28_r1_psutil_readers.unit.test.py"


def _dep_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _DEP_BOUNDARY_PATH).read_text(encoding="utf-8"))


def _psutil_tree() -> ast.Module:
    return ast.parse((_REPO_ROOT / _PSUTIL_READERS_PATH).read_text(encoding="utf-8"))


def _base_package_params(tree: ast.Module) -> tuple[ast.AST, dict[str, object], dict[str, str]]:
    spec = CASES["base_package_import"]
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == spec["symbol"])
    ops = dynamic_operations(fn)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module")
    target_path = "src/main/python/repomap_kg/__init__.py"
    target_sha = hashlib.sha256((_REPO_ROOT / target_path).read_bytes()).hexdigest()
    domain = _derive_blocked_domain(_REPO_ROOT)
    params = {
        "schema": "optional-import-substitution-v1",
        "case": "base_package_import",
        "blocked_domain": domain,
        "target_module": "repomap_kg",
        "target_path": target_path,
        "target_sha256": target_sha,
        "alternate_names": spec["alternate_names"],
        "chain": chain,
    }
    modules = {"repomap_kg": target_path}
    return call, params, modules


def _sampling_params(tree: ast.Module, case: str) -> tuple[ast.AST, dict[str, object], dict[str, str]]:
    spec = CASES[case]
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == spec["symbol"])
    ops = dynamic_operations(fn)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module")
    target_path = "tools/scale12_resource_sampling.py"
    target_sha = hashlib.sha256((_REPO_ROOT / target_path).read_bytes()).hexdigest()
    domain = _derive_blocked_domain(_REPO_ROOT)
    params = {
        "schema": "optional-import-substitution-v1",
        "case": case,
        "blocked_domain": domain,
        "target_module": spec["target_module"],
        "target_path": target_path,
        "target_sha256": target_sha,
        "alternate_names": spec["alternate_names"],
        "chain": chain,
    }
    modules = {spec["target_module"]: target_path}
    return call, params, modules


def test_base_package_import_resolves_cleanly() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    resolved = optional_import_substitution(call, tree, params, _REPO_ROOT, modules)
    assert resolved == {("repomap_kg", "")}


@pytest.mark.parametrize("case", ["sampling_missing_psutil", "sampling_missing_docker"])
def test_sampling_missing_dependency_cases_resolve_cleanly(case: str) -> None:
    tree = _psutil_tree()
    call, params, modules = _sampling_params(tree, case)
    resolved = optional_import_substitution(call, tree, params, _REPO_ROOT, modules)
    assert resolved == {("scale12_resource_sampling", "")}


def test_substitution_derives_domain_from_pyproject() -> None:
    domain = _derive_blocked_domain(_REPO_ROOT)
    assert domain == ["docker", "psutil"]


def test_substitution_rejects_unsupported_schema() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["schema"] = "wrong-schema"
    with pytest.raises(ValueError, match="unsupported substitution schema"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_unsupported_case() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["case"] = "nonexistent_case"
    with pytest.raises(ValueError, match="unsupported substitution case"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


@pytest.mark.parametrize("bad_domain", [
    ["psutil"],
    ["docker", "psutil", "requests"],
    ["extra_pkg"],
    [],
])
def test_substitution_rejects_blocked_domain_drift(bad_domain: list[str]) -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["blocked_domain"] = bad_domain
    with pytest.raises(ValueError, match="substitution blocked domain must equal pyproject"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_target_module_mismatch() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["target_module"] = "other_mod"
    with pytest.raises(ValueError, match="substitution target module differs"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_alternate_names_mismatch() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["alternate_names"] = "_other_name"
    with pytest.raises(ValueError, match="substitution alternate name differs"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_unresolved_target_module() -> None:
    tree = _dep_tree()
    call, params, _ = _base_package_params(tree)
    with pytest.raises(ValueError, match="not found in modules map"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, {})


def test_substitution_rejects_target_path_mismatch_with_modules() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["target_path"] = "differing/path.py"
    with pytest.raises(ValueError, match="does not match modules resolution"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_target_source_drift() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["target_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="substitution target source drift"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_missing_target_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes((_REPO_ROOT / "pyproject.toml").read_bytes())
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    with pytest.raises(ValueError, match="substitution target path does not exist"):
        optional_import_substitution(call, tree, params, tmp_path, modules)


def test_substitution_rejects_symlink_target_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes((_REPO_ROOT / "pyproject.toml").read_bytes())
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    target_rel = str(params["target_path"])
    full_target = tmp_path / target_rel
    full_target.parent.mkdir(parents=True, exist_ok=True)
    real_file = tmp_path / "real_init.py"
    real_file.write_bytes((_REPO_ROOT / target_rel).read_bytes())
    full_target.symlink_to(real_file)
    with pytest.raises(ValueError, match="substitution target path alias or symlink"):
        optional_import_substitution(call, tree, params, tmp_path, modules)



def test_substitution_rejects_operation_outside_owning_function() -> None:
    tree = _dep_tree()
    _, params, modules = _base_package_params(tree)
    outside_call = ast.parse("exec_module(mod)").body[0]
    assert isinstance(outside_call, ast.Expr)
    with pytest.raises(ValueError, match="substitution operation is outside"):
        optional_import_substitution(outside_call.value, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_altered_ast_structure() -> None:
    source = (_REPO_ROOT / _DEP_BOUNDARY_PATH).read_text(encoding="utf-8")
    mutated = source.replace("monkeypatch.context()", "unrestored_hook()")
    assert mutated != source
    tree = ast.parse(mutated)
    call, params, modules = _base_package_params(tree)
    with pytest.raises(ValueError, match="substitution AST structure differs"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)


def test_substitution_rejects_chain_mismatch() -> None:
    tree = _dep_tree()
    call, params, modules = _base_package_params(tree)
    params["chain"] = []
    with pytest.raises(ValueError, match="substitution chain declaration differs"):
        optional_import_substitution(call, tree, params, _REPO_ROOT, modules)
