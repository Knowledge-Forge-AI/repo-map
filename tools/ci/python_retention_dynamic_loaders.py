"""Closed file-loader specification recipe; binds loader chain and restoration."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ci.python_retention_dynamic_loaders_templates import HELPER_DISPATCH, LOADER_TEMPLATES
from ci.python_retention_operations import dynamic_operations


CASES: dict[str, dict[str, Any]] = {
    "helper_contract_probe": {
        "symbol": "_load_contract_module",
        "runtime_names": ["repomap_helper_contract_Selected", "repomap_helper_contract_Missing"],
        "module_name": "repomap_test_support.contract_loader_fixtures.nested.probe",
        "target_path": "src/test/support/python/repomap_test_support/contract_loader_fixtures/nested/probe.py",
        "target_symbol": "Selected",
        "refusal": False,
    },
    "conftest_refusal": {
        "symbol": "test_direct_integration_conftest_import_refuses_before_fixture_setup",
        "runtime_names": ["conftest"],
        "module_name": "conftest",
        "target_path": "src/test/int/python/conftest.py",
        "target_symbol": "",
        "refusal": True,
    },
    "conftest_inspection": {
        "symbol": "test_unit_inspection_import_of_integration_conftest_does_not_activate_guard",
        "runtime_names": ["repomap_int_conftest_inspection"],
        "module_name": "conftest",
        "target_path": "src/test/int/python/conftest.py",
        "target_symbol": "",
        "refusal": False,
    },
}


def file_loader_spec(
    call: ast.AST,
    tree: ast.Module,
    parameters: dict[str, Any],
    repo_root: Path,
    modules: Mapping[str, str],
) -> set[tuple[str, str]]:
    """Verify complete file loader chain, target provenance, and sys.modules restoration."""
    if parameters.get("schema") != "file-loader-spec-v1":
        raise ValueError("unsupported file loader schema")
    if set(parameters) != {"schema", "case", "target_path", "target_sha256", "runtime_names", "chain"}:
        raise ValueError("unsupported file loader parameters")
    case = parameters.get("case")
    if not isinstance(case, str) or case not in CASES:
        raise ValueError("unsupported file loader case")
    spec = CASES[case]

    target_path = parameters.get("target_path")
    if target_path != spec["target_path"]:
        raise ValueError("loader target path differs from declaration")
    if modules.get(spec["module_name"]) != target_path:
        raise ValueError("loader target module does not map to declared path")

    runtime_names = parameters.get("runtime_names")
    if runtime_names != spec.get("runtime_names"):
        raise ValueError("loader runtime name differs from declaration")

    full = repo_root / target_path
    if not full.resolve().is_relative_to(repo_root.resolve()) or full.is_symlink():
        raise ValueError("loader target path alias or symlink")
    if not full.is_file():
        raise ValueError("loader target path does not exist")
    digest = hashlib.sha256(full.read_bytes()).hexdigest()
    if digest != parameters.get("target_sha256"):
        raise ValueError("loader target source drift")

    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == spec["symbol"]
    ]
    if len(functions) != 1:
        raise ValueError("loader symbol absent or ambiguous")
    function = functions[0]

    if not any(n is call for n in ast.walk(function)):
        raise ValueError("loader operation is outside its owning function")

    # Complete semantic attribute-free AST template comparison
    template_str = LOADER_TEMPLATES.get(case)
    if not template_str:
        raise ValueError(f"no template for loader case {case}")
    expected_node = ast.parse(template_str).body[0]
    if ast.dump(function, include_attributes=False) != ast.dump(expected_node, include_attributes=False):
        raise ValueError(f"file loader AST structure differs from template for {case}")

    ops = dynamic_operations(function)
    kinds = [op["kind"] for op in ops]
    expected_kinds = ["exec_module", "module_from_spec", "spec_from_file_location"]
    if sorted(kinds) != expected_kinds:

        raise ValueError("loader chain incomplete or extra dynamic operations")

    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    if parameters.get("chain") != chain:
        raise ValueError("loader chain declaration differs from actual operations")

    if case == "helper_contract_probe":
        helper = repo_root / "src/test/support/python/repomap_test_support/policy_helper_branches.py"
        helper_tree = ast.parse(helper.read_bytes())
        definitions = [n for n in helper_tree.body if isinstance(n, ast.FunctionDef)
                       and n.name == "load_unit_contract_class"]
        if (len(definitions) != 1 or ast.dump(definitions[0], include_attributes=False)
                != ast.dump(ast.parse(HELPER_DISPATCH).body[0], include_attributes=False)):
            raise ValueError("helper callback dispatch differs from maintained contract")

    return {(spec["module_name"], spec["target_symbol"])}
