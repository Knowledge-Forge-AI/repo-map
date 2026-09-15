"""Unit tests for bounded dynamic operation detector in Python retention."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ci.python_retention_operations import (
    detect_dynamic_calls,
    dynamic_operations,
)

ENFORCED_DOCKER_RELOAD_PATHS = (
    "src/test/support/python/repomap_test_support/resource_test_image_commands.py",
    "src/test/support/python/repomap_test_support/resource_test_image_materialization.py",
    "src/test/support/python/repomap_test_support/resource_test_image_build_context.py",
)


def test_enclosing_symbol_determinism_and_nesting() -> None:
    source = """
eval('root')

def func_a():
    eval('func_a')
    def inner_b():
        eval('inner_b')

class Service:
    eval('class_body')
    def method_c(self):
        eval('method_c')

    class InnerClass:
        def nested_method(self):
            eval('nested')

async def async_worker():
    eval('async_worker')
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    symbols = [op["symbol"] for op in ops]
    assert symbols == [
        "<module>",
        "func_a",
        "func_a.inner_b",
        "Service",
        "Service.method_c",
        "Service.InnerClass.nested_method",
        "async_worker",
    ]


def test_enclosing_symbol_sensitivity() -> None:
    source1 = "def worker(): eval('1')\n"
    source2 = "def dispatch(): eval('1')\n"
    ops1 = dynamic_operations(ast.parse(source1))
    ops2 = dynamic_operations(ast.parse(source2))
    assert ops1[0]["symbol"] == "worker"
    assert ops2[0]["symbol"] == "dispatch"
    assert ops1[0]["symbol"] != ops2[0]["symbol"]


def test_fingerprint_determinism_and_sensitivity() -> None:
    source_a = "import importlib\nimportlib.import_module('module_a')\n"
    source_b = "import importlib\nimportlib.import_module('module_b')\n"
    tree_a1 = ast.parse(source_a)
    tree_a2 = ast.parse(source_a)
    tree_b = ast.parse(source_b)

    ops_a1 = dynamic_operations(tree_a1)
    ops_a2 = dynamic_operations(tree_a2)
    ops_b = dynamic_operations(tree_b)

    assert len(ops_a1) == 1
    assert len(ops_a2) == 1
    assert len(ops_b) == 1

    # Determinism: identical AST yields identical fingerprint
    assert ops_a1[0]["fingerprint"] == ops_a2[0]["fingerprint"]
    # Sensitivity: distinct argument yields distinct fingerprint
    assert ops_a1[0]["fingerprint"] != ops_b[0]["fingerprint"]


def test_fingerprint_position_invariance() -> None:
    source1 = "eval('payload')\n"
    source2 = "\n\n# comment\n\n\ndef wrapper():\n    pass\n\neval('payload')\n"

    op1 = dynamic_operations(ast.parse(source1))[0]
    op2 = dynamic_operations(ast.parse(source2))[0]

    assert op1["fingerprint"] == op2["fingerprint"]
    assert op1["lineno"] != op2["lineno"]


def test_aliased_import_module_and_runpy() -> None:
    source = """
import importlib as il
from importlib import import_module as im
import runpy as rp
from runpy import run_path as rpath, run_module as rmod
from importlib.util import module_from_spec as mfs, spec_from_file_location as sffl

def run():
    m1 = il.import_module('mod1')
    m2 = im('mod2')
    rp.run_module('pkg.mod')
    rpath('script.py')
    rmod('another.mod')
    mfs(None)
    sffl('name', 'path.py')
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    kinds = [op["kind"] for op in ops]
    assert kinds == [
        "import_module",
        "import_module",
        "run_module",
        "run_path",
        "run_module",
        "module_from_spec",
        "spec_from_file_location",
    ]


def test_aliased_builtins_and_sys_modules() -> None:
    source = """
from builtins import eval as my_eval, exec as my_exec, __import__ as my_import
from sys import modules as my_sys_modules

def evaluate():
    my_eval('1 + 1')
    my_exec('x = 1')
    my_import('json')
    _ = my_sys_modules['os']
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    kinds = [op["kind"] for op in ops]
    assert kinds == ["eval", "exec", "__import__", "modules"]


