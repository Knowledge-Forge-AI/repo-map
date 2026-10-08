"""Symbol propagation for the SQLite managed-child source ownership check."""
from __future__ import annotations

import ast

from repomap_test_support.sqlite_abrupt_reflection import AbruptReflection


class AbruptSymbols(AbruptReflection, ast.NodeVisitor):
    _prescanned: bool
    guard_returning_functions: dict[str, bool]
    guard_tuple_returning_functions: dict[str, bool]
    global_guard_returning_functions: dict[str, bool]
    global_guard_tuple_returning_functions: dict[str, bool]
    guard_processes: set[str]
    guard_containers: set[str]
    guard_kill_methods: dict[str, str]
    pid_aliases: set[str]
    signal_aliases: set[str]
    unrelated_processes: set[str]
    launch_contracts: dict[str, bool]
    function_aliases: dict[str, str]
    harness_instances: set[str]
    abrupt_envs: set[str]
    guard_path_vars: set[str]
    guard_command_vars: set[str]
    object_setattr_aliases: set[str]
    object_getattribute_aliases: set[str]

    def _opted(self, call: ast.Call) -> bool:
        func_name = self._name(call.func)
        if func_name in {"paused_env", "start_holder"}:
            return any(
                kw.arg == "abrupt" and not (isinstance(kw.value, ast.Constant) and not kw.value.value)
                for kw in call.keywords)
        return any(
            kw.arg == "extra_env" and (
                (isinstance(kw.value, ast.Call) and self._opted(kw.value))
                or (isinstance(kw.value, ast.Name) and kw.value.id in getattr(self, "abrupt_envs", ()))
            ) for kw in call.keywords
        )

    def _is_sigkill(self, sig: ast.expr) -> bool:
        if isinstance(sig, ast.Constant):
            return sig.value in (9, "SIGKILL")
        name = self._name(sig)
        if name in {"SIGKILL", "SIG_KILL"}:
            return True
        key = self._expr_key(sig)
        if key and key in getattr(self, "signal_aliases", ()):
            return True
        if isinstance(sig, ast.Attribute):
            if sig.attr in {"SIGKILL", "SIG_KILL"}:
                return True
            if sig.attr == "value" and self._is_sigkill(sig.value):
                return True
        if isinstance(sig, ast.Call):
            func_name = self._name(sig.func)
            if func_name in {"int", "Signals", "SIGKILL"}:
                return any(self._is_sigkill(arg) for arg in sig.args)
        return False

    def _prescan(self, tree: ast.Module) -> None:
        self._prescanned = True
        self.object_setattr_aliases = getattr(self, "object_setattr_aliases", set())
        self.object_getattribute_aliases = getattr(self, "object_getattribute_aliases", set())
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.visit(node)
            elif isinstance(node, ast.Assign):
                self._record_assignment(node)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self._record_assignment(ast.Assign(targets=[node.target], value=node.value))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_function_return(node)

    def _analyze_function_return(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        local_guards: dict[str, bool] = {}
        local_tuples: dict[str, bool] = {}
        local_harness: set[str] = set()
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.annotation and self._name(arg.annotation) == "LocalHarness":
                local_harness.add(arg.arg)
            if arg.arg in {"harness", "local_harness", "rig"}:
                local_harness.add(arg.arg)

        val: ast.expr | None
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                val = stmt.value
                if isinstance(val, ast.Call):
                    is_guard, is_abrupt, is_tuple = self._check_launch(val, local_harness)
                    if is_guard:
                        for target in stmt.targets:
                            key = self._expr_key(target)
                            if key:
                                if is_tuple:
                                    local_tuples[key] = is_abrupt
                                else:
                                    local_guards[key] = is_abrupt
            elif isinstance(stmt, (ast.Return, ast.Yield)):
                val = stmt.value
                if val is not None:
                    if isinstance(val, ast.Call):
                        is_guard, is_abrupt, is_tuple = self._check_launch(val, local_harness)
                        if is_guard:
                            if is_tuple:
                                self.guard_tuple_returning_functions[node.name] = is_abrupt
                            else:
                                self.guard_returning_functions[node.name] = is_abrupt
                    elif isinstance(val, ast.Name):
                        if val.id in local_tuples:
                            self.guard_tuple_returning_functions[node.name] = local_tuples[val.id]
                        elif val.id in local_guards:
                            self.guard_returning_functions[node.name] = local_guards[val.id]
                    elif isinstance(val, (ast.Tuple, ast.List)) and val.elts:
                        first = val.elts[0]
                        if isinstance(first, ast.Name):
                            if first.id in local_guards:
                                self.guard_tuple_returning_functions[node.name] = local_guards[first.id]
                        elif isinstance(first, ast.Call):
                            is_guard, is_abrupt, _ = self._check_launch(first, local_harness)
                            if is_guard:
                                self.guard_tuple_returning_functions[node.name] = is_abrupt

    def _check_launch(self, call: ast.Call, local_harness: set[str] | None = None) -> tuple[bool, bool, bool]:
        func_name = self._name(call.func)
        if func_name == "start_holder":
            return True, self._opted(call), True
        if func_name in self.guard_tuple_returning_functions:
            return True, self.guard_tuple_returning_functions[func_name], True
        if func_name in self.guard_returning_functions:
            return True, self.guard_returning_functions[func_name], False
        if getattr(self, "global_guard_tuple_returning_functions", None) and func_name in self.global_guard_tuple_returning_functions:
            return True, self.global_guard_tuple_returning_functions[func_name], True
        if getattr(self, "global_guard_returning_functions", None) and func_name in self.global_guard_returning_functions:
            return True, self.global_guard_returning_functions[func_name], False

        all_harness = self.harness_instances | (local_harness or set())
        if func_name == "start" and isinstance(call.func, ast.Attribute):
            caller_key = self._expr_key(call.func.value)
            caller_id = getattr(call.func.value, "id", "")
            if (
                caller_key in all_harness
                or caller_id in {"harness", "local_harness", "rig"}
                or (isinstance(call.func.value, ast.Call) and getattr(call.func.value.func, "id", None) == "LocalHarness")
                or any(getattr(kw, "arg", None) == "extra_env" for kw in call.keywords)
            ):
                return True, self._opted(call), False
        if func_name in {"Popen", "run", "launch_observed_process", "popen_observed_process"}:
            if self._guard_command(call):
                return True, self._opted(call), False
        return False, False, False

    def _name(self, function: ast.expr) -> str | None:
        name = getattr(function, "id", None) or getattr(function, "attr", None)
        return self.function_aliases.get(name, name) if isinstance(name, str) else None

    def _expr_key(self, expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            val_key = self._expr_key(expr.value)
            return f"{val_key}.{expr.attr}" if val_key else expr.attr
        if isinstance(expr, ast.Subscript):
            val_key = self._expr_key(expr.value)
            if not val_key:
                return None
            if isinstance(expr.slice, ast.Constant):
                return f"{val_key}[{expr.slice.value!r}]"
            if isinstance(expr.slice, ast.Name):
                return f"{val_key}[{expr.slice.id}]"
            return f"{val_key}[]"
        return None

    def _is_guard_path_expr(self, expr: ast.expr) -> bool:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str) and "sqlite_local_guard.py" in expr.value:
            return True
        if isinstance(expr, ast.Name) and self.function_aliases.get(expr.id, expr.id) in {"HOLD", "HOLD_AND_SPAWN"}:
            return True
        key = self._expr_key(expr)
        if key and key in self.guard_path_vars:
            return True
        for part in ast.walk(expr):
            if isinstance(part, ast.Constant) and isinstance(part.value, str) and "sqlite_local_guard.py" in part.value:
                return True
            if isinstance(part, ast.Attribute) and part.attr == "__file__" and getattr(part.value, "id", None) == "sqlite_local_guard":
                return True
            if isinstance(part, ast.Name) and (part.id in self.guard_path_vars or self.function_aliases.get(part.id, part.id) in {"HOLD", "HOLD_AND_SPAWN"}):
                return True
        return False

    def _guard_command(self, call: ast.Call) -> bool:
        for arg in call.args:
            if self._is_guard_path_expr(arg):
                return True
            key = self._expr_key(arg)
            if key and (key in self.guard_command_vars or key in self.guard_path_vars):
                return True
            if isinstance(arg, (ast.List, ast.Tuple)):
                if any(self._is_guard_path_expr(elt) for elt in arg.elts):
                    return True
        for kw in call.keywords:
            if kw.arg in {"args", "cmd"}:
                if self._is_guard_path_expr(kw.value):
                    return True
                key = self._expr_key(kw.value)
                if key and (key in self.guard_command_vars or key in self.guard_path_vars):
                    return True
        return False

    def _is_guard_expr(self, expr: ast.expr) -> bool:
        key = self._expr_key(expr)
        if key and key in self.guard_processes:
            return True
        if isinstance(expr, ast.Attribute):
            base_key = self._expr_key(expr.value)
            if base_key and (base_key in self.guard_containers or base_key in self.guard_processes):
                return True
            if self._is_guard_expr(expr.value):
                return True
        if isinstance(expr, ast.Subscript):
            base_key = self._expr_key(expr.value)
            if base_key and (base_key in self.guard_containers or base_key in self.guard_processes):
                return True
        if isinstance(expr, ast.Call):
            func_name = self._name(expr.func)
            if func_name == "getattr" and len(expr.args) >= 2:
                return self._is_guard_expr(expr.args[0])
            is_guard, _, _ = self._check_launch(expr)
            if is_guard:
                return True
            if any(self._is_guard_expr(arg) for arg in expr.args) or any(self._is_guard_expr(kw.value) for kw in expr.keywords):
                return True
        return False

    def _is_guard_pid_expr(self, expr: ast.expr) -> bool:
        key = self._expr_key(expr)
        if key and key in self.pid_aliases:
            return True
        if isinstance(expr, ast.Attribute) and expr.attr == "pid":
            return self._is_guard_expr(expr.value)
        if isinstance(expr, ast.Call):
            func_name = self._name(expr.func)
            if func_name == "getattr":
                if len(expr.args) >= 2 and isinstance(expr.args[1], ast.Constant) and expr.args[1].value == "pid":
                    return self._is_guard_expr(expr.args[0])
                return False
            return any(self._is_guard_pid_expr(arg) for arg in expr.args)
        if isinstance(expr, ast.Subscript):
            val_key = self._expr_key(expr.value)
            if val_key and (val_key in self.pid_aliases or val_key in self.guard_containers):
                return True
        if isinstance(expr, ast.UnaryOp):
            return self._is_guard_pid_expr(expr.operand)
        if isinstance(expr, ast.BinOp):
            return self._is_guard_pid_expr(expr.left) or self._is_guard_pid_expr(expr.right)
        for part in ast.walk(expr):
            if part is expr:
                continue
            if isinstance(part, ast.Name) and part.id in self.pid_aliases:
                return True
            if isinstance(part, ast.Attribute) and part.attr == "pid" and self._is_guard_expr(part.value):
                return True
        return False

    def _record_assignment(self, node: ast.Assign) -> None:
        val = node.value
        is_guard = False
        is_holder = False
        is_unrelated = False
        is_abrupt_launch = False

        if self._is_guard_path_expr(val):
            for target in node.targets:
                key = self._expr_key(target)
                if key:
                    self.guard_path_vars.add(key)
        elif isinstance(val, (ast.List, ast.Tuple)) and any(self._is_guard_path_expr(elt) for elt in val.elts):
            for target in node.targets:
                key = self._expr_key(target)
                if key:
                    self.guard_command_vars.add(key)

        if isinstance(val, ast.Call):
            func_name = self._name(val.func)
            for target in node.targets:
                key = self._expr_key(target)
                if key:
                    if func_name == "LocalHarness":
                        self.harness_instances.add(key)
                    if func_name == "paused_env" and self._opted(val):
                        self.abrupt_envs.add(key)

            launch_guard, launch_abrupt, launch_tuple = self._check_launch(val)
            if launch_guard:
                is_abrupt_launch = launch_abrupt
                if launch_tuple:
                    is_holder = True
                else:
                    is_guard = True
            elif func_name in {"Popen", "run", "launch_observed_process", "popen_observed_process"}:
                is_unrelated = True
            elif func_name == "start" and isinstance(val.func, ast.Attribute):
                caller = getattr(val.func.value, "id", "")
                if caller not in self.harness_instances and caller not in {"harness", "local_harness", "rig"}:
                    is_unrelated = True
            elif not is_guard and not is_holder and not is_unrelated:
                if func_name != "getattr" and (any(self._is_guard_expr(arg) for arg in val.args) or any(self._is_guard_expr(kw.value) for kw in val.keywords)):
                    for target in node.targets:
                        target_key = self._expr_key(target)
                        if target_key:
                            self.guard_containers.add(target_key)
                            self.guard_processes.add(target_key)
                            wrapped_child = next((arg for arg in val.args if self._is_guard_expr(arg)), None)
                            wrapped_key = self._expr_key(wrapped_child) if wrapped_child else None
                            self.launch_contracts[target_key] = self.launch_contracts.get(wrapped_key, False) if wrapped_key else False

        self._record_reflection_assignment(node)

        for target in node.targets:
            target_key = self._expr_key(target)
            if is_holder:
                if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
                    first = target.elts[0]
                    first_key = self._expr_key(first)
                    if first_key:
                        self.guard_processes.add(first_key)
                        self.managed_child_instances.add(first_key)
                        self.launch_contracts[first_key] = is_abrupt_launch
                elif target_key:
                    self.guard_containers.add(target_key)
                    self.managed_child_instances.add(target_key)
                    self.launch_contracts[target_key] = is_abrupt_launch
            elif is_guard:
                if target_key:
                    self.guard_processes.add(target_key)
                    self.managed_child_instances.add(target_key)
                    self.launch_contracts[target_key] = is_abrupt_launch
            elif is_unrelated:
                if target_key:
                    self.unrelated_processes.add(target_key)
            else:
                val_key = self._expr_key(val)
                if val_key and val_key in self.guard_processes:
                    if target_key:
                        self.guard_processes.add(target_key)
                        if val_key in self.managed_child_instances:
                            self.managed_child_instances.add(target_key)
                        self.launch_contracts[target_key] = self.launch_contracts.get(val_key, False)
                elif val_key and val_key in self.guard_containers:
                    if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
                        first = target.elts[0]
                        first_key = self._expr_key(first)
                        if first_key:
                            self.guard_processes.add(first_key)
                            self.managed_child_instances.add(first_key)
                            self.launch_contracts[first_key] = self.launch_contracts.get(val_key, False)
                    elif target_key:
                        self.guard_containers.add(target_key)
                        self.managed_child_instances.add(target_key)
                        self.launch_contracts[target_key] = self.launch_contracts.get(val_key, False)
                elif isinstance(val, (ast.List, ast.Tuple)) and any(self._is_guard_expr(elt) for elt in val.elts):
                    if target_key:
                        self.guard_containers.add(target_key)
                elif isinstance(val, ast.Dict) and any(self._is_guard_expr(v) for v in val.values):
                    if target_key:
                        self.guard_containers.add(target_key)
                elif isinstance(val, ast.Subscript):
                    base_key = self._expr_key(val.value)
                    if base_key and (base_key in self.guard_containers or base_key in self.guard_processes):
                        if target_key:
                            self.guard_processes.add(target_key)
                            self.launch_contracts[target_key] = self.launch_contracts.get(base_key, False)
                elif self._is_sigkill(val):
                    if target_key:
                        self.signal_aliases.add(target_key)
                elif self._is_guard_pid_expr(val):
                    if target_key:
                        self.pid_aliases.add(target_key)
                elif val_key and val_key in self.pid_aliases:
                    if target_key:
                        self.pid_aliases.add(target_key)
                elif val_key and val_key in self.unrelated_processes:
                    if target_key:
                        self.unrelated_processes.add(target_key)
                elif isinstance(val, ast.Attribute) and getattr(val.value, "id", "") in {"os", "operating"} and val.attr in {"kill", "killpg"}:
                    if target_key:
                        self.function_aliases[target_key] = val.attr
                elif isinstance(val, ast.Call) and getattr(val.func, "id", None) == "getattr" and len(val.args) >= 2:
                    if getattr(val.args[0], "id", None) in {"os", "operating"} and isinstance(val.args[1], ast.Constant) and val.args[1].value in {"kill", "killpg"}:
                        if target_key:
                            self.function_aliases[target_key] = str(val.args[1].value)
                    elif self._is_guard_expr(val.args[0]) and isinstance(val.args[1], ast.Constant) and val.args[1].value in {"kill", "send_signal"}:
                        if target_key:
                            self.guard_kill_methods[target_key] = str(val.args[1].value)
                elif isinstance(val, ast.Attribute) and val.attr in {"kill", "send_signal"} and self._is_guard_expr(val.value):
                    if target_key:
                        self.guard_kill_methods[target_key] = val.attr
