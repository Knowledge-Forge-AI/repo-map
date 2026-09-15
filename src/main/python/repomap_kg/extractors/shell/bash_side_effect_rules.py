"""Bash side-effect command rules and target helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.shell.bash_arguments import argument_value_kind
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    is_dynamic_value,
)
from repomap_kg.extractors.shell.bash_redirects import REDIRECT_OPERATORS


FILE_READ_COMMANDS = frozenset({"cat", "grep", "find", "test", "[", "head", "tail", "wc"})
FILE_WRITE_COMMANDS = frozenset({"touch", "mkdir", "rm", "mv", "cp", "install"})
ARCHIVE_COMMANDS = frozenset({"tar", "unzip"})
PERMISSION_COMMANDS = frozenset({"chmod", "umask"})
OWNERSHIP_COMMANDS = frozenset({"chown", "chgrp"})
NETWORK_COMMANDS = frozenset({"curl", "wget", "nc", "ssh", "scp", "rsync"})
PACKAGE_MANAGERS = frozenset(
    {
        "apt",
        "apt-get",
        "dnf",
        "yum",
        "pacman",
        "brew",
        "npm",
        "pip",
        "pip3",
        "gem",
        "bundle",
        "cargo",
        "go",
    }
)
PACKAGE_MUTATING_OPERATIONS = frozenset(
    {"install", "upgrade", "update", "remove", "uninstall", "add", "delete"}
)
SERVICE_MUTATIONS = {
    "systemctl": frozenset({"restart", "start", "stop", "enable", "disable"}),
    "service": frozenset({"restart", "start", "stop"}),
    "launchctl": frozenset({"kickstart", "bootstrap", "bootout", "enable", "disable"}),
}
CONTAINER_MUTATIONS = {
    "docker": frozenset({"run", "rm", "build"}),
    "docker-compose": frozenset({"up", "run", "rm", "build"}),
    "podman": frozenset({"run", "rm", "build"}),
    "kubectl": frozenset({"apply", "delete", "scale", "rollout"}),
    "helm": frozenset({"install", "upgrade", "uninstall"}),
}
INFRASTRUCTURE_MUTATIONS = {"terraform": frozenset({"apply", "destroy"})}
SECURITY_POLICY_COMMANDS = {
    "spctl": frozenset({"--add", "--enable", "--disable"}),
    "defaults": frozenset({"write"}),
}


def target_metadata(target: str | None) -> dict[str, Any]:
    if target is None:
        return {
            "target_kind": "unknown",
            "target_display": None,
            "target_redacted": False,
            "raw_value_stored": False,
        }
    if is_dynamic_value(target) or argument_value_kind(target) in {
        "glob",
        "command_substitution",
        "process_substitution",
    }:
        return {
            "target_kind": "dynamic",
            "target_display": "[dynamic]",
            "target_redacted": False,
            "raw_value_stored": False,
        }
    return {
        "target_kind": "static",
        "target_display": target,
        "target_redacted": False,
        "raw_value_stored": True,
    }


def positional_args(args: list[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in REDIRECT_OPERATORS:
            index += 2
            continue
        if token.startswith("-"):
            if token in {"-o", "-O", "-C", "-d", "-f", "-H", "-u"}:
                index += 2
            else:
                index += 1
            continue
        if ASSIGNMENT_RE.match(token):
            index += 1
            continue
        output.append(token)
        index += 1
    return output


def last_positional(args: list[str]) -> str | None:
    positionals = positional_args(args)
    if not positionals:
        return None
    return positionals[-1]


def first_operation(args: list[str], *, fallback: str) -> str:
    for arg in positional_args(args):
        return arg
    return fallback


def option_value(args: list[str], option: str) -> str | None:
    for index, token in enumerate(args):
        if token == option and index + 1 < len(args):
            return args[index + 1]
        if token.startswith(option) and token != option and option not in {"-o", "-O"}:
            return token[len(option) :]
    return None


def network_target(command_name: str, args: list[str]) -> str | None:
    if command_name in {"curl", "wget"}:
        for arg in args:
            if arg.startswith(("http://", "https://", "$")):
                return arg
    if command_name == "scp":
        for arg in args:
            if ":" in arg or arg.startswith("$"):
                return arg
    for arg in positional_args(args):
        return arg
    return None


def network_output_target(command_name: str, args: list[str]) -> str | None:
    if command_name == "curl":
        return option_value(args, "-o")
    if command_name == "wget":
        return option_value(args, "-O")
    return None


def package_operation(command_name: str, args: list[str]) -> str | None:
    positionals = positional_args(args)
    if command_name == "go" and positionals[:1] == ["install"]:
        return "install"
    for arg in positionals:
        if arg in PACKAGE_MUTATING_OPERATIONS:
            return arg
    return None


def package_name_for_operation(args: list[str], operation: str) -> str | None:
    positionals = positional_args(args)
    try:
        start = positionals.index(operation) + 1
    except ValueError:
        return None
    for arg in positionals[start:]:
        if not arg.startswith("-"):
            return arg
    return None


def container_operation_for(command_name: str, args: list[str]) -> str | None:
    positionals = positional_args(args)
    if command_name == "docker" and positionals[:1] == ["compose"] and len(positionals) > 1:
        operation = positionals[1]
        return f"compose-{operation}" if operation in {"up", "run", "rm", "build"} else None
    operations = CONTAINER_MUTATIONS.get(command_name)
    if not operations or not positionals:
        return None
    return positionals[0] if positionals[0] in operations else None


def is_credential_command(command_name: str, args: list[str]) -> bool:
    if command_name in {"ssh-add", "security"}:
        return True
    if command_name == "docker" and args[:1] == ["login"]:
        return True
    if command_name == "npm" and args[:1] == ["login"]:
        return True
    if command_name == "aws" and args[:1] == ["configure"]:
        return True
    if command_name == "git" and args[:1] == ["credential"]:
        return True
    if command_name == "gpg" and args[:1] == ["--import"]:
        return True
    return False


def credential_operation(command_name: str, args: list[str]) -> str:
    if args:
        return args[0]
    return command_name


def credential_target(args: list[str]) -> str | None:
    return None


def security_policy_operation(
    command_name: str,
    args: list[str],
    fallback_operation: str,
) -> str | None:
    operations = SECURITY_POLICY_COMMANDS.get(command_name)
    if operations is None:
        return None
    for arg in args:
        if arg in operations:
            return arg
    if fallback_operation in operations:
        return fallback_operation
    return None
