"""Bounded dynamic operation detector for Python retention."""

from __future__ import annotations

import ast
import hashlib
from typing import Any

DYNAMIC_CALLS = frozenset({
    "__import__",
    "compile",
    "eval",
    "exec",
    "exec_module",
    "import_module",
    "module_from_spec",
    "run_module",
    "run_path",
    "spec_from_file_location",
})

KNOWN_MODULE_TARGETS: dict[str, dict[str, tuple[str, str]]] = {
    "importlib": {
        "import_module": ("importlib", "import_module"),
        "reload": ("importlib", "reload"),
    },
    "importlib.util": {
        "module_from_spec": ("importlib.util", "module_from_spec"),
        "spec_from_file_location": ("importlib.util", "spec_from_file_location"),
    },
    "runpy": {
        "run_module": ("runpy", "run_module"),
        "run_path": ("runpy", "run_path"),
    },
    "sys": {"modules": ("sys", "modules")},
    "builtins": {
        "__import__": ("builtins", "__import__"),
        "compile": ("builtins", "compile"),
        "eval": ("builtins", "eval"),
        "exec": ("builtins", "exec"),
    },
    "imp": {"reload": ("importlib", "reload")},
    "re": {"compile": ("re", "compile")},
}

KNOWN_MODULES = frozenset({
    "builtins", "imp", "importlib", "importlib.machinery",
    "importlib.util", "re", "runpy", "sys",
})


