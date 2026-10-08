"""Bounded reflection/slot policy for maintained ManagedChild source.

This resolves local constant names and aliases, not arbitrary Python execution.
Unresolved reflection around a protected managed value is refused conservatively.
"""
from __future__ import annotations

import ast


class AbruptReflection:
    string_constants: dict[str, str]
    managed_child_classes: set[str]
    managed_child_instances: set[str]
    descriptor_aliases: dict[str, str]
    descriptor_method_aliases: dict[str, tuple[str, str]]
    object_setattr_aliases: set[str]
    object_getattribute_aliases: set[str]
    filename: str
    bypasses: list[str]

    def _name(self, expr: ast.expr) -> str | None:
        raise NotImplementedError

    def _expr_key(self, expr: ast.expr) -> str | None:
        raise NotImplementedError

    def _is_guard_expr(self, expr: ast.expr) -> bool:
        raise NotImplementedError

    def _resolve_str_constant(self, expr: ast.expr | None) -> str | None:
        if expr is None:
            return None
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        key = self._expr_key(expr)
        if key and hasattr(self, "string_constants") and key in self.string_constants:
            return self.string_constants[key]
        return None

    def _is_managed_child_class_expr(self, expr: ast.expr | None) -> bool:
        if expr is None:
            return False
        name = self._name(expr)
        if name in {"ManagedChild", "ManagedChildProcess"}:
            return True
        key = self._expr_key(expr)
        if key and hasattr(self, "managed_child_classes") and key in self.managed_child_classes:
            return True
        if isinstance(expr, ast.Attribute) and expr.attr == "__class__":
            return self._is_managed_child_expr(expr.value)
        if isinstance(expr, ast.Call) and self._name(expr.func) == "type" and expr.args:
            return self._is_managed_child_expr(expr.args[0])
        return False

    def _is_managed_child_expr(self, expr: ast.expr | None) -> bool:
        if expr is None:
            return False
        if self._is_guard_expr(expr):
            return True
        key = self._expr_key(expr)
        if key and hasattr(self, "managed_child_instances") and key in self.managed_child_instances:
            return True
        if isinstance(expr, ast.Name):
            if expr.id in getattr(self, "managed_child_instances", ()):
                return True
            if expr.id in {"child", "managed_child", "managed_proc", "managed"}:
                return True
        if isinstance(expr, ast.Call) and self._name(expr.func) in {"ManagedChild", "ManagedChildProcess"}:
            return True
        return False

    def _resolve_descriptor_slot(self, expr: ast.expr | None) -> str | None:
        if expr is None:
            return None
        if isinstance(expr, ast.Attribute) and self._is_managed_child_class_expr(expr.value):
            return expr.attr
        if isinstance(expr, ast.Call) and self._name(expr.func) == "getattr" and len(expr.args) >= 2:
            if self._is_managed_child_class_expr(expr.args[0]):
                resolved = self._resolve_str_constant(expr.args[1])
                return resolved if resolved is not None else "<unresolved>"
        if isinstance(expr, ast.Subscript):
            is_mc_dict = False
            if isinstance(expr.value, ast.Attribute) and expr.value.attr == "__dict__":
                is_mc_dict = self._is_managed_child_class_expr(expr.value.value)
            elif isinstance(expr.value, ast.Call) and self._name(expr.value.func) == "vars" and expr.value.args:
                is_mc_dict = self._is_managed_child_class_expr(expr.value.args[0])
            if is_mc_dict:
                resolved = self._resolve_str_constant(expr.slice)
                return resolved if resolved is not None else "<unresolved>"
        key = self._expr_key(expr)
        if key and hasattr(self, "descriptor_aliases") and key in self.descriptor_aliases:
            return self.descriptor_aliases[key]
        return None

    def _record_reflection_assignment(self, node: ast.Assign) -> None:
        val = node.value
        val_str = self._resolve_str_constant(val)
        for target in node.targets:
            for part in ast.walk(target):
                if isinstance(part, ast.Name):
                    self.string_constants.pop(part.id, None)
        if val_str is not None:
            for target in node.targets:
                t_k = self._expr_key(target)
                if t_k:
                    self.string_constants[t_k] = val_str
        elif isinstance(val, (ast.Tuple, ast.List)):
            for target in node.targets:
                if isinstance(target, (ast.Tuple, ast.List)) and len(target.elts) == len(val.elts):
                    for t_elt, v_elt in zip(target.elts, val.elts):
                        t_k = self._expr_key(t_elt)
                        v_s = self._resolve_str_constant(v_elt)
                        if t_k and v_s is not None:
                            self.string_constants[t_k] = v_s
        if self._is_managed_child_class_expr(val):
            for target in node.targets:
                t_k = self._expr_key(target)
                if t_k:
                    self.managed_child_classes.add(t_k)
        slot_desc = self._resolve_descriptor_slot(val)
        if slot_desc:
            for target in node.targets:
                t_k = self._expr_key(target)
                if t_k:
                    self.descriptor_aliases[t_k] = slot_desc
        if isinstance(val, ast.Attribute) and val.attr in {"__set__", "__get__", "__delete__"}:
            slot = self._resolve_descriptor_slot(val.value)
            if slot:
                for target in node.targets:
                    t_k = self._expr_key(target)
                    if t_k:
                        self.descriptor_method_aliases[t_k] = (slot, val.attr)
        elif isinstance(val, ast.Call) and self._name(val.func) == "getattr" and len(val.args) >= 2:
            m_name = self._resolve_str_constant(val.args[1])
            if m_name in {"__set__", "__get__", "__delete__"}:
                slot = self._resolve_descriptor_slot(val.args[0])
                if slot:
                    for target in node.targets:
                        t_k = self._expr_key(target)
                        if t_k:
                            self.descriptor_method_aliases[t_k] = (slot, m_name)

        for target in node.targets:
            key, val_key = self._expr_key(target), self._expr_key(val)
            if not key:
                continue
            if isinstance(val, ast.Call) and self._is_managed_child_class_expr(val.func):
                self.managed_child_instances.add(key)
            method = None
            if isinstance(val, ast.Attribute) and self._name(val.value) == "object":
                method = val.attr
            elif isinstance(val, ast.Call) and self._name(val.func) == "getattr" and len(val.args) >= 2 and self._name(val.args[0]) == "object":
                method = self._resolve_str_constant(val.args[1])
            for method_name, aliases in (("__setattr__", self.object_setattr_aliases), ("__getattribute__", self.object_getattribute_aliases)):
                if method == method_name or val_key in aliases:
                    aliases.add(key)
            if val_key in self.descriptor_method_aliases:
                self.descriptor_method_aliases[key] = self.descriptor_method_aliases[val_key]
            if val_key in self.managed_child_instances:
                self.managed_child_instances.add(key)

    def _check_reflection_call(self, node: ast.Call) -> None:
        # Check object.__setattr__ and aliases
        is_object_setattr = False
        if isinstance(node.func, ast.Attribute) and self._name(node.func.value) == "object" and node.func.attr == "__setattr__":
            is_object_setattr = True
        elif isinstance(node.func, ast.Name) and node.func.id in getattr(self, "object_setattr_aliases", ()):
            is_object_setattr = True
        elif isinstance(node.func, ast.Call) and self._name(node.func.func) == "getattr" and len(node.func.args) >= 2:
            g_attr = self._resolve_str_constant(node.func.args[1])
            if self._name(node.func.args[0]) == "object" and g_attr == "__setattr__":
                is_object_setattr = True

        if is_object_setattr and len(node.args) >= 2 and self.filename != "src/test/support/python/repomap_test_support/sqlite_managed_child.py":
            attr_name = self._resolve_str_constant(node.args[1])
            if attr_name in {"_abrupt", "abrupt", "_ManagedChild__process", "__process"}:
                self.bypasses.append(f"{self.filename}:{node.lineno}: object.__setattr__ bypass")
            elif attr_name is None and self._is_managed_child_expr(node.args[0]):
                self.bypasses.append(f"{self.filename}:{node.lineno}: object.__setattr__ bypass")

        # Check object.__getattribute__ and aliases
        is_object_getattribute = False
        if isinstance(node.func, ast.Attribute) and self._name(node.func.value) == "object" and node.func.attr == "__getattribute__":
            is_object_getattribute = True
        elif isinstance(node.func, ast.Name) and node.func.id in getattr(self, "object_getattribute_aliases", ()):
            is_object_getattribute = True
        elif isinstance(node.func, ast.Call) and self._name(node.func.func) == "getattr" and len(node.func.args) >= 2:
            g_attr = self._resolve_str_constant(node.func.args[1])
            if self._name(node.func.args[0]) == "object" and g_attr == "__getattribute__":
                is_object_getattribute = True

        if is_object_getattribute and len(node.args) >= 2 and self.filename != "src/test/support/python/repomap_test_support/sqlite_managed_child.py":
            attr_name = self._resolve_str_constant(node.args[1])
            if attr_name in {"_ManagedChild__process", "__process", "_abrupt"}:
                self.bypasses.append(f"{self.filename}:{node.lineno}: object.__getattribute__ bypass")
            elif attr_name is None and self._is_managed_child_expr(node.args[0]):
                self.bypasses.append(f"{self.filename}:{node.lineno}: object.__getattribute__ bypass")

        # Check slot descriptor bypasses (__set__, __get__, __delete__)
        if self.filename != "src/test/support/python/repomap_test_support/sqlite_managed_child.py":
            slot_name = None
            is_desc_call = False
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"__set__", "__get__", "__delete__"}:
                slot_name = self._resolve_descriptor_slot(node.func.value)
                if slot_name is not None:
                    is_desc_call = True
                elif node.args and self._is_managed_child_expr(node.args[0]):
                    is_desc_call = True
                    slot_name = "<unresolved>"
            elif isinstance(node.func, ast.Call) and self._name(node.func.func) == "getattr" and len(node.func.args) >= 2:
                m_name = self._resolve_str_constant(node.func.args[1])
                if m_name in {"__set__", "__get__", "__delete__"}:
                    slot_name = self._resolve_descriptor_slot(node.func.args[0])
                    if slot_name is not None:
                        is_desc_call = True
                    elif node.args and self._is_managed_child_expr(node.args[0]):
                        is_desc_call = True
                        slot_name = "<unresolved>"
            elif isinstance(node.func, (ast.Name, ast.Attribute)):
                func_key = self._expr_key(node.func)
                if func_key and func_key in getattr(self, "descriptor_method_aliases", ()):
                    slot_name, _ = self.descriptor_method_aliases[func_key]
                    is_desc_call = True

            if is_desc_call and (
                slot_name in {"_abrupt", "abrupt", "_ManagedChild__process", "__process", "<unresolved>"}
                or (node.args and self._is_managed_child_expr(node.args[0]))
            ):
                self.bypasses.append(f"{self.filename}:{node.lineno}: descriptor bypass")

