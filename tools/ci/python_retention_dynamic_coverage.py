"""Closed literal-file coverage probes, validated without executing fixture code."""

from __future__ import annotations

import ast
from typing import Any

from ci.python_retention_dynamic_recipes import imported_names
from ci.python_retention_dynamic_coverage_templates import CHILD_COVERAGE_TEMPLATES, TAILS
from ci.python_retention_operations import dynamic_operations
from ci.python_retention_owner_contract import validate_owner_context


CASES: dict[str, dict[str, Any]] = {
    "uncovered_branch": {
        "symbol": "test_raw_coverage_export_preserves_uncovered_branch",
        "filename": "sample.py",
        "source_utf8": "def choose(flag):\n    if flag:\n        return 1\n    return 2\n",
        "suffix": "choose(True)\n", "branch": True, "namespace": "namespace",
        "executed_lines": [3], "missing_lines": [4],
        "executed_branches": [[2, 3]], "missing_branches": [[2, 4]],
    },
    "export_refusal": {
        "symbol": "test_export_write_failure_is_not_silently_discarded",
        "filename": "sample.py", "source_utf8": "value = 1\n",
        "suffix": "", "branch": None, "namespace": "{}",
        "executed_lines": [], "missing_lines": [],
        "executed_branches": [], "missing_branches": [],
    },
    "direct_report": {
        "symbol": "test_runner_coverage_reports_direct_invocation",
        "filename": "mod.py", "source_utf8": "a = 1\nb = 2\n",
        "suffix": "", "branch": False, "namespace": "{}",
        "executed_lines": [], "missing_lines": [],
        "executed_branches": [], "missing_branches": [],
    },
}


CHILD_CASES: dict[str, dict[str, Any]] = {
    "caller_mod": {
        "class_name": "ChildCoverageSessionUnitTests",
        "method_name": "test_run_pytest_with_coverage_default_caller_path_and_reporting",
        "symbol": "ChildCoverageSessionUnitTests.test_run_pytest_with_coverage_default_caller_path_and_reporting.fake_run_pytest",
        "filename": "caller_mod.py",
        "source_utf8": "def hello(): return 'world'\n",
        "targets": {("runner_coverage", ""), ("run_tests", "")},
    },
    "decision_mod": {
        "class_name": "WorkDRegressionUnitTests",
        "method_name": "test_regr1_nested_coverage_preserves_branch_arcs",
        "symbol": "WorkDRegressionUnitTests.test_regr1_nested_coverage_preserves_branch_arcs",
        "filename": "decision_mod.py",
        "source_utf8": "def branch_fn(val):\n    if val > 0:\n        return 1\n    return 0\n",
        "targets": {("runner_coverage", "")},
    },
}

_CAPABILITY_SPEC: dict[str, Any] = {
    "class_name": "ChildCoverageCapabilityUnitTests",
    "method_name": "test_prelaunch_registration_and_accept_validation",
    "symbol": "ChildCoverageCapabilityUnitTests.test_prelaunch_registration_and_accept_validation",
    "filename": "sample.py",
    "source_utf8": "def fn():\n    return 42\n",
    "owner": "src/test/unit/python/tools/test_runner_coverage_capability.unit.test.py",
    "targets": {("runner_coverage", ""), ("runner_coverage_capability", "")},
}

CAPABILITY_CASES: dict[str, dict[str, Any]] = {
    "capability_mod": _CAPABILITY_SPEC,
}



def _child_coverage_fixture(
    call: ast.AST, tree: ast.Module, parameters: dict[str, Any], case: str,
) -> set[tuple[str, str]]:
    spec = CHILD_CASES[case]
    if set(parameters) != {"schema", "case", "filename", "source_utf8", "symbol", "chain"}:
        raise ValueError("unsupported child coverage parameters")
    if parameters.get("schema") != "literal-coverage-fixture-v1":
        raise ValueError("coverage fixture schema mismatch")
    if parameters.get("filename") != spec["filename"]:
        raise ValueError("child coverage filename differs from declaration")
    if parameters.get("source_utf8") != spec["source_utf8"]:
        raise ValueError("child coverage literal source differs from declaration")
    if parameters.get("symbol") != spec["symbol"]:
        raise ValueError("child coverage symbol differs from declaration")

    cls_nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == spec["class_name"]]
    if len(cls_nodes) != 1:
        raise ValueError("child coverage class absent or ambiguous")
    method_nodes = [
        n for n in cls_nodes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == spec["method_name"]
    ]
    if len(method_nodes) != 1:
        raise ValueError("child coverage method absent or ambiguous")
    method = method_nodes[0]

    if not any(n is call for n in ast.walk(method)):
        raise ValueError("coverage operation is outside its fixture")

    has_write = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "write_text"
        and any(isinstance(a, ast.Constant) and a.value == spec["source_utf8"] for a in n.args)
        for n in ast.walk(method)
    )
    if not has_write:
        raise ValueError("child coverage literal source write differs from recipe")

    mod_stem = spec["filename"][:-3]
    has_pop = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "pop"
        and any(isinstance(a, ast.Constant) and a.value == mod_stem for a in n.args)
        for n in ast.walk(method)
    )
    if not has_pop:
        raise ValueError("child coverage sys.modules cleanup missing")

    ops = dynamic_operations(method)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    if [op["kind"] for op in chain] != ["import_module"]:
        raise ValueError("unexpected dynamic operations in child coverage method")
    if parameters.get("chain") != chain:
        raise ValueError("child coverage chain differs from actual operations")

    expected_template = CHILD_COVERAGE_TEMPLATES.get(case)
    if not expected_template:
        raise ValueError(f"no template for child coverage case {case}")
    expected_node = ast.parse(expected_template).body[0]
    if ast.dump(method, include_attributes=False) != ast.dump(expected_node, include_attributes=False):
        raise ValueError(f"child coverage method AST differs from template for {case}")


    return set(spec["targets"])


