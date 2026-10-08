"""Structured invocation and job-order contracts for release qualification."""
from __future__ import annotations

from pathlib import PurePosixPath
import ast
import re

from ci.qualification_shell_syntax import (
    parse_shell_script,
    ShellWord,
    validate_var_path_expansion,
    validate_command_option_cmd_sub,
    validate_command_option_var_expansion,
    validate_key_value_cmd_sub,
    validate_key_value_var_expansion,
)
from ci.workflow_model import Workflow


def _extract_commands_from_script(script: str) -> list[list[str]]:
    """Preserve quoted multiline arguments and actual shell list boundaries."""
    return parse_shell_script(script)


def _runner_arguments(command: list[str]) -> list[str] | None:
    tokens = list(command)
    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=.*", tokens[0]):
        tokens.pop(0)
    if (len(tokens) >= 2 and PurePosixPath(tokens[0]).name in {"python", "python3"}
            and tokens[1] in {"tools/run_tests.py", "./tools/run_tests.py"}):
        return tokens[2:]
    return None


def _option_values(arguments: list[str], flag: str) -> list[str | None]:
    values: list[str | None] = []
    for index, token in enumerate(arguments):
        if token == flag:
            following = arguments[index + 1] if index + 1 < len(arguments) else None
            values.append(following if following and not following.startswith("--") else None)
        elif token.startswith(flag + "="):
            values.append(token[len(flag) + 1:] or None)
    return values


def _is_staging_runner(command: list[str]) -> bool:
    arguments = _runner_arguments(command)
    return arguments is not None and "staging" in _option_values(arguments, "--suite")


def _job_runners(workflow: Workflow, job_name: str) -> list[list[str]]:
    runners: list[list[str]] = []
    for script in workflow.job_run_commands(job_name):
        for command in _extract_commands_from_script(script):
            arguments = _runner_arguments(command)
            if arguments is not None:
                runners.append(arguments)
    return runners


def _validate_staging_runner_tokens(workflow: Workflow, job_name: str) -> list[str]:
    prefix = f"{workflow.path.name}: "
    if job_name not in workflow.jobs:
        return [prefix + f"{job_name} job is missing"]
    try:
        runners = _job_runners(workflow, job_name)
        violations = [prefix + f"cross-job leakage: staging runner found in {name}"
                      for name in workflow.jobs if name != job_name
                      if any("staging" in _option_values(args, "--suite") for args in _job_runners(workflow, name))]
    except ValueError:
        return [prefix + "qualification shell command cannot be parsed"]
    if len(runners) != 1:
        label = "duplicate staging runner" if len(runners) > 1 else "must find exactly one staging runner"
        return violations + [prefix + f"{label} in {job_name}; found {len(runners)}"]
    arguments = runners[0]
    if "--" in arguments:
        return violations + [prefix + "staging qualification flags must precede end of options"]
    for flag, value in {"--suite": "staging", "--hygiene-profile": "exhaustive",
                        "--declared-complete-gates": "1", "--pg-container-port": "55433"}.items():
        if _option_values(arguments, flag) != [value]:
            violations.append(prefix + f"staging runner missing required flag {flag} {value} exactly once")
    for flag in ("--operator-attest-exclusive", "--operator-attest-pressure-degradation", "--sandbox", "--report"):
        if arguments.count(flag) != 1 or any(token.startswith(flag + "=") for token in arguments):
            violations.append(prefix + f"staging runner missing exact {flag} flag exactly once")
    directories = _option_values(arguments, "--report-dir")
    if len(directories) != 1 or directories[0] is None:
        violations.append(prefix + "staging runner missing exact --report-dir flag and nonempty value")
    return violations


def _validate_downstream_dependencies(workflow: Workflow) -> list[str]:
    jobs = ("pre-review-static", "unit-tests", "staging-integration-gate", "main-system-gate",
            *[name for name in workflow.jobs if "codeql" in name.lower() or "sbom" in name.lower()])
    violations: list[str] = []
    for name in jobs:
        if name in workflow.jobs:
            needs = workflow.jobs[name].get("needs")
            if needs != ["source-and-export-policy"]:
                violations.append(f"{workflow.path.name}: {name} needs must be [source-and-export-policy]")
    return violations


_BOUND_REVISIONS = {
    "CANDIDATE_SHA": "HEAD", "CANDIDATE_TREE": "HEAD^{tree}",
    "CANDIDATE_BASE_PARENT": "HEAD^1", "CANDIDATE_HEAD_PARENT": "HEAD^2",
}


