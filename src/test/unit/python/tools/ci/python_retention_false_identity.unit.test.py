"""Focused static tests for the generated false-code-identity recipe."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from ci.python_retention_dynamic_false_identity import (
    GENERATED_SOURCE_SHA256,
    OWNER_SYMBOL,
    PACKAGE_INIT_PATH,
    PACKAGE_MODULE,
    TARGET_MODULE,
    TARGET_PATH,
    generated_false_code_identity,
    _validate_imports,
)
from ci.python_retention_operations import dynamic_operations


_ROOT = Path(__file__).resolve().parents[6]
_OWNER_PATH = "src/test/unit/python/repomap_test_support/test_cov5k_r2_fix4_reproductions.unit.test.py"


def _tree(source: str | None = None) -> ast.Module:
    if source is None:
        source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    return ast.parse(source, filename=_OWNER_PATH)


def _chain(tree: ast.Module) -> list[dict[str, str]]:
    return [
        {
            "kind": operation["kind"],
            "fingerprint": operation["fingerprint"],
        }
        for operation in dynamic_operations(tree)
        if operation["symbol"] == OWNER_SYMBOL
    ]


def _parameters(tree: ast.Module) -> dict[str, object]:
    return {
        "generated_source_sha256": GENERATED_SOURCE_SHA256,
        "chain": _chain(tree),
    }


def _operation(tree: ast.Module, kind: str) -> ast.Call:
    owner = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == OWNER_SYMBOL
    )
    return next(
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == kind
    )


def _resolve(
    tree: ast.Module,
    *,
    kind: str = "exec",
    root: Path = _ROOT,
    modules: dict[str, str] | None = None,
    parameters: dict[str, object] | None = None,
) -> set[tuple[str, str]]:
    return generated_false_code_identity(
        _operation(tree, kind),
        tree,
        _parameters(tree) if parameters is None else parameters,
        root,
        {
            PACKAGE_MODULE: PACKAGE_INIT_PATH,
            TARGET_MODULE: TARGET_PATH,
        } if modules is None else modules,
    )


@pytest.mark.parametrize("kind", ["exec", "compile"])
def test_recipe_resolves_both_operations_without_execution(kind: str) -> None:
    tree = _tree()
    assert _resolve(tree, kind=kind) == {(TARGET_MODULE, "execute_runtime_driver_read")}


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        (
            "def same_module_alternate(*_args, **_kwargs):",
            "def altered_generated_symbol(*_args, **_kwargs):",
            "generated source bytes",
        ),
        ("runtime.__file__", "runtime.__name__", "compile filename"),
        ("dict(runtime.__dict__)", "dict(runtime)", "runtime.__dict__"),
        (
            'namespace["same_module_alternate"]',
            'namespace["execute_runtime_driver_read"]',
            "code object",
        ),
        (
            '    with pytest.raises(TypeError, match="terminal_owner"):\n'
            "        _execute_with_caller_terminal_owner(\n"
            '            _psycopg_entry("success"),\n',
            '    with pytest.raises(TypeError, match="owner"):\n'
            "        _execute_with_caller_terminal_owner(\n"
            '            _psycopg_entry("success"),\n',
            "refusal must match",
        ),
    ],
)
def test_semantic_source_drift_refuses_after_chain_refresh(
    needle: str, replacement: str, message: str
) -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    assert needle in source
    tree = _tree(source.replace(needle, replacement, 1))
    with pytest.raises(ValueError, match=message):
        _resolve(tree)


def test_altered_generated_bytes_cannot_refresh_closed_source_commitment() -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    altered = source.replace(
        "def same_module_alternate(*_args, **_kwargs):",
        "def altered_generated_symbol(*_args, **_kwargs):",
        1,
    )
    tree = _tree(altered)
    parameters = _parameters(tree)
    parameters["generated_source_sha256"] = hashlib.sha256(
        b"def altered_generated_symbol(*_args, **_kwargs):\n"
        b"    class State: value = 'success'\n"
        b"    class Readback: publication_state = State()\n"
        b"    return Readback()\n"
    ).hexdigest()
    with pytest.raises(ValueError, match="source commitment"):
        _resolve(tree, parameters=parameters)


def test_real_target_symbol_claim_is_refused(tmp_path: Path) -> None:
    target = tmp_path / TARGET_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((_ROOT / TARGET_PATH).read_bytes() + b"\nsame_module_alternate = object()\n")
    package = tmp_path / PACKAGE_INIT_PATH
    package.write_text('"""temporary package"""\n', encoding="utf-8")
    with pytest.raises(ValueError, match="real target owner"):
        _resolve(
            _tree(),
            root=tmp_path,
            modules={PACKAGE_MODULE: PACKAGE_INIT_PATH, TARGET_MODULE: TARGET_PATH},
        )


def test_rebound_runtime_import_is_refused() -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    marker = "from repomap_test_support.test_cov5k_r2_fix4_terminal_contexts import ("
    tree = _tree(source.replace(marker, "runtime = object()\n\n" + marker, 1))
    with pytest.raises(ValueError, match="runtime import"):
        _resolve(tree)


def test_helper_relationship_is_refused_when_runtime_owner_changes() -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    needle = "return execute_runtime_driver_read("
    assert needle in source
    tree = _tree(source.replace(needle, "return execute_terminal_read(", 1))
    with pytest.raises(ValueError, match="execute_runtime_driver_read"):
        _resolve(tree)


def test_extra_compile_operation_is_refused_after_chain_refresh() -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    marker = (
        '    with pytest.raises(TypeError, match="terminal_owner"):\n'
        "        _execute_with_caller_terminal_owner(\n"
        '            _psycopg_entry("success"),\n'
    )
    tree = _tree(source.replace(marker, '    compile("extra", runtime.__file__, "exec")\n' + marker, 1))
    with pytest.raises(ValueError, match="chain"):
        _resolve(tree)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda chain: chain[:1],
        lambda chain: [chain[0], chain[0]],
        lambda chain: [chain[0], {**chain[1], "fingerprint": "0" * 64}],
    ],
)
def test_partial_duplicate_and_stale_chain_declarations_refuse(mutator) -> None:
    tree = _tree()
    parameters = _parameters(tree)
    parameters["chain"] = mutator(parameters["chain"])
    with pytest.raises(ValueError, match="chain"):
        _resolve(tree, parameters=parameters)


def test_target_path_alias_is_refused(tmp_path: Path) -> None:
    target = tmp_path / TARGET_PATH
    target.parent.mkdir(parents=True)
    target.symlink_to(_ROOT / TARGET_PATH)
    package = tmp_path / PACKAGE_INIT_PATH
    package.write_text('"""temporary package"""\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing or aliased"):
        _resolve(
            _tree(),
            root=tmp_path,
            modules={PACKAGE_MODULE: PACKAGE_INIT_PATH, TARGET_MODULE: TARGET_PATH},
        )


def test_missing_target_is_refused() -> None:
    with pytest.raises(ValueError, match="missing or aliased"):
        _resolve(_tree(), modules={PACKAGE_MODULE: PACKAGE_INIT_PATH})


@pytest.mark.parametrize("mutation", [
    "from foreign import exec", "runtime.__file__ = 'foreign.py'",
    "runtime.__dict__.clear()", "pytest.raises = object()",
])
def test_module_mutations_fail_with_refreshed_chain(mutation: str) -> None:
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    tree = _tree(source + "\n" + mutation + "\n")
    with pytest.raises(ValueError):
        _resolve(tree)


def test_entry_helper_cannot_fake_the_owner_refusal() -> None:
    tree = _tree()
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_psycopg_entry")
    helper.body = ast.parse("raise TypeError('terminal_owner')").body
    with pytest.raises(ValueError, match="helper relationship"):
        _resolve(tree)


@pytest.mark.parametrize("name", ["dict", "compile", "exec", "TypeError"])
@pytest.mark.parametrize("construction", [
    "def {name}(): pass\n{name} = object()",
    "from foreign import {name}\n{name} = object()",
    "def helper({name}):\n    {name} = object()",
])
def test_ambiguous_builtin_bindings_fail_closed(name: str, construction: str) -> None:
    # Test the binding boundary directly: later template checks must not hide it.
    source = (_ROOT / _OWNER_PATH).read_text(encoding="utf-8")
    tree = _tree(source + "\n" + construction.format(name=name) + "\n")
    with pytest.raises(ValueError, match="builtin binding"):
        _validate_imports(tree)
    with pytest.raises(ValueError, match="builtin binding"):
        _resolve(tree)