def _capability_coverage_fixture(
    call: ast.AST, tree: ast.Module, parameters: dict[str, Any], case: str,
) -> set[tuple[str, str]]:
    spec = CAPABILITY_CASES[case]
    if set(parameters) != {"schema", "case", "filename", "source_utf8", "symbol", "chain"}:
        raise ValueError("unsupported capability coverage parameters")
    if parameters.get("schema") != "literal-coverage-fixture-v1":
        raise ValueError("coverage fixture schema mismatch")
    if parameters.get("filename") != spec["filename"]:
        raise ValueError("capability coverage filename differs from declaration")
    if parameters.get("source_utf8") != spec["source_utf8"]:
        raise ValueError("capability coverage literal source differs from declaration")
    if parameters.get("symbol") != spec["symbol"]:
        raise ValueError("capability coverage symbol differs from declaration")

    cls_nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == spec["class_name"]]
    if len(cls_nodes) != 1:
        raise ValueError("capability coverage class absent or ambiguous")
    method_nodes = [
        n for n in cls_nodes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == spec["method_name"]
    ]
    if len(method_nodes) != 1:
        raise ValueError("capability coverage method absent or ambiguous")
    method = method_nodes[0]

    if not any(n is call for n in ast.walk(method)):
        raise ValueError("coverage operation is outside its fixture")

    setup_methods = [
        n for n in cls_nodes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "setUp"
    ]
    if len(setup_methods) != 1:
        raise ValueError("capability coverage setUp absent or ambiguous")
    has_write = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "write_text"
        and any(isinstance(a, ast.Constant) and a.value == spec["source_utf8"] for a in n.args)
        for n in ast.walk(setup_methods[0])
    )
    if not has_write:
        raise ValueError("capability coverage literal source write differs from recipe")

    ops = dynamic_operations(method)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    if [op["kind"] for op in chain] != ["compile", "exec"]:
        raise ValueError("unexpected dynamic operations in capability coverage method")
    if parameters.get("chain") != chain:
        raise ValueError("capability coverage chain differs from actual operations")

    try_nodes = [
        n for n in method.body
        if isinstance(n, ast.Try) and any(
            c is call or (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in {"compile", "exec"})
            for c in ast.walk(n)
        )
    ]
    if len(try_nodes) != 1:
        raise ValueError("capability coverage execution must be enclosed in a unique try block")
    try_node = try_nodes[0]

    if try_node.handlers:
        raise ValueError("capability coverage must not catch or suppress exceptions in try block")

    has_stop = any(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "stop"
        for n in try_node.finalbody
    )
    if not has_stop:
        raise ValueError("capability coverage collector stop must be in finally block")

    has_correct_exec = False
    for n in try_node.body:
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "exec":
            exec_call = n.value
            if len(exec_call.args) >= 2:
                ns_arg = exec_call.args[1]
                if isinstance(ns_arg, ast.Dict) and len(ns_arg.keys) == 0:
                    compile_call = exec_call.args[0]
                    if isinstance(compile_call, ast.Call) and isinstance(compile_call.func, ast.Name) and compile_call.func.id == "compile":
                        if len(compile_call.args) >= 3:
                            mode_arg = compile_call.args[2]
                            if isinstance(mode_arg, ast.Constant) and mode_arg.value == "exec":
                                has_correct_exec = True
    if not has_correct_exec:
        raise ValueError("capability coverage exec/compile execution or namespace differs from recipe")

    has_sample_source = any(
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "sample" for t in n.targets)
        and isinstance(n.value, ast.BinOp) and isinstance(n.value.right, ast.Constant) and n.value.right.value == spec["filename"]
        for n in try_node.body
    )
    if not has_sample_source:
        raise ValueError("capability coverage source file reference differs from recipe")

    try_idx = method.body.index(try_node)
    if try_idx == 0:
        raise ValueError("capability coverage collector start missing before try block")

    has_start = any(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "start"
        for n in method.body[:try_idx]
    )
    if not has_start:
        raise ValueError("capability coverage collector start missing before try block")

    if try_idx + 1 >= len(method.body):
        raise ValueError("capability coverage collector save missing after try block")

    next_stmt = method.body[try_idx + 1]
    is_save = (
        isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Call)
        and isinstance(next_stmt.value.func, ast.Attribute) and next_stmt.value.func.attr == "save"
    )
    if not is_save:
        raise ValueError("capability coverage collector save must immediately follow try block")

    validate_owner_context(spec["owner"], tree)

    return set(spec["targets"])


