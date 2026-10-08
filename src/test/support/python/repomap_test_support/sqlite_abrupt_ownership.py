"""R4-4 omission-proof abrupt termination ownership scanner for whole maintained scope.

Scans test files across the maintained test and test support directories to relate
process aliases to guard/holder launchers, verify that intentional kills are centralized
in maintained abrupt helpers, detect explicit abrupt=False, and forbid direct kill,
send_signal(SIGKILL), os.kill/killpg, or reflection bypasses (object.__setattr__,
object.__getattribute__) outside central helpers without false-positive rejections
on unrelated process cleanups.

Maintained-source enforced; does not claim unbypassable Python runtime reflection.
"""

from __future__ import annotations

import ast
from pathlib import Path

from repomap_test_support.sqlite_abrupt_symbols import AbruptSymbols

MAINTAINED_DIRS = ("src/test",)

CENTRAL_ABRUPT_HELPERS = frozenset({"kill_paused_child", "kill_holder"})
GUARD_LAUNCHERS = frozenset({"start_holder", "start"})
CENTRAL_HELPER_OWNERS = {
    "src/test/support/python/repomap_test_support/sqlite_local_harness.py": "kill_paused_child",
    "src/test/support/python/repomap_test_support/sqlite_local_lock_children.py": "kill_holder",
    "src/test/support/python/repomap_test_support/sqlite_managed_child.py": "kill_abruptly",
}