def _environment_reference(node: ast.AST | None, name: str) -> bool:
    return (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"
            and node.value.attr == "environ" and isinstance(node.slice, ast.Constant)
            and node.slice.value == name)


def _bound_request(command: list[str]) -> bool:
    """Validate executable Python request construction, excluding comments/text."""
    if len(command) != 3 or command[:2] != ["python3", "-c"]:
        return False
    code = command[2]
    if not isinstance(code, ShellWord):
        return False
    expanded = [part.text for part in code.parts if part.kind == "param_expansion"]
    if expanded != ["${RUNNER_TEMP}"] or any(
        part.kind not in {"double_quoted_text", "param_expansion"} for part in code.parts
    ):
        return False
    try:
        module = ast.parse(command[2])
    except (SyntaxError, ValueError):
        return False
    requests = [node for node in module.body if isinstance(node, ast.Assign)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "req"]
    if len(requests) != 1 or not isinstance(requests[0].value, ast.Dict):
        return False
    request_index = module.body.index(requests[0])
    if any(not isinstance(node, ast.Import) or any(
        alias.name not in {"json", "os", "sys"} or alias.asname is not None for alias in node.names
    ) for node in module.body[:request_index]):
        return False
    if len(module.body[request_index + 1:]) != 1:
        return False
    values = {key.value: value for key, value in zip(requests[0].value.keys, requests[0].value.values)
              if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    for key, literal in (("schema", "repomap-ci-gate-request-v1"), ("gate_kind", "main-system")):
        value = values.get(key)
        if not isinstance(value, ast.Constant) or value.value != literal:
            return False
    if not all(_environment_reference(values.get(key), name) for key, name in (
        ("base_sha", "CANDIDATE_BASE_PARENT"), ("head_sha", "CANDIDATE_HEAD_PARENT"),
    )):
        return False
    # Only a top-level write after construction supplies the runner's request.
    for node in module.body[request_index + 1:]:
        if not isinstance(node, ast.With) or len(node.items) != 1 or len(node.body) != 1:
            continue
        item = node.items[0]
        call = item.context_expr
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                or call.func.id != "open" or len(call.args) < 2
                or not isinstance(call.args[0], ast.Constant)
                or call.args[0].value != "${RUNNER_TEMP}/gate-request.json"
                or not isinstance(call.args[1], ast.Constant) or call.args[1].value != "w"
                or not isinstance(item.optional_vars, ast.Name)):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                continue
            dump = statement.value
            if (isinstance(dump.func, ast.Attribute) and isinstance(dump.func.value, ast.Name)
                    and dump.func.value.id == "json" and dump.func.attr == "dump"
                    and len(dump.args) >= 2 and isinstance(dump.args[0], ast.Name)
                    and dump.args[0].id == "req" and isinstance(dump.args[1], ast.Name)
                    and dump.args[1].id == item.optional_vars.id):
                return True
    return False


def _main_system_binding(script: str) -> bool:
    """Accept the maintained straight-line binding grammar, fail closed otherwise."""
    commands = _extract_commands_from_script(script)
    assigned: set[str] = set()
    exported: set[str] = set()
    persisted: set[str] = set()
    group: set[str] | None = None
    for command in commands:
        if not command:
            continue
        joined = " ".join(command)
        name = joined.split("=", 1)[0]
        if name in _BOUND_REVISIONS:
            if (len(command) != 1 or name in assigned
                    or not isinstance(command[0], ShellWord) or not command[0].raw.startswith(name + "=")
                    or not validate_key_value_cmd_sub(command[0], name, ["git", "rev-parse", _BOUND_REVISIONS[name]])):
                return False
            assigned.add(name)
        elif command[0].split("=", 1)[0] in _BOUND_REVISIONS:
            return False
        elif command[0] == "export":
            if not set(command[1:]) <= assigned:
                return False
            exported.update(command[1:])
        elif command == ["{"] and isinstance(command[0], ShellWord) and command[0].raw == "{" and group is None:
            group = set()
        elif (_environment_redirect(command) and group is not None):
            persisted.update(group)
            group = None
        elif command[0] == "echo":
            if len(command) != 2 or group is None or getattr(command[0], "has_single_quotes", lambda: False)():
                return False
            name = str(command[1]).split("=", 1)[0]
            if name not in assigned or not validate_key_value_var_expansion(command[1], name, name):
                return False
            group.add(name)
        elif command == ["mkdir", "-p", "${RUNNER_TEMP}/ci"]:
            if assigned != set(_BOUND_REVISIONS) or exported != assigned or persisted != assigned:
                return False
        elif _bound_request(command):
            return (group is None and assigned == set(_BOUND_REVISIONS)
                    and exported == assigned and persisted == assigned
                    and command is commands[-1])
        else:
            return False
    return False