class _OperationVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope_stack: list[str] = []
        self.alias_scopes: list[dict[str, tuple[str, ...]]] = [{}]
        self.local_defs: set[str] = set()
        self.records: list[dict[str, Any]] = []
        self._seen_nodes: set[int] = set()

    @property
    def current_symbol(self) -> str:
        return ".".join(self.scope_stack) if self.scope_stack else "<module>"

    def lookup(self, name: str) -> tuple[str, ...] | None:
        for scope in reversed(self.alias_scopes):
            if name in scope:
                return scope[name]
        return None

    def bind_alias(self, name: str, value: tuple[str, ...]) -> None:
        self.alias_scopes[-1][name] = value

    def _resolve_expr_target(self, expr: ast.AST | None) -> tuple[str, ...] | None:
        if expr is None:
            return None
        if isinstance(expr, ast.Name):
            target = self.lookup(expr.id)
            if target is not None:
                return target
            if expr.id in KNOWN_MODULES:
                return ("module", expr.id)
            if expr.id in DYNAMIC_CALLS:
                return ("target", "builtins", expr.id)
            return None
        if isinstance(expr, ast.Attribute):
            base_target = self._resolve_expr_target(expr.value)
            if base_target is not None and base_target[0] == "module":
                mod = base_target[1]
                if mod in KNOWN_MODULE_TARGETS and expr.attr in KNOWN_MODULE_TARGETS[mod]:
                    return ("target", *KNOWN_MODULE_TARGETS[mod][expr.attr])
                sub_mod = f"{mod}.{expr.attr}"
                if sub_mod in KNOWN_MODULES:
                    return ("module", sub_mod)
            return None
        if isinstance(expr, ast.IfExp):
            b_target = self._resolve_expr_target(expr.body)
            if b_target is not None and b_target[0] == "target":
                return b_target
            o_target = self._resolve_expr_target(expr.orelse)
            if o_target is not None and o_target[0] == "target":
                return o_target
            return b_target or o_target
        return None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            asname = alias.asname or alias.name
            if alias.name in KNOWN_MODULES:
                self.bind_alias(asname, ("module", alias.name))
            elif "." in alias.name:
                top = alias.name.split(".")[0]
                if top in KNOWN_MODULES and not alias.asname:
                    self.bind_alias(top, ("module", top))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            asname = alias.asname or alias.name
            orig = alias.name
            if orig == "*":
                if mod in KNOWN_MODULE_TARGETS:
                    for target_name, target_tuple in KNOWN_MODULE_TARGETS[mod].items():
                        self.bind_alias(target_name, ("target", *target_tuple))
                continue
            full_mod = f"{mod}.{orig}" if mod else orig
            if full_mod in KNOWN_MODULES:
                self.bind_alias(asname, ("module", full_mod))
            elif mod in KNOWN_MODULE_TARGETS and orig in KNOWN_MODULE_TARGETS[mod]:
                self.bind_alias(asname, ("target", *KNOWN_MODULE_TARGETS[mod][orig]))
            elif mod == "builtins" and orig in DYNAMIC_CALLS:
                self.bind_alias(asname, ("target", "builtins", orig))
        self.generic_visit(node)

    def _visit_scoped_callable(
        self,
        name: str,
        decorator_list: list[ast.expr],
        returns: ast.expr | None,
        defaults: list[ast.expr],
        body: list[ast.stmt],
    ) -> None:
        self.local_defs.add(name)
        for dec in decorator_list:
            self.visit(dec)
        if returns:
            self.visit(returns)
        for def_val in defaults:
            self.visit(def_val)
        self.scope_stack.append(name)
        self.alias_scopes.append({})
        for stmt in body:
            self.visit(stmt)
        self.alias_scopes.pop()
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.visit(node.args)
        for parameter in node.type_params:
            self.visit(parameter)
        defaults = node.args.defaults + [d for d in node.args.kw_defaults if d]
        self._visit_scoped_callable(
            node.name, node.decorator_list, node.returns, defaults, node.body
        )

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit(node.args)
        for parameter in node.type_params:
            self.visit(parameter)
        defaults = node.args.defaults + [d for d in node.args.kw_defaults if d]
        self._visit_scoped_callable(
            node.name, node.decorator_list, node.returns, defaults, node.body
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for parameter in node.type_params:
            self.visit(parameter)
        self.local_defs.add(node.name)
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw)
        self.scope_stack.append(node.name)
        self.alias_scopes.append({})
        for stmt in node.body:
            self.visit(stmt)
        self.alias_scopes.pop()
        self.scope_stack.pop()

    def _resolve_call_kind(self, node: ast.Call) -> str | None:
        func = node.func
        if isinstance(func, ast.Name):
            target = self.lookup(func.id)
            if target is not None and target[0] == "target":
                mod, orig = target[1], target[2]
                if mod == "re" and orig == "compile":
                    return None
                return orig if (orig in DYNAMIC_CALLS or orig == "reload") else None
            if func.id == "compile":
                return "compile"
            if func.id == "reload":
                return None if func.id in self.local_defs else "reload"
            return func.id if func.id in DYNAMIC_CALLS else None

        if isinstance(func, ast.Attribute):
            attr = func.attr
            if attr == "reload":
                tgt = self._resolve_expr_target(func.value)
                return "reload" if (tgt and tgt[0] == "module" and tgt[1] in ("importlib", "imp")) else None
            if attr == "compile":
                tgt = self._resolve_expr_target(func.value)
                if (tgt and tgt[0] == "module" and tgt[1] == "re") or (
                    isinstance(func.value, ast.Name) and func.value.id == "re"
                ):
                    return None
                return "compile"
            if attr in DYNAMIC_CALLS:
                return attr
            tgt = self._resolve_expr_target(func.value)
            if tgt and tgt[0] == "module":
                mod = tgt[1]
                if mod in KNOWN_MODULE_TARGETS and attr in KNOWN_MODULE_TARGETS[mod]:
                    orig = KNOWN_MODULE_TARGETS[mod][attr][1]
                    if orig in DYNAMIC_CALLS or orig == "reload":
                        return orig
            return None

        return None

    def _record_operation(self, node: ast.Call | ast.Subscript, kind: str) -> None:
        if id(node) in self._seen_nodes:
            return
        self._seen_nodes.add(id(node))
        dump_clean = ast.dump(node, include_attributes=False)
        dump_expr = ast.dump(node)
        fingerprint = hashlib.sha256(dump_clean.encode("utf-8")).hexdigest()
        self.records.append({
            "kind": kind,
            "symbol": self.current_symbol,
            "fingerprint": fingerprint,
            "lineno": int(getattr(node, "lineno", 0)),
            "expression": dump_expr,
        })

    def visit_Call(self, node: ast.Call) -> None:
        kind = self._resolve_call_kind(node)
        if kind is not None:
            self._record_operation(node, kind)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        val = node.value
        is_modules = False
        if isinstance(val, ast.Attribute) and val.attr == "modules":
            is_modules = True
        elif isinstance(val, ast.Name):
            if val.id == "modules":
                is_modules = True
            else:
                target = self.lookup(val.id)
                if target and target[0] == "target" and target[1:3] == ("sys", "modules"):
                    is_modules = True
        if is_modules:
            self._record_operation(node, "modules")
        self.generic_visit(node)


def _pre_scan_top_level(tree: ast.AST, visitor: _OperationVisitor) -> None:
    if isinstance(tree, ast.Module):
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                visitor.visit_Import(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                visitor.visit_ImportFrom(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visitor.local_defs.add(stmt.name)


def dynamic_operations(tree: ast.AST) -> list[dict[str, Any]]:
    """Return deterministic records of dynamic operations in AST."""
    visitor = _OperationVisitor()
    _pre_scan_top_level(tree, visitor)
    visitor.visit(tree)
    visitor.records.sort(
        key=lambda r: (
            r["lineno"],
            r["symbol"],
            r["kind"],
            r["fingerprint"],
            r["expression"],
        )
    )
    return visitor.records


def detect_dynamic_calls(tree: ast.AST) -> list[str]:
    """Expose detect reasons via existing wrapper format for API compatibility."""
    reasons: list[str] = []
    for op in dynamic_operations(tree):
        if op["kind"] == "modules":
            reasons.append("subscript access to modules")
        else:
            reasons.append(f"dynamic call to {op['kind']}")
    return sorted(reasons)
