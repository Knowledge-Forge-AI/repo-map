"""Closed optional-import substitution recipe; binds domain, hooks, and restoration."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import tomllib
from typing import Any, Mapping

from ci.python_retention_dynamic_substitution_templates import SUBSTITUTION_TEMPLATES
from ci.python_retention_operations import dynamic_operations


CASES: dict[str, dict[str, Any]] = {
    "base_package_import": {
        "symbol": "test_base_package_import_does_not_require_scale_tools",
        "target_module": "repomap_kg",
        "alternate_names": ["_repomap_without_scale_tools"],
        "outcome": "import_succeeds",
    },
    "sampling_missing_psutil": {
        "symbol": "test_sampling_module_fails_fast_when_scale_dependency_is_missing",
        "target_module": "scale12_resource_sampling",
        "alternate_names": ["_scale28_missing_psutil", "_scale28_missing_docker"],
        "outcome": "runtime_error_scale_tools",
    },
    "sampling_missing_docker": {
        "symbol": "test_sampling_module_fails_fast_when_scale_dependency_is_missing",
        "target_module": "scale12_resource_sampling",
        "alternate_names": ["_scale28_missing_psutil", "_scale28_missing_docker"],
        "outcome": "runtime_error_scale_tools",
    },
}


def _derive_blocked_domain(repo_root: Path) -> list[str]:
    """Independently derive scale-tools domain from pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError("pyproject.toml not found for dependency derivation")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scale_deps = data["project"]["optional-dependencies"]["scale-tools"]
    names = {dep.split("==")[0].split(">=")[0].split("[")[0].strip() for dep in scale_deps}
    return sorted(names)


def optional_import_substitution(
    call: ast.AST,
    tree: ast.Module,
    parameters: dict[str, Any],
    repo_root: Path,
    modules: Mapping[str, str],
) -> set[tuple[str, str]]:
    """Verify closed optional dependency substitution domain, hook forwarding, and restoration."""
    if parameters.get("schema") != "optional-import-substitution-v1":
        raise ValueError("unsupported substitution schema")
    if set(parameters) != {"schema", "case", "blocked_domain", "target_module", "target_path",
                           "target_sha256", "alternate_names", "chain"}:
        raise ValueError("unsupported substitution parameters")
    case = parameters.get("case")
    if not isinstance(case, str) or case not in CASES:
        raise ValueError("unsupported substitution case")
    spec = CASES[case]

    expected_domain = _derive_blocked_domain(repo_root)
    if sorted(parameters.get("blocked_domain", [])) != expected_domain:
        raise ValueError(f"substitution blocked domain must equal pyproject scale-tools pins {expected_domain}")

    target_module = spec["target_module"]
    if parameters.get("target_module") != target_module:
        raise ValueError("substitution target module differs from declaration")
    if parameters.get("alternate_names") != spec["alternate_names"]:
        raise ValueError("substitution alternate name differs from declaration")

    # Canonical source resolution using modules.get(target_module) without assuming paths
    target_path = modules.get(target_module)
    if target_path is None:
        raise ValueError(f"substitution target module {target_module} not found in modules map")
    if parameters.get("target_path") != target_path:
        raise ValueError("substitution target path does not match modules resolution")

    full = repo_root / target_path
    if not full.resolve().is_relative_to(repo_root.resolve()) or full.is_symlink():
        raise ValueError("substitution target path alias or symlink")
    if not full.is_file():
        raise ValueError("substitution target path does not exist")
    digest = hashlib.sha256(full.read_bytes()).hexdigest()
    if digest != parameters.get("target_sha256"):
        raise ValueError("substitution target source drift")

    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == spec["symbol"]
    ]
    if len(functions) != 1:
        raise ValueError("substitution symbol absent or ambiguous")
    function = functions[0]

    if not any(n is call for n in ast.walk(function)):
        raise ValueError("substitution operation is outside its owning function")

    # Complete semantic attribute-free AST template comparison
    template_str = SUBSTITUTION_TEMPLATES.get(case)
    if not template_str:
        raise ValueError(f"no template for substitution case {case}")
    expected_node = ast.parse(template_str).body[0]
    if ast.dump(function, include_attributes=False) != ast.dump(expected_node, include_attributes=False):
        raise ValueError(f"substitution AST structure differs from template for {case}")

    ops = dynamic_operations(function)
    kinds = [op["kind"] for op in ops]
    expected_kinds = ["exec_module", "module_from_spec", "modules", "spec_from_file_location"]
    if sorted(kinds) != expected_kinds:
        raise ValueError("substitution chain incomplete or extra dynamic operations")

    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    if parameters.get("chain") != chain:
        raise ValueError("substitution chain declaration differs from actual operations")

    return {(target_module, "")}
