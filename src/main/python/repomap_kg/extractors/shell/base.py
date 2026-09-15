"""Conservative shell-family raw observation extraction."""

from __future__ import annotations

from dataclasses import dataclass
import posixpath
import re
import shlex

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation


ASSIGNMENT_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ENV_READ_PATTERN = re.compile(
    r"\$(?:"
    r"{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?:[^}]*)}"
    r"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
    r")"
)
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z]+")
CONTROL_WORDS = frozenset(
    {
        "!",
        "[[",
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "select",
        "then",
        "until",
        "while",
        "{",
        "}",
    }
)
SOURCE_COMMANDS = frozenset({"source", "."})
DYNAMIC_SOURCE_CHARS = frozenset("$`*?[")
BREW_MUTATING_VERBS = frozenset(
    {"install", "reinstall", "uninstall", "upgrade", "tap", "untap"}
)
NIX_PROFILE_MUTATING_VERBS = frozenset({"install", "remove", "upgrade"})
LAUNCHCTL_MUTATING_VERBS = frozenset(
    {
        "bootstrap",
        "bootout",
        "disable",
        "enable",
        "kickstart",
        "load",
        "remove",
        "start",
        "stop",
        "unload",
    }
)
FILESYSTEM_MUTATING_TOOLS = frozenset({"cp", "mv", "rm"})
FILESYSTEM_TARGET_DIRECTORY_OPTIONS = frozenset({"-t", "--target-directory"})
SUDO_OPTIONS_WITH_VALUES = frozenset({"-C", "-g", "-h", "-p", "-T", "-u"})


@dataclass(frozen=True)
class HostMutation:
    category: str
    reason: str
    tool: str
    effective_argv: tuple[str, ...]
    privileged: bool


def extract_shell_command_observations(
    path: str, content: str
) -> tuple[RawObservation, ...]:
    return tuple(
        observation
        for observation in extract_shell_observations(path, content)
        if observation.kind == "shell.command"
    )


def extract_shell_observations(path: str, content: str) -> tuple[RawObservation, ...]:
    observations = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = command_line(raw_line)
        if not line:
            continue
        words = command_words(line)
        if not words:
            continue
        observations.extend(
            shell_env_observations(path, line_number, raw_line, line, words)
        )
        argv = command_argv_from_words(words)
        if not argv:
            continue
        if argv[0] in SOURCE_COMMANDS:
            source = shell_source_observation(path, line_number, raw_line, argv)
            if source is not None:
                observations.append(source)
        else:
            observations.append(
                shell_command_observation(path, line_number, raw_line, argv)
            )
            mutation = shell_host_mutation_observation(
                path, line_number, raw_line, argv
            )
            if mutation is not None:
                observations.append(mutation)
    return tuple(observations)


def shell_command_observation(
    path: str, line_number: int, raw_line: str, argv: tuple[str, ...]
) -> RawObservation:
    command = argv[0]
    tool = tool_name(command)
    name = command_display_name(tool, argv)
    return RawObservation(
        kind="shell.command",
        source_id=f"{path}#call:{line_number}:{slug(name)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=f"tool:{tool}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata={
            "argv": list(argv),
            "command": command,
            "raw": raw_line.strip(),
        },
    )


def shell_source_observation(
    path: str, line_number: int, raw_line: str, argv: tuple[str, ...]
) -> RawObservation | None:
    if len(argv) < 2:
        return None
    source_path = argv[1]
    resolved_path = resolve_source_path(path, source_path)
    if resolved_path is None:
        return None
    return RawObservation(
        kind="shell.source",
        source_id=f"{path}#source:{line_number}:{slug(resolved_path)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=source_path,
        target=f"file:{resolved_path}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata={
            "argv": list(argv),
            "source": source_path,
            "resolved_path": resolved_path,
            "raw": raw_line.strip(),
        },
    )