def _body(tree: ast.Module, symbol: str) -> list[ast.stmt]:
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol]
    if len(functions) != 1:
        raise ValueError("coverage fixture owner absent or ambiguous")
    function = functions[0]
    signature = ast.parse(f"def {symbol}(tmp_path: Path, request: pytest.FixtureRequest) -> None: pass").body[0]
    assert isinstance(signature, ast.FunctionDef)
    if (ast.dump(function.args) != ast.dump(signature.args)
            or function.decorator_list or function.type_params):
        raise ValueError("coverage fixture must own the pytest temporary root")
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body.pop(0)
    return body


def coverage_fixture(call: ast.AST, tree: ast.Module, parameters: dict[str, Any]) -> set[tuple[str, str]]:
    """Bind literal bytes, execution provenance, collector lifetime and export assertions."""
    case = parameters.get("case")
    if not isinstance(case, str):
        raise ValueError("unsupported coverage fixture case")
    if case in CHILD_CASES:
        return _child_coverage_fixture(call, tree, parameters, case)
    if case in CAPABILITY_CASES:
        return _capability_coverage_fixture(call, tree, parameters, case)
    if case not in CASES:
        raise ValueError("unsupported coverage fixture case")
    spec = CASES[case]
    symbol = str(spec["symbol"])
    body = _body(tree, symbol)
    source = repr(spec["source_utf8"])
    filename = repr(spec["filename"])
    branch = "" if spec["branch"] is None else f"branch={spec['branch']}, "
    namespace = str(spec["namespace"])
    namespace_setup = "namespace: dict[str, object] = {}\n" if namespace == "namespace" else ""
    suffix = " + " + repr(spec["suffix"]) if spec["suffix"] else ""
    prologue = ast.parse(
        f"source = tmp_path / {filename}\n"
        f"source.write_text({source}, encoding='utf-8')\n"
        f"collector = coverage.Coverage({branch}data_file=None, config_file=False)\n"
        "request.addfinalizer(lambda: collector.get_data().close(force=True))\n"
        f"{namespace_setup}collector.start()\n"
        f"try:\n    exec(compile(source.read_text(){suffix}, str(source), 'exec'), {namespace})\n"
        "finally:\n    collector.stop()\n"
    ).body
    if [ast.dump(n) for n in body[:len(prologue)]] != [ast.dump(n) for n in prologue]:
        raise ValueError("coverage source construction or measurement ownership differs")
    tail = ast.Module(body=body[len(prologue):], type_ignores=[])
    if ast.dump(tail) != ast.dump(ast.parse(TAILS[symbol])):
        raise ValueError("coverage export, source root or cleanup tail differs")
    names = imported_names(tree)
    required_imports = {"coverage": "coverage", "Path": "pathlib.Path",
                        "runner_coverage": "runner_coverage",
                        "runner_coverage_reports": "runner_coverage_reports", "pytest": "pytest"}
    if case == "uncovered_branch":
        required_imports.update({"patch": "unittest.mock.patch", "json": "json",
                                 "write_html_report": "test_report.write_html_report"})
    if case == "export_refusal":
        required_imports["pytest"] = "pytest"
    if any(names.get(k) != v for k, v in required_imports.items()):
        raise ValueError("coverage fixture imports are ambiguous or rebound")
    for name in ("exec", "compile", "str", "dict"):
        if name in names and names[name] != "builtins." + name:
            raise ValueError("coverage execution builtin imported from another owner")
    for top in tree.body:
        if isinstance(top, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(top, ast.FunctionDef) and not top.decorator_list:
            continue
        if isinstance(top, ast.Expr) and isinstance(top.value, ast.Constant) and isinstance(top.value.value, str):
            continue
        raise ValueError("coverage fixture module has unsupported initialization")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in {"exec", "compile", "str", "dict"}:
                raise ValueError("coverage execution builtin rebound")
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "exec", "compile", "str", "dict"
        }:
            raise ValueError("coverage execution builtin replaced")
    scope = ast.Module(body=body, type_ignores=[])
    operations = dynamic_operations(scope)
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in operations]
    if sorted(op["kind"] for op in chain) != ["compile", "exec"]:
        raise ValueError("coverage fixture has undeclared or extra execution")
    expected = {"schema": "literal-coverage-fixture-v1", "case": case,
                "temporary_root": "pytest.tmp_path", **spec, "chain": chain}
    if parameters != expected:
        raise ValueError("coverage fixture declaration differs from independent construction")
    if not any(n is call for n in ast.walk(scope)):
        raise ValueError("coverage operation is outside its fixture")
    required = {("runner_coverage", ""), ("runner_coverage_reports", "")}
    if case == "uncovered_branch":
        required.add(("test_report", "write_html_report"))
    return required