class AbruptOwnershipVisitor(AbruptSymbols):
    """AST visitor that detects abrupt launch sites, central kills, and bypass patterns."""

    def __init__(
        self,
        filename: str,
        global_guard_returning_functions: dict[str, bool] | None = None,
        global_guard_tuple_returning_functions: dict[str, bool] | None = None,
    ) -> None:
        self.filename = filename
        self.in_finally = False
        self.current_function: str | None = None
        self.intentional_kills: list[tuple[str, str, int]] = []
        self.abrupt_launches: list[tuple[str, str, int]] = []
        self.bypasses: list[str] = []

        # Scoped state
        self.guard_processes: set[str] = set()
        self.guard_containers: set[str] = set()
        self.guard_kill_methods: dict[str, str] = {}
        self.pid_aliases: set[str] = set()
        self.signal_aliases: set[str] = set()
        self.unrelated_processes: set[str] = set()
        self.launch_contracts: dict[str, bool] = {}
        self.function_aliases: dict[str, str] = {}
        self.harness_instances: set[str] = set()
        self.abrupt_envs: set[str] = set()
        self.guard_path_vars: set[str] = set()
        self.guard_command_vars: set[str] = set()
        self.object_setattr_aliases: set[str] = set()
        self.object_getattribute_aliases: set[str] = set()
        self.string_constants: dict[str, str] = {}
        self.managed_child_classes: set[str] = {"ManagedChild", "ManagedChildProcess"}
        self.managed_child_instances: set[str] = set()
        self.descriptor_aliases: dict[str, str] = {}
        self.descriptor_method_aliases: dict[str, tuple[str, str]] = {}

        # Inter-procedural / module level
        self._prescanned = False
        self.guard_returning_functions: dict[str, bool] = {}
        self.guard_tuple_returning_functions: dict[str, bool] = {}
        self.global_guard_returning_functions: dict[str, bool] = dict(global_guard_returning_functions or {})
        self.global_guard_tuple_returning_functions: dict[str, bool] = dict(global_guard_tuple_returning_functions or {})

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Module) and not self._prescanned:
            self._prescan(node)
        super().visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and (node.module.endswith(("sqlite_local_harness", "sqlite_local_lock_children", "sqlite_managed_child")) or node.module in {"signal", "os"}):
            self.function_aliases.update({item.asname or item.name: item.name for item in node.names})

    def visit_Import(self, node: ast.Import) -> None:
        self.function_aliases.update({item.asname or item.name: item.name for item in node.names})

    def _opted(self, call: ast.Call) -> bool:
        func_name = self._name(call.func)
        if func_name in {"paused_env", "start_holder"}:
            return any(
                kw.arg == "abrupt" and not (isinstance(kw.value, ast.Constant) and not kw.value.value)
                for kw in call.keywords
            )
        return any(
            kw.arg == "extra_env" and (
                (isinstance(kw.value, ast.Call) and self._opted(kw.value))
                or (isinstance(kw.value, ast.Name) and kw.value.id in self.abrupt_envs)
            ) for kw in call.keywords
        )

    def visit_Try(self, node: ast.Try) -> None:
        for s in [*node.body, *node.handlers, *node.orelse]:
            self.visit(s)
        old, self.in_finally = self.in_finally, True
        for s in node.finalbody:
            self.visit(s)
        self.in_finally = old

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        names = (
            "guard_processes", "guard_containers", "guard_kill_methods", "pid_aliases", "signal_aliases",
            "unrelated_processes", "launch_contracts", "function_aliases",
            "harness_instances", "abrupt_envs", "guard_path_vars", "guard_command_vars",
            "object_setattr_aliases", "object_getattribute_aliases",
            "string_constants", "managed_child_classes", "managed_child_instances",
            "descriptor_aliases", "descriptor_method_aliases",
        )
        previous = {name: getattr(self, name).copy() for name in names}
        old_function = self.current_function
        self.current_function = node.name

        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            # Parameters shadow module constants; unknown names must stay unknown.
            self.string_constants.pop(arg.arg, None)
            if arg.annotation is not None and self._name(arg.annotation) in {"ManagedChild", "ManagedChildProcess"}:
                self.managed_child_instances.add(arg.arg)
            if arg.arg in {"child", "managed_child", "managed_proc"}:
                self.managed_child_instances.add(arg.arg)
            if arg.annotation is not None and self._name(arg.annotation) == "LocalHarness":
                self.harness_instances.add(arg.arg)
            if arg.arg in {"harness", "local_harness", "rig"}:
                self.harness_instances.add(arg.arg)
            if arg.arg in self.guard_returning_functions:
                self.guard_processes.add(arg.arg)
                self.launch_contracts[arg.arg] = self.guard_returning_functions[arg.arg]
            elif arg.arg in self.global_guard_returning_functions:
                self.guard_processes.add(arg.arg)
                self.launch_contracts[arg.arg] = self.global_guard_returning_functions[arg.arg]
            if arg.arg in self.guard_tuple_returning_functions:
                self.guard_containers.add(arg.arg)
                self.launch_contracts[arg.arg] = self.guard_tuple_returning_functions[arg.arg]
            elif arg.arg in self.global_guard_tuple_returning_functions:
                self.guard_containers.add(arg.arg)
                self.launch_contracts[arg.arg] = self.global_guard_tuple_returning_functions[arg.arg]

        try:
            self.generic_visit(node)
        finally:
            self.current_function = old_function
            for name, value in previous.items():
                setattr(self, name, value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_With(self, node: ast.With) -> None:
        self._record_with(node)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._record_with(node)
        self.generic_visit(node)

    def _record_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                is_guard, is_abrupt, is_tuple = self._check_launch(item.context_expr)
                if is_guard and item.optional_vars is not None:
                    if is_tuple and isinstance(item.optional_vars, (ast.Tuple, ast.List)) and item.optional_vars.elts:
                        first_key = self._expr_key(item.optional_vars.elts[0])
                        if first_key:
                            self.guard_processes.add(first_key)
                            self.launch_contracts[first_key] = is_abrupt
                    else:
                        opt_key = self._expr_key(item.optional_vars)
                        if opt_key:
                            self.guard_processes.add(opt_key)
                            self.launch_contracts[opt_key] = is_abrupt

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_assignment(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_assignment(ast.Assign(targets=[node.target], value=node.value))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "_ManagedChild__process" and self.filename != "src/test/support/python/repomap_test_support/sqlite_managed_child.py":
            self.bypasses.append(f"{self.filename}:{node.lineno}: private managed process bypass")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_reflection_call(node)

        name = self._name(node.func)
        if name in CENTRAL_ABRUPT_HELPERS and not self.in_finally:
            self.intentional_kills.append((self.filename, name, node.lineno))
            process = node.args[0] if node.args else None
            if process is not None:
                p_key = self._expr_key(process)
                is_guard = self._is_guard_expr(process) or (p_key in self.guard_processes if p_key else False)
                has_contract = self.launch_contracts.get(p_key, False) if p_key else False
                if is_guard and not has_contract:
                    self.bypasses.append(f"{self.filename}:{node.lineno}: intentional abrupt helper requires abrupt=True launcher contract")
        elif name in {"paused_env", "start_holder"}:
            for kw in node.keywords:
                if kw.arg == "abrupt":
                    if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        self.bypasses.append(f"{self.filename}:{node.lineno}: explicit abrupt=False")
                    else:
                        self.abrupt_launches.append((self.filename, name, node.lineno))

        is_inside_central_helper = any(
            self.filename == path
            and self.current_function == fn
            for path, fn in CENTRAL_HELPER_OWNERS.items()
        )

        pid_arg = (
            node.args[0]
            if len(node.args) >= 1
            else next((kw.value for kw in node.keywords if kw.arg in ("pid", "pgid")), None)
        )
        sig_arg = (
            node.args[1]
            if len(node.args) >= 2
            else next((kw.value for kw in node.keywords if kw.arg in ("sig", "signal")), None)
        )

        if not is_inside_central_helper:
            # Check direct name calls: from os import kill; kill(pid, SIGKILL)
            if isinstance(node.func, ast.Name):
                func_name = self._name(node.func)
                if func_name in {"kill", "killpg"}:
                    if sig_arg and self._is_sigkill(sig_arg):
                        if pid_arg and (self._is_guard_pid_expr(pid_arg) or self._is_guard_expr(pid_arg)):
                            self.bypasses.append(f"{self.filename}:{node.lineno}: direct os.{func_name} bypass")
                elif node.func.id in self.guard_kill_methods:
                    method_name = self.guard_kill_methods[node.func.id]
                    if method_name == "kill":
                        self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{node.func.id}() bypass")
                    elif method_name == "send_signal" and (not node.args or self._is_sigkill(node.args[0])):
                        self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{node.func.id}() bypass")

            # Check getattr calls: getattr(os, "kill")(pid, SIGKILL) or getattr(proc, "kill")()
            elif isinstance(node.func, ast.Call):
                g_func = getattr(node.func.func, "id", None)
                if g_func == "getattr" and len(node.func.args) >= 2:
                    target_obj = node.func.args[0]
                    attr_name = (
                        node.func.args[1].value
                        if isinstance(node.func.args[1], ast.Constant)
                        else None
                    )
                    target_name = self._name(target_obj)
                    if target_name in {"os", "operating"} and attr_name in {"kill", "killpg"}:
                        if sig_arg and self._is_sigkill(sig_arg):
                            if pid_arg and (self._is_guard_pid_expr(pid_arg) or self._is_guard_expr(pid_arg)):
                                self.bypasses.append(f"{self.filename}:{node.lineno}: direct os.{attr_name} bypass")
                    elif attr_name == "kill" and self._is_guard_expr(target_obj):
                        tgt = self._expr_key(target_obj) or "target"
                        self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{tgt}.kill() bypass")
                    elif attr_name == "send_signal" and node.args and self._is_sigkill(node.args[0]):
                        if self._is_guard_expr(target_obj):
                            tgt = self._expr_key(target_obj) or "target"
                            self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{tgt}.send_signal() bypass")

            # Check attribute calls: os.kill, proc.kill, wrapper.child.kill(), etc.
            elif isinstance(node.func, ast.Attribute):
                caller_name = getattr(node.func.value, "id", "")
                resolved_caller = self.function_aliases.get(caller_name, caller_name)
                attr = node.func.attr

                if resolved_caller in {"os", "operating"} and attr in {"kill", "killpg"}:
                    if sig_arg and self._is_sigkill(sig_arg):
                        if pid_arg and (self._is_guard_pid_expr(pid_arg) or self._is_guard_expr(pid_arg)):
                            self.bypasses.append(f"{self.filename}:{node.lineno}: direct os.{attr} bypass")
                elif resolved_caller not in {"os", "operating"}:
                    if attr == "kill" and self._is_guard_expr(node.func.value):
                        tgt = self._expr_key(node.func.value) or "target"
                        self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{tgt}.kill() bypass")
                    elif attr == "send_signal" and node.args and self._is_sigkill(node.args[0]):
                        if self._is_guard_expr(node.func.value):
                            tgt = self._expr_key(node.func.value) or "target"
                            self.bypasses.append(f"{self.filename}:{node.lineno}: direct .{tgt}.send_signal() bypass")

        self.generic_visit(node)

# Backward compatibility alias
AbruptKillCensusVisitor = AbruptOwnershipVisitor

def scan_file_abrupt_ownership(path: Path | str) -> AbruptOwnershipVisitor:
    """Parse and scan a Python source file for abrupt termination ownership."""
    file_path = Path(path)
    visitor = AbruptOwnershipVisitor(file_path.name)
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(file_path))
    visitor.visit(tree)
    return visitor

def scan_maintained_scope(repo_root: Path | str) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]], list[str]]:
    """Scan the entire maintained test/support scope for abrupt launches, kills, and bypasses."""
    root = Path(repo_root)
    kills: list[tuple[str, str, int]] = []
    launches: list[tuple[str, str, int]] = []
    bypasses: list[str] = []

    global_guard_returning_functions: dict[str, bool] = {}
    global_guard_tuple_returning_functions: dict[str, bool] = {}
    parsed_files: list[tuple[str, ast.Module]] = []

    for rel_dir in MAINTAINED_DIRS:
        target_dir = root / rel_dir
        if not target_dir.is_dir():
            continue
        for path in sorted(target_dir.rglob("*.py")):
            if path.relative_to(root / "src/test").parts[0] == "fixtures":
                continue
            rel_name = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            parsed_files.append((rel_name, tree))
            prescanner = AbruptSymbols()
            prescanner.guard_returning_functions = {}
            prescanner.guard_tuple_returning_functions = {}
            prescanner.global_guard_returning_functions = {}
            prescanner.global_guard_tuple_returning_functions = {}
            prescanner.guard_processes = set()
            prescanner.guard_containers = set()
            prescanner.guard_kill_methods = {}
            prescanner.pid_aliases = set()
            prescanner.signal_aliases = set()
            prescanner.unrelated_processes = set()
            prescanner.launch_contracts = {}
            prescanner.function_aliases = {}
            prescanner.harness_instances = set()
            prescanner.abrupt_envs = set()
            prescanner.guard_path_vars = set()
            prescanner.guard_command_vars = set()
            prescanner.object_setattr_aliases = set()
            prescanner.object_getattribute_aliases = set()
            prescanner.string_constants = {}
            prescanner.managed_child_classes = {"ManagedChild", "ManagedChildProcess"}
            prescanner.managed_child_instances = set()
            prescanner.descriptor_aliases = {}
            prescanner.descriptor_method_aliases = {}
            prescanner._prescan(tree)
            global_guard_returning_functions.update(prescanner.guard_returning_functions)
            global_guard_tuple_returning_functions.update(prescanner.guard_tuple_returning_functions)

    for rel_name, tree in parsed_files:
        visitor = AbruptOwnershipVisitor(
            rel_name,
            global_guard_returning_functions=global_guard_returning_functions,
            global_guard_tuple_returning_functions=global_guard_tuple_returning_functions,
        )
        visitor.visit(tree)
        kills.extend(visitor.intentional_kills)
        launches.extend(visitor.abrupt_launches)
        bypasses.extend(visitor.bypasses)

    return kills, launches, bypasses

__all__ = (
    "AbruptKillCensusVisitor",
    "AbruptOwnershipVisitor",
    "CENTRAL_ABRUPT_HELPERS",
    "GUARD_LAUNCHERS",
    "MAINTAINED_DIRS",
    "scan_file_abrupt_ownership",
    "scan_maintained_scope",
)
