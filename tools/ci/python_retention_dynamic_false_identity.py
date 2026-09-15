"""Closed static recipe for the generated false-code-identity reproduction."""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ci.python_retention_operations import dynamic_operations
from ci.python_retention_dynamic_false_templates import HELPERS, INITIALIZATION


TARGET_MODULE = "repomap_test_support.test_cov5k_r2_fix2_runtime"
TARGET_PATH = "src/test/support/python/repomap_test_support/test_cov5k_r2_fix2_runtime.py"
PACKAGE_MODULE = "repomap_test_support"
PACKAGE_INIT_PATH = "src/test/support/python/repomap_test_support/__init__.py"
TARGET_SYMBOL = "execute_runtime_driver_read"
OWNER_SYMBOL = "test_fix4_rejects_same_module_alternate_owner_with_right_shape"
GENERATED_SYMBOL = "same_module_alternate"

_GENERATED_SOURCE = (
    "def same_module_alternate(*_args, **_kwargs):\n"
    "    class State: value = 'success'\n"
    "    class Readback: publication_state = State()\n"
    "    return Readback()\n"
)
GENERATED_SOURCE_SHA256 = hashlib.sha256(_GENERATED_SOURCE.encode("utf-8")).hexdigest()
_PARAMETER_KEYS = frozenset({"chain", "generated_source_sha256"})
_CHAIN_KEYS = frozenset({"kind", "fingerprint"})