def shell_env_observations(
    path: str,
    line_number: int,
    raw_line: str,
    line: str,
    words: list[str],
) -> tuple[RawObservation, ...]:
    observations = []
    for variable, value, scope in assignment_writes(words):
        observations.append(
            shell_env_observation(
                path,
                line_number,
                raw_line,
                operation="write",
                variable=variable,
                value=value,
                scope=scope,
            )
        )
    for variable in variable_reads(line):
        observations.append(
            shell_env_observation(
                path,
                line_number,
                raw_line,
                operation="read",
                variable=variable,
            )
        )
    return tuple(observations)


def shell_env_observation(
    path: str,
    line_number: int,
    raw_line: str,
    *,
    operation: str,
    variable: str,
    value: str | None = None,
    scope: str | None = None,
) -> RawObservation:
    metadata = {
        "operation": operation,
        "variable": variable,
        "raw": raw_line.strip(),
    }
    if operation == "write":
        metadata["value"] = value or ""
        metadata["scope"] = scope or "shell"
    return RawObservation(
        kind="shell.env",
        source_id=f"{path}#env-{operation}:{line_number}:{slug(variable)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        target=f"env:{variable}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata=metadata,
    )


def shell_host_mutation_observation(
    path: str, line_number: int, raw_line: str, argv: tuple[str, ...]
) -> RawObservation | None:
    mutation = classify_host_mutation(argv)
    if mutation is None:
        return None
    name = host_mutation_name(mutation)
    return RawObservation(
        kind="shell.host_mutation",
        source_id=(
            f"{path}#host-mutation:{line_number}:"
            f"{slug(f'{mutation.category}-{name}')}"
        ),
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=f"host:{mutation.category}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata={
            "argv": list(argv),
            "category": mutation.category,
            "effective_argv": list(mutation.effective_argv),
            "privileged": mutation.privileged,
            "reason": mutation.reason,
            "raw": raw_line.strip(),
            "tool": mutation.tool,
        },
    )


def command_argv(raw_line: str) -> tuple[str, ...]:
    line = command_line(raw_line)
    if not line:
        return ()
    words = command_words(line)
    if not words:
        return ()
    return command_argv_from_words(words)


