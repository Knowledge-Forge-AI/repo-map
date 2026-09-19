from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[5]
WORKFLOW = ROOT / ".github/workflows/repomap-release-qualification.yml"
SANDBOX = ROOT / "tools/test_sandbox.py"
CONTAINER_PAIR_TEST = (
    ROOT
    / "src/test/int/python/repomap_test_support/"
    "test_cov5k_r2_fix3_container_pairs.int.test.py"
)


def _declared_image_prerequisites() -> frozenset[str]:
    tree = ast.parse(CONTAINER_PAIR_TEST.read_text(encoding="utf-8"))
    return frozenset(
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "images"
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    )


def _string_constants(tree: ast.Module) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _delegated_images(tree: ast.Module) -> ast.Tuple:
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_prepare_inner_images"
    ]
    assert len(functions) == 1, "expected one image preparation facade"
    calls = [
        node for node in ast.walk(functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_inner"
        and node.func.attr == "prepare_inner_images"
    ]
    assert len(calls) == 1, "expected one inner image delegation"
    arguments = [kw.value for kw in calls[0].keywords if kw.arg == "images"]
    assert len(arguments) == 1, "expected an explicit images argument"
    argument = arguments[0]
    assert isinstance(argument, ast.Tuple), "images argument must be a tuple"
    return argument


def _sandbox_image_prerequisites(tree: ast.Module) -> frozenset[str]:
    constants = _string_constants(tree)
    contract = _string_constants(ast.parse(
        (SANDBOX.parent / "test_sandbox_contract.py").read_text(encoding="utf-8")
    ))
    for node in tree.body:
        if (isinstance(node, ast.ImportFrom) and node.level == 0
                and node.module == "test_sandbox_contract"):
            for alias in node.names:
                if alias.name in contract:
                    constants[alias.asname or alias.name] = contract[alias.name]
    prerequisites: list[str] = []
    for item in _delegated_images(tree).elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            prerequisites.append(item.value)
        elif isinstance(item, ast.Name):
            assert item.id in constants, f"unresolved image constant: {item.id}"
            prerequisites.append(constants[item.id])
        else:
            raise AssertionError("unresolved image expression")
    return frozenset(prerequisites)


def _assert_image_contract(tree: ast.Module) -> None:
    required = _declared_image_prerequisites()
    assert required, "container-pair owner must declare image prerequisites"
    assert required <= _sandbox_image_prerequisites(tree), "missing required image"


def test_hosted_gate_routes_container_pair_images_to_sandbox_inner_daemon() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    staging_offset = workflow.index("--suite staging")
    staging_command = workflow[staging_offset : workflow.index("ci-staging-report")]

    assert "--sandbox" in staging_command
    assert re.search(r"\bdocker\s+pull\b", workflow) is None
    _assert_image_contract(ast.parse(SANDBOX.read_text(encoding="utf-8")))


def test_delegated_images_contract_rejects_missing_required_image() -> None:
    tree = ast.parse(SANDBOX.read_text(encoding="utf-8"))
    _assert_image_contract(tree)
    images = _delegated_images(tree)
    original = list(images.elts)
    required = _declared_image_prerequisites()
    for index, item in enumerate(original):
        assert isinstance(item, ast.Name)
        images.elts = [item]
        if _sandbox_image_prerequisites(tree) & required:
            break
    else:
        raise AssertionError("no required delegated image found")
    images.elts = [item for offset, item in enumerate(original) if offset != index]
    with pytest.raises(AssertionError, match="missing required image"):
        _assert_image_contract(tree)


def test_container_pair_path_only_gets_preprovisioned_images() -> None:
    source = CONTAINER_PAIR_TEST.read_text(encoding="utf-8")

    assert ".images.pull(" not in source
    assert "docker pull" not in source
    assert "ImageNotFound" not in source
    assert "pytest.skip" not in source
    assert "pytest.xfail" not in source