def _name(node: ast.AST, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _constant(node: ast.AST, expected: object) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(functions) != 1:
        raise ValueError(f"generated false-identity owner function {name!r} is not unique")
    return functions[0]


def _fingerprint(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def _owner_chain(tree: ast.AST) -> list[dict[str, str]]:
    operations = [
        operation
        for operation in dynamic_operations(tree)
        if operation["symbol"] == OWNER_SYMBOL
    ]
    expected_kinds = ["exec", "compile"]
    if [operation["kind"] for operation in operations] != expected_kinds:
        raise ValueError("false-identity owner must contain exactly one exec/compile chain")
    return [
        {
            "kind": operation["kind"],
            "fingerprint": operation["fingerprint"],
        }
        for operation in operations
    ]


def _validate_chain(
    operation: ast.Call,
    tree: ast.AST,
    parameters: Mapping[str, Any],
) -> None:
    if set(parameters) != _PARAMETER_KEYS:
        raise ValueError("generated false-identity parameters are not closed")
    if parameters["generated_source_sha256"] != GENERATED_SOURCE_SHA256:
        raise ValueError("generated false-identity source commitment differs")
    chain = parameters["chain"]
    if not isinstance(chain, list) or len(chain) != 2:
        raise ValueError("generated false-identity chain must contain two operations")
    if any(not isinstance(item, dict) or set(item) != _CHAIN_KEYS for item in chain):
        raise ValueError("generated false-identity chain descriptors are incomplete")
    if any(
        not isinstance(item["kind"], str)
        or not isinstance(item["fingerprint"], str)
        or len(item["fingerprint"]) != 64
        for item in chain
    ):
        raise ValueError("generated false-identity chain descriptor is malformed")

    expected = _owner_chain(tree)
    if chain != expected:
        raise ValueError("generated false-identity chain differs from source operations")
    owner = _function(tree, OWNER_SYMBOL)
    if sum(node is operation for node in ast.walk(owner)) != 1:
        raise ValueError("declared false-identity operation is outside its owning test")
    if _fingerprint(operation) not in {
        descriptor["fingerprint"] for descriptor in expected
    }:
        raise ValueError("declared false-identity operation is not in the complete chain")


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                bindings.setdefault(local, set()).add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                bindings.setdefault(local, set()).add(alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings.setdefault(node.id, set()).add("<rebound>")
        elif isinstance(node, ast.arg):
            bindings.setdefault(node.arg, set()).add("<parameter>")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.setdefault(node.name, set()).add("<definition>")
    # Ambiguity must remain a binding, never become apparent builtin absence.
    return {name: next(iter(values)) if len(values) == 1 else "<ambiguous>"
            for name, values in bindings.items()}


def _validate_imports(tree: ast.AST) -> tuple[str, str]:
    bindings = _import_bindings(tree)
    if any(name in bindings for name in ("dict", "compile", "exec", "TypeError")):
        raise ValueError("false-identity builtin binding is missing or rebound")
    if bindings.get("runtime") != "repomap_test_support.test_cov5k_r2_fix2_runtime":
        raise ValueError("runtime import is missing, aliased or rebound")
    if bindings.get(TARGET_SYMBOL) != f"{TARGET_MODULE}.{TARGET_SYMBOL}":
        raise ValueError("runtime helper import is missing, aliased or rebound")
    required = {
        "pytest": "pytest",
        "subprocess": "subprocess",
        "_psycopg_entry": "<definition>",
        "_execute_with_caller_terminal_owner": "<definition>",
        "public_expected_authority":
            "repomap_test_support.test_cov5k_r2_fix4_psycopg.public_expected_authority",
    }
    if any(bindings.get(name) != origin for name, origin in required.items()):
        raise ValueError("false-identity refusal binding is missing, aliased or rebound")

    runtime_aliases = [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == "repomap_test_support"
        for alias in node.names
        if alias.name == "test_cov5k_r2_fix2_runtime" and alias.asname == "runtime"
    ]
    helper_aliases = [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == TARGET_MODULE
        for alias in node.names
        if alias.name == TARGET_SYMBOL and alias.asname is None
    ]
    if len(runtime_aliases) != 1 or len(helper_aliases) != 1:
        raise ValueError("false-identity imports do not bind the maintained runtime helper")
    target = bindings[TARGET_SYMBOL]
    module, symbol = target.rsplit(".", 1)
    return module, symbol


def _validate_runtime_mutation(tree: ast.AST) -> None:
    mutators = {"clear", "pop", "popitem", "setdefault", "update", "__delitem__", "__setitem__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _name(node.value, "runtime") and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise ValueError("false-identity runtime attributes must not be mutated")
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            value = node.value
            if _name(value, "runtime") or (
                isinstance(value, ast.Attribute)
                and _name(value.value, "runtime")
                and value.attr == "__dict__"
            ):
                raise ValueError("false-identity runtime namespace must not be mutated")
        if isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Name)
                and function.id in {"setattr", "delattr"}
                and node.args
                and _name(node.args[0], "runtime")
            ):
                raise ValueError("false-identity runtime attributes must not be mutated")
            if (
                isinstance(function, ast.Attribute)
                and function.attr in mutators
                and isinstance(function.value, ast.Attribute)
                and _name(function.value.value, "runtime")
                and function.value.attr == "__dict__"
            ):
                raise ValueError("false-identity runtime namespace must not be mutated")


def _call(node: ast.AST, function: str) -> ast.Call:
    if not isinstance(node, ast.Call) or not _name(node.func, function):
        raise ValueError(f"false-identity source must call {function}")
    return node


def _validate_generated_chain(owner: ast.FunctionDef) -> None:
    if (
        owner.decorator_list
        or owner.args.posonlyargs
        or owner.args.args
        or owner.args.kwonlyargs
        or owner.args.vararg
    ):
        raise ValueError("false-identity owner test shape changed")
    if (
        owner.args.kwarg
        or owner.args.defaults
        or owner.args.kw_defaults
        or (owner.returns is not None and not _constant(owner.returns, None))
        or owner.type_comment is not None or owner.type_params
    ):
        raise ValueError("false-identity owner test accepts no arguments")
    if len(owner.body) != 3:
        raise ValueError("false-identity owner test must retain its three-step boundary")

    assignment = owner.body[0]
    if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
        raise ValueError("false-identity namespace assignment changed")
    if not _name(assignment.targets[0], "namespace"):
        raise ValueError("false-identity namespace must remain local")
    copied = _call(assignment.value, "dict")
    if len(copied.args) != 1 or copied.keywords:
        raise ValueError("false-identity namespace must be a copied runtime dictionary")
    runtime_dict = copied.args[0]
    if not (
        isinstance(runtime_dict, ast.Attribute)
        and _name(runtime_dict.value, "runtime")
        and runtime_dict.attr == "__dict__"
    ):
        raise ValueError("false-identity namespace must copy runtime.__dict__")

    execution = owner.body[1]
    if not isinstance(execution, ast.Expr):
        raise ValueError("false-identity source execution boundary changed")
    executor = _call(execution.value, "exec")
    if len(executor.args) != 2 or executor.keywords:
        raise ValueError("false-identity exec must receive only code and local namespace")
    if not _name(executor.args[1], "namespace"):
        raise ValueError("false-identity exec must use the copied local namespace")
    compiler = _call(executor.args[0], "compile")
    if len(compiler.args) != 3 or compiler.keywords:
        raise ValueError("false-identity compile arguments changed")
    source = compiler.args[0]
    if not isinstance(source, ast.Constant) or not isinstance(source.value, str):
        raise ValueError("false-identity generated source must be a literal string")
    if source.value.encode("utf-8") != _GENERATED_SOURCE.encode("utf-8"):
        raise ValueError("false-identity generated source bytes changed")
    if not (
        isinstance(compiler.args[1], ast.Attribute)
        and _name(compiler.args[1].value, "runtime")
        and compiler.args[1].attr == "__file__"
    ):
        raise ValueError("false-identity compile filename must be runtime.__file__")
    if not _constant(compiler.args[2], "exec"):
        raise ValueError("false-identity compile mode must be exec")
    refusal = owner.body[2]
    if not isinstance(refusal, ast.With) or len(refusal.items) != 1 or len(refusal.body) != 1:
        raise ValueError("false-identity refusal boundary changed")
    raises = refusal.items[0].context_expr
    if not (
        isinstance(raises, ast.Call)
        and isinstance(raises.func, ast.Attribute)
        and _name(raises.func.value, "pytest")
        and raises.func.attr == "raises"
    ):
        raise ValueError("false-identity refusal must use pytest.raises")
    if len(raises.args) != 1 or not _name(raises.args[0], "TypeError"):
        raise ValueError("false-identity refusal must assert TypeError")
    if len(raises.keywords) != 1 or raises.keywords[0].arg != "match":
        raise ValueError("false-identity refusal must retain its match assertion")
    if not _constant(raises.keywords[0].value, "terminal_owner"):
        raise ValueError("false-identity refusal must match terminal_owner")
    invocation = refusal.body[0]
    if not isinstance(invocation, ast.Expr):
        raise ValueError("false-identity refusal body changed")
    helper = _call(invocation.value, "_execute_with_caller_terminal_owner")
    if len(helper.args) != 1:
        raise ValueError("false-identity refusal helper call changed")
    entry = _call(helper.args[0], "_psycopg_entry")
    if len(entry.args) != 1 or entry.keywords or not _constant(entry.args[0], "success"):
        raise ValueError("false-identity refusal entry changed")
    keywords = {keyword.arg: keyword.value for keyword in helper.keywords}
    if set(keywords) != {"psql_args", "expected_authority", "terminal_owner"}:
        raise ValueError("false-identity refusal arguments changed")
    psql_args = keywords["psql_args"]
    if not isinstance(psql_args, ast.Tuple) or len(psql_args.elts) != 2:
        raise ValueError("false-identity refusal psql arguments changed")
    if not all(
        _constant(value, expected)
        for value, expected in zip(psql_args.elts, ("-h", "127.0.0.1"))
    ):
        raise ValueError("false-identity refusal psql arguments changed")
    authority = _call(keywords["expected_authority"], "public_expected_authority")
    if authority.args or authority.keywords:
        raise ValueError("false-identity refusal authority call changed")
    code_object = keywords["terminal_owner"]
    if not (
        isinstance(code_object, ast.Subscript)
        and _name(code_object.value, "namespace")
        and _constant(code_object.slice, GENERATED_SYMBOL)
    ):
        raise ValueError("false-identity code object must come from namespace[same_module_alternate]")

def _validate_target(repo_root: Path, modules: Mapping[str, str]) -> None:
    package_path = modules.get(PACKAGE_MODULE)
    package = repo_root / PACKAGE_INIT_PATH
    if package_path != PACKAGE_INIT_PATH or package.is_symlink() or not package.is_file():
        raise ValueError("false-identity package initialization is unsupported")
    if dynamic_operations(ast.parse(package.read_bytes(), filename=PACKAGE_INIT_PATH)):
        raise ValueError("false-identity package initialization is unsupported")
    path = modules.get(TARGET_MODULE)
    if path != TARGET_PATH:
        raise ValueError("false-identity runtime target is missing or aliased")
    full_path = repo_root / path
    root = repo_root.resolve()
    if full_path.is_symlink() or not full_path.is_file() or full_path.resolve() != root / path:
        raise ValueError("false-identity runtime target is missing or aliased")
    source = full_path.read_bytes()
    target_tree = ast.parse(source, filename=path)
    defined = {node.name for node in target_tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    if TARGET_SYMBOL not in defined:
        raise ValueError("false-identity runtime helper symbol is absent")
    top_level = set(defined)
    top_level.update(
        target.id
        for node in target_tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    )
    top_level.update(
        alias.asname or alias.name.split(".")[0]
        for node in target_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    )
    if GENERATED_SYMBOL in top_level:
        raise ValueError("false-identity generated symbol claims a real target owner")


def _validate_helper_relationship(tree: ast.AST) -> None:
    if not isinstance(tree, ast.Module):
        raise ValueError("false-identity helper must be module-local")
    for name, source in HELPERS.items():
        helper = _function(tree, name)
        expected = ast.parse(source).body[0]
        if helper not in tree.body or ast.dump(helper) != ast.dump(expected):
            raise ValueError("false-identity execute_runtime_driver_read helper relationship changed")
    initialization = copy.deepcopy(tree)
    for node in initialization.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.body = [ast.Pass()]
    if ast.dump(initialization) != ast.dump(ast.parse(INITIALIZATION)):
        raise ValueError("false-identity module initialization changed")


def generated_false_code_identity(
    operation: ast.Call,
    tree: ast.AST,
    parameters: Mapping[str, Any],
    repo_root: Path,
    modules: Mapping[str, str],
    graph: Mapping[str, Any] | None = None,
) -> set[tuple[str, str]]:
    """Resolve the exact false-identity test without executing target code."""
    if not isinstance(operation, ast.Call) or not isinstance(parameters, Mapping):
        raise ValueError("invalid generated false-identity recipe inputs")
    owner = _function(tree, OWNER_SYMBOL)
    target_module, target_symbol = _validate_imports(tree)
    _validate_runtime_mutation(tree)
    _validate_chain(operation, tree, parameters)
    _validate_generated_chain(owner)
    _validate_helper_relationship(tree)
    _validate_target(repo_root, modules)
    if (target_module, target_symbol) != (TARGET_MODULE, TARGET_SYMBOL):
        raise ValueError("false-identity target is not the maintained runtime helper")
    return {(target_module, target_symbol)}