def test_multiple_import_aliases_remain_independently_detected() -> None:
    source = """
from importlib import import_module as alias_fn
from importlib import import_module as other_fn

def execute():
    alias_fn('transitive_target')
    other_fn('other_target')
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    kinds = [op["kind"] for op in ops]
    assert kinds == ["import_module", "import_module"]


def test_python_reload_detection() -> None:
    source = """
import importlib
import importlib as il
from importlib import reload
from importlib import reload as rld

def perform_reloads(target_mod):
    importlib.reload(target_mod)
    il.reload(target_mod)
    reload(target_mod)
    rld(target_mod)

"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    kinds = [op["kind"] for op in ops]
    assert kinds == ["reload", "reload", "reload", "reload"]


def test_re_compile_negative_controls() -> None:
    source = """
import re
import re as rx
from re import compile as rcomp

def patterns():
    re.compile(r'\\d+')
    rx.compile(r'[a-z]+')
    rcomp(r'\\w+')
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    assert ops == []


def test_docker_reload_negative_controls_synthetic() -> None:
    source = """
class FakeContainer:
    def reload(self) -> None:
        pass

def handle_docker(client, container, network):
    container.reload()
    network.reload()
    fake = FakeContainer()
    fake.reload()
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    reasons = detect_dynamic_calls(tree)
    assert ops == []
    assert reasons == []


def test_docker_reload_negative_controls_source_backed() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    for rel_path in ENFORCED_DOCKER_RELOAD_PATHS:
        full_path = repo_root / rel_path
        assert full_path.is_file(), f"enforced source file missing: {rel_path}"
        source = full_path.read_text(encoding="utf-8")
        assert ".reload()" in source, f"expected .reload() in {rel_path}"
        tree = ast.parse(source, filename=rel_path)
        ops = dynamic_operations(tree)
        reasons = detect_dynamic_calls(tree)
        assert ops == [], f"unexpected dynamic operations in {rel_path}: {ops}"
        assert reasons == [], f"unexpected detect reasons in {rel_path}: {reasons}"


def test_detect_dynamic_calls_wrapper_format() -> None:
    source = """
import importlib
import sys

def dynamic_loader():
    importlib.import_module('a')
    importlib.reload(sys)
    _ = sys.modules['b']
    eval('1')
"""
    tree = ast.parse(source)
    reasons = detect_dynamic_calls(tree)
    assert reasons == [
        "dynamic call to eval",
        "dynamic call to import_module",
        "dynamic call to reload",
        "subscript access to modules",
    ]


@pytest.mark.parametrize("prefix", ["def", "async def"])
@pytest.mark.parametrize("parameters", [
    "x: eval('int')", "x: eval('int'), /", "*, x: eval('int')",
    "*args: eval('int')", "**kwargs: eval('int')",
])
def test_parameter_annotations_retain_dynamic_uncertainty(prefix: str, parameters: str) -> None:
    source = f"{prefix} function({parameters}): pass\n"
    operations = dynamic_operations(ast.parse(source))
    assert [(op["kind"], op["symbol"]) for op in operations] == [("eval", "<module>")]


@pytest.mark.parametrize("declaration", ["def f[T: eval('int')](): pass",
                                          "async def f[T: eval('int')](): pass",
                                          "class C[T: eval('int')]: pass"])
def test_type_parameter_bounds_retain_dynamic_uncertainty(declaration: str) -> None:
    operations = dynamic_operations(ast.parse(declaration))
    assert [(op["kind"], op["symbol"]) for op in operations] == [("eval", "<module>")]


def test_exec_module_receiver_agnostic_detection() -> None:
    source = """
class CustomLoader:
    def exec_module(self, mod): pass

def run_execs(spec, loader, obj):
    spec.loader.exec_module(None)
    loader.exec_module(None)
    obj.exec_module(None)
    exec_module(None)
"""
    tree = ast.parse(source)
    ops = dynamic_operations(tree)
    assert len(ops) == 4
    for op in ops:
        assert op["kind"] == "exec_module"
        assert op["symbol"] == "run_execs"