def command_words(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError:
        return []


def command_argv_from_words(words: list[str]) -> tuple[str, ...]:
    index = first_command_index(words)
    if index is None:
        return ()
    argv = tuple(words[index:])
    if not argv or argv[0] in CONTROL_WORDS:
        return ()
    return argv


def command_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return ""
    return re.sub(r"\s+#.*$", "", line).strip()


def first_command_index(words: list[str]) -> int | None:
    for index, word in enumerate(words):
        if ASSIGNMENT_PATTERN.match(word):
            continue
        if word in CONTROL_WORDS:
            return None
        return index
    return None


def assignment_writes(words: list[str]) -> tuple[tuple[str, str, str], ...]:
    writes = []
    for word in words:
        match = ASSIGNMENT_PATTERN.match(word)
        if match is None:
            break
        writes.append((match.group(1), match.group(2)))
    scope = "shell" if len(writes) == len(words) else "command"
    return tuple((variable, value, scope) for variable, value in writes)


def variable_reads(line: str) -> tuple[str, ...]:
    variables = []
    seen = set()
    for match in ENV_READ_PATTERN.finditer(line):
        variable = match.group("braced") or match.group("bare")
        if variable not in seen:
            variables.append(variable)
            seen.add(variable)
    return tuple(variables)


def classify_host_mutation(argv: tuple[str, ...]) -> HostMutation | None:
    effective_argv, privileged = effective_host_argv(argv)
    if not effective_argv:
        return None
    tool = tool_name(effective_argv[0])
    verb = effective_argv[1] if len(effective_argv) > 1 else ""
    if tool == "brew" and verb in BREW_MUTATING_VERBS:
        return HostMutation(
            category="package-management",
            reason=f"brew {verb}",
            tool=tool,
            effective_argv=effective_argv,
            privileged=privileged,
        )
    if (
        tool == "nix"
        and len(effective_argv) > 2
        and effective_argv[1] == "profile"
        and effective_argv[2] in NIX_PROFILE_MUTATING_VERBS
    ):
        return HostMutation(
            category="package-management",
            reason=f"nix profile {effective_argv[2]}",
            tool=tool,
            effective_argv=effective_argv,
            privileged=privileged,
        )
    if tool == "launchctl" and verb in LAUNCHCTL_MUTATING_VERBS:
        return HostMutation(
            category="service-management",
            reason=f"launchctl {verb}",
            tool=tool,
            effective_argv=effective_argv,
            privileged=privileged,
        )
    if tool == "darwin-rebuild" and verb == "switch":
        return HostMutation(
            category="system-activation",
            reason="darwin-rebuild switch",
            tool=tool,
            effective_argv=effective_argv,
            privileged=privileged,
        )
    if tool in FILESYSTEM_MUTATING_TOOLS and filesystem_mutates_host(
        tool, effective_argv, privileged
    ):
        return HostMutation(
            category="filesystem-mutation",
            reason=f"{tool} host filesystem path",
            tool=tool,
            effective_argv=effective_argv,
            privileged=privileged,
        )
    return None


def effective_host_argv(argv: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    if not argv or tool_name(argv[0]) != "sudo":
        return argv, False
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        index += 1
        if option in SUDO_OPTIONS_WITH_VALUES and index < len(argv):
            index += 1
    return tuple(argv[index:]), True


def filesystem_mutates_host(
    tool: str, effective_argv: tuple[str, ...], privileged: bool
) -> bool:
    operands, target_dirs = filesystem_operands(effective_argv)
    if not operands and not target_dirs:
        return False
    if privileged:
        return True
    if tool == "cp":
        destinations = target_dirs
        if not destinations and len(operands) > 1:
            destinations = (operands[-1],)
        return any(is_obvious_host_path(path) for path in destinations)
    if tool == "mv":
        return any(is_obvious_host_path(path) for path in (*operands, *target_dirs))
    if tool == "rm":
        return any(is_obvious_host_path(path) for path in operands)
    return False


def filesystem_operands(
    argv: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    operands = []
    target_dirs = []
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            operands.extend(argv[index + 1 :])
            break
        if word in FILESYSTEM_TARGET_DIRECTORY_OPTIONS and index + 1 < len(argv):
            target_dirs.append(argv[index + 1])
            index += 2
            continue
        if word.startswith("--target-directory="):
            target_dirs.append(word.split("=", 1)[1])
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        operands.append(word)
        index += 1
    return tuple(operands), tuple(target_dirs)


def is_obvious_host_path(path: str) -> bool:
    return path.startswith("/") or path.startswith("~")


def host_mutation_name(mutation: HostMutation) -> str:
    if mutation.category == "filesystem-mutation":
        return mutation.tool
    if (
        mutation.tool == "nix"
        and len(mutation.effective_argv) > 2
        and mutation.effective_argv[1] == "profile"
    ):
        return f"nix profile {mutation.effective_argv[2]}"
    return command_display_name(mutation.tool, mutation.effective_argv)


def tool_name(command: str) -> str:
    return command.rsplit("/", maxsplit=1)[-1]


def command_display_name(tool: str, argv: tuple[str, ...]) -> str:
    if len(argv) > 1 and not argv[1].startswith("-"):
        return f"{tool} {argv[1]}"
    return tool


def resolve_source_path(path: str, source_path: str) -> str | None:
    if (
        not source_path
        or source_path.startswith("/")
        or any(character in source_path for character in DYNAMIC_SOURCE_CHARS)
    ):
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), source_path))
    if resolved == "." or resolved.startswith("../"):
        return None
    return resolved


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-").lower() or "command"
