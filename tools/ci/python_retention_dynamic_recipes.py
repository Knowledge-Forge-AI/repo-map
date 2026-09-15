"""Closed AST recipes; a source fingerprint alone never discharges uncertainty."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping


def fingerprint(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def imported_names(tree: ast.AST) -> dict[str, str]:
    """Resolve explicit import spellings; ambiguous rebinding cannot prove a recipe."""
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                bindings.setdefault(name, set()).add(alias.name if alias.asname else name)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                bindings.setdefault(alias.asname or alias.name, set()).add(
                    f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings.setdefault(node.id, set()).add("<rebound>")
        elif isinstance(node, ast.arg):
            bindings.setdefault(node.arg, set()).add("<parameter>")
    return {key: next(iter(values)) for key, values in bindings.items() if len(values) == 1}


def qualified(node: ast.AST, names: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return names.get(node.id, "")
    if isinstance(node, ast.Attribute):
        base = qualified(node.value, names)
        return f"{base}.{node.attr}" if base else ""
    return ""


def literal_module_entry(call: ast.Call, tree: ast.AST, parameters: dict[str, Any],
                         modules: Mapping[str, str]) -> set[tuple[str, str]]:
    """Bind package initialization plus real __main__ execution with exact arguments."""
    if (qualified(call.func, imported_names(tree)) != "runpy.run_module"
            or len(call.args) != 1 or len(call.keywords) != 1
            or call.keywords[0].arg != "run_name"):
        raise ValueError("unsupported module-entry operation")
    module, run_name = ast.literal_eval(call.args[0]), ast.literal_eval(call.keywords[0].value)
    if (not isinstance(module, str) or run_name != "__main__"
            or parameters != {"module": module, "run_name": run_name}):
        raise ValueError("module-entry declaration differs from source")
    target = modules.get(module)
    if target is None:
        raise ValueError("module-entry target is absent or ambiguous")
    required = {(module, "")}
    if target.endswith("/__init__.py"):
        required.add((module + ".__main__", ""))
    return required


def guarded_symbol_import(call: ast.Call, tree: ast.AST, parameters: dict[str, Any],
                          repo_root: Path, modules: Mapping[str, str]) -> set[tuple[str, str]]:
    """Verify the complete small independent resolver and its literal closed domain."""
    if set(parameters) != {"domain_path", "domain_sha256", "domain_module"}:
        raise ValueError("invalid guarded resolver parameters")
    path = parameters["domain_path"]
    if modules.get(parameters["domain_module"]) != path:
        raise ValueError("closed domain module/source mismatch")
    full = repo_root / path
    if not full.resolve().is_relative_to(repo_root.resolve()) or full.is_symlink():
        raise ValueError("closed domain source alias")
    source = full.read_bytes()
    if hashlib.sha256(source).hexdigest() != parameters["domain_sha256"]:
        raise ValueError("closed domain source drift")
    domain_tree = ast.parse(source)
    for node in domain_tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            raise ValueError("closed domain must contain only literal declarations")
        target_nodes = node.targets if isinstance(node, ast.Assign) else [node.target]
        if (len(target_nodes) != 1 or not isinstance(target_nodes[0], ast.Name)
                or target_nodes[0].id not in {"PYTHON_TARGETS", "EXTERNAL_TARGETS"}):
            raise ValueError("unexpected closed domain declaration")
        if node.value is None:
            raise ValueError("closed domain declaration has no value")
        ast.literal_eval(node.value)
    assignments = [n for n in domain_tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))]
    values = []
    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if len(targets) == 1 and isinstance(targets[0], ast.Name) and targets[0].id == "PYTHON_TARGETS":
            if node.value is None:
                raise ValueError("closed domain declaration has no value")
            values.append(ast.literal_eval(node.value))
    if len(values) != 1 or not isinstance(values[0], tuple) or not values[0]:
        raise ValueError("closed domain requires one nonempty literal tuple")
    domain = values[0]
    if any(not isinstance(t, tuple) or len(t) != 2 or
           any(not isinstance(v, str) or not v for v in t) for t in domain):
        raise ValueError("invalid closed module/symbol domain")
    if tuple(sorted(set(domain))) != domain:
        raise ValueError("closed domain must be sorted and unique")
    names = imported_names(tree)
    if names.get("PYTHON_TARGETS") != parameters["domain_module"] + ".PYTHON_TARGETS":
        raise ValueError("closed domain import missing or rebound")
    expected = ast.parse('''def _resolve_symbol(module_name: str, symbol: str):
    if (module_name, symbol) not in PYTHON_TARGETS:
        raise ExecutorEvidenceError("registered symbol outside closed resolver domain")
    value = importlib.import_module(module_name)
    for part in symbol.split("."):
        value = getattr(value, part)
    return value
''').body[0]
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "_resolve_symbol"]
    if (len(functions) != 1 or ast.dump(functions[0]) != ast.dump(expected)
            or qualified(call.func, names) != "importlib.import_module"):
        raise ValueError("independent guarded resolver source differs from recipe")
    return set(domain)