def _environment_redirect(command: list[str]) -> bool:
    return (len(command) == 3 and command[:2] == ["}", ">>"]
            and all(isinstance(word, ShellWord) and word.raw == expected
                    for word, expected in zip(command[:2], ("}", ">>")))
            and validate_var_path_expansion(command[2], "GITHUB_ENV", ""))


def _expanded_path_option(arguments: list[str], flag: str, variable: str, suffix: str) -> bool:
    values = _option_values(arguments, flag)
    return len(values) == 1 and values[0] is not None and validate_var_path_expansion(values[0], variable, suffix)

def _private_main_system_binding(script: str) -> bool:
    """Preserve the private trusted verifier's distinct command contract."""
    commands = _extract_commands_from_script(script)
    if (len(commands) != 7 or commands[0] != ["{"]
            or not isinstance(commands[0][0], ShellWord) or commands[0][0].raw != "{"
            or not _environment_redirect(commands[5])):
        return False
    for command, (name, revision) in zip(commands[1:5], _BOUND_REVISIONS.items()):
        if len(command) != 2 or command[0] != "echo" or getattr(command[0], "has_single_quotes", lambda: False)():
            return False
        if not validate_key_value_cmd_sub(command[1], name, ["git", "rev-parse", revision]):
            return False
    verify = commands[-1]
    if verify[:5] != ["python3", "-S", "-E", "${RUNNER_TEMP}/gate_contract.py", "verify"]:
        return False
    if not validate_var_path_expansion(verify[3], "RUNNER_TEMP", "/gate_contract.py"):
        return False
    flags = ("--candidate-sha", "--candidate-tree", "--candidate-base-parent", "--candidate-head-parent")
    if not _expanded_path_option(verify[5:], "--request-json", "RUNNER_TEMP", "/gate-request.json"):
        return False
    for flag, revision in zip(flags, _BOUND_REVISIONS.values()):
        if not validate_command_option_cmd_sub(verify[5:], flag, ["git", "rev-parse", revision]):
            return False
    return True


def _validate_main_system_gate_ordering(workflow: Workflow, job_name: str = "main-system-gate") -> list[str]:
    prefix = f"{workflow.path.name}: {job_name} "
    if job_name not in workflow.jobs:
        return [prefix + "job is missing"]
    steps = workflow.job_steps(job_name)
    bindings: list[int] = []
    setups = [index for index, step in enumerate(steps)
              if str(step.get("uses", "")).startswith("actions/setup-python@")]
    runners: list[int] = []
    try:
        for index, step in enumerate(steps):
            binding = _private_main_system_binding if job_name == "repomap-main-system-gate" else _main_system_binding
            if binding(str(step.get("run", ""))):
                bindings.append(index)
            for command in _extract_commands_from_script(str(step.get("run", ""))):
                arguments = _runner_arguments(command)
                if arguments is not None and _option_values(arguments, "--suite") == ["system"]:
                    runners.append(index)
    except ValueError:
        return [prefix + "qualification shell command cannot be parsed"]
    for values, label in ((bindings, "merge-parent/candidate binding"), (setups, "setup-python"), (runners, "system runner")):
        if len(values) != 1:
            return [prefix + f"requires exactly one {label}; found {len(values)}"]
    if not bindings[0] < setups[0] < runners[0]:
        return [prefix + "candidate binding must precede setup-python which must precede execution"]
    for step in steps[:bindings[0]] if job_name == "main-system-gate" else ():
        if step.get("run") or (step.get("uses") and not str(step["uses"]).startswith("actions/checkout@")):
            return [prefix + "candidate binding must precede expensive setup commands"]
    runner_commands = _job_runners(workflow, job_name)
    system_arguments = next(args for args in runner_commands if _option_values(args, "--suite") == ["system"])
    for flag, name in (("--candidate-sha", "CANDIDATE_SHA"), ("--candidate-tree", "CANDIDATE_TREE"),
                       ("--candidate-base-parent", "CANDIDATE_BASE_PARENT"), ("--candidate-head-parent", "CANDIDATE_HEAD_PARENT")):
        if not validate_command_option_var_expansion(system_arguments, flag, name):
            return [prefix + "system request must consume bound " + name]
    if not _expanded_path_option(system_arguments, "--gate-request-json", "RUNNER_TEMP", "/gate-request.json"):
        return [prefix + "system runner must consume the constructed request"]
    return []
