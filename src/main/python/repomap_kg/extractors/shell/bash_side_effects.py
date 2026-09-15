"""Bash side-effect observation helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell._bash_side_effect_observations import (
    file_effect_observation,
    file_effect_observation_from_metadata,
    host_mutation_from_target_metadata,
    host_mutation_observation,
    network_call_observation,
)
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
    is_dynamic_value,
)
from repomap_kg.extractors.shell.bash_commands import normalize_command_token
from repomap_kg.extractors.shell.bash_side_effect_rules import (
    ARCHIVE_COMMANDS,
    CONTAINER_MUTATIONS,
    FILE_READ_COMMANDS,
    FILE_WRITE_COMMANDS,
    INFRASTRUCTURE_MUTATIONS,
    NETWORK_COMMANDS,
    OWNERSHIP_COMMANDS,
    PACKAGE_MANAGERS,
    PACKAGE_MUTATING_OPERATIONS,
    PERMISSION_COMMANDS,
    SECURITY_POLICY_COMMANDS,
    SERVICE_MUTATIONS,
    container_operation_for,
    credential_operation,
    credential_target,
    first_operation,
    is_credential_command,
    last_positional,
    network_output_target,
    network_target,
    option_value,
    package_name_for_operation,
    package_operation,
    positional_args,
    security_policy_operation,
    target_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


def side_effect_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    overlays: list[tuple[str, str]],
    args: list[str],
    redirects: list[RawObservation],
    context: dict[str, Any],
    wrapped_command: str | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(
        redirect_side_effect_observations(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            redirects,
            context,
        )
    )
    effective_command, effective_args, privileged = effective_command_for_side_effect(
        command_name,
        args,
        wrapped_command=wrapped_command,
    )
    if effective_command is None:
        return tuple(observations)
    observations.extend(
        command_side_effect_observations(
            relative_path,
            line_number,
            command_source_id,
            effective_command,
            effective_args,
            overlays=overlays,
            context=context,
            privileged=privileged,
        )
    )
    return tuple(observations)

def effective_command_for_side_effect(
    command_name: str,
    args: list[str],
    *,
    wrapped_command: str | None,
) -> tuple[str | None, list[str], bool]:
    if command_name == "sudo":
        command, remaining = command_after_prefix(args)
        return command, remaining, True
    if command_name == "env":
        command, remaining = command_after_env(args)
        return command, remaining, False
    if command_name in {"command", "builtin", "time"}:
        command, remaining = command_after_prefix(args)
        return command, remaining, False
    if wrapped_command is not None and command_name not in {"nohup"}:
        command, remaining = command_after_prefix(args)
        return command, remaining, False
    return command_name, args, False


def command_after_prefix(args: list[str]) -> tuple[str | None, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 1
    if index < len(args) and args[index] == "env":
        return command_after_env(args[index + 1 :])
    if index >= len(args) or args[index].startswith("$"):
        return None, []
    return normalize_command_token(args[index]), args[index + 1 :]


def command_after_env(args: list[str]) -> tuple[str | None, list[str]]:
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("-") or ASSIGNMENT_RE.match(token):
            index += 1
            continue
        if token.startswith("$"):
            return None, []
        return normalize_command_token(token), args[index + 1 :]
    return None, []


def command_side_effect_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    overlays: list[tuple[str, str]],
    context: dict[str, Any],
    privileged: bool,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    if command_name in FILE_READ_COMMANDS:
        target = file_read_target(command_name, args)
        if target is not None:
            observations.append(
                file_effect_observation(
                    "shell.file_read",
                    relative_path,
                    line_number,
                    command_source_id,
                    command_name,
                    operation=command_name,
                    target=target,
                    via="command",
                    context=context,
                )
            )
    if command_name in FILE_WRITE_COMMANDS or command_name == "ln":
        observations.extend(
            file_mutation_observations(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                args,
                context=context,
                privileged=privileged,
            )
        )
    if command_name in ARCHIVE_COMMANDS:
        observations.extend(
            archive_mutation_observations(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                args,
                context=context,
                privileged=privileged,
            )
        )
    if command_name in PERMISSION_COMMANDS:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="permission_mutation",
                operation=first_operation(args, fallback=command_name),
                target=last_positional(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if command_name in OWNERSHIP_COMMANDS:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="ownership_mutation",
                operation=first_operation(args, fallback=command_name),
                target=last_positional(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if command_name in NETWORK_COMMANDS:
        observations.extend(
            network_side_effect_observations(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                args,
                context=context,
            )
        )
    observations.extend(
        package_side_effect_observations(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            args,
            context=context,
            privileged=privileged,
        )
    )
    observations.extend(
        operational_host_mutations(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            args,
            context=context,
            privileged=privileged,
        )
    )
    return tuple(observations)


def redirect_side_effect_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    redirects: list[RawObservation],
    context: dict[str, Any],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for index, redirect in enumerate(redirects):
        metadata = redirect.metadata
        operator = metadata["operator"]
        mode = metadata["mode"]
        if mode == "read":
            observations.append(
                file_effect_observation_from_metadata(
                    "shell.file_read",
                    relative_path,
                    line_number,
                    command_source_id,
                    command_name,
                    operation="redirect-read",
                    target_metadata=metadata,
                    suffix=f"redirect-read-{index}",
                    via="redirect",
                    context=context,
                )
            )
            continue
        if mode not in {"truncate", "append"}:
            continue
        observations.append(
            file_effect_observation_from_metadata(
                "shell.file_write",
                relative_path,
                line_number,
                command_source_id,
                command_name,
                operation=f"redirect-{mode}",
                target_metadata=metadata,
                suffix=f"redirect-write-{index}",
                via="redirect",
                context=context,
            )
        )
        observations.append(
            host_mutation_from_target_metadata(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="file_write",
                operation=f"redirect-{operator}",
                target_metadata=metadata,
                destructive=mode == "truncate",
                suffix=f"redirect-file-write-{index}",
                context=context,
            )
        )
        if metadata.get("target_profile_like"):
            observations.append(
                host_mutation_from_target_metadata(
                    relative_path,
                    line_number,
                    command_source_id,
                    command_name,
                    mutation_category="shell_profile_mutation",
                    operation=f"redirect-{operator}",
                    target_metadata=metadata,
                    destructive=mode == "truncate",
                    suffix=f"redirect-profile-{index}",
                    context=context,
                )
            )
    return tuple(observations)


def file_read_target(command_name: str, args: list[str]) -> str | None:
    if command_name in {"test", "["}:
        for index, token in enumerate(args):
            if token in {"-f", "-e", "-d", "-r", "-s"} and index + 1 < len(args):
                return args[index + 1]
    positionals = positional_args(args)
    if not positionals:
        return None
    if command_name == "grep" and len(positionals) > 1:
        return positionals[-1]
    if command_name == "grep":
        return None
    return positionals[-1]


def file_mutation_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    context: dict[str, Any],
    privileged: bool,
) -> tuple[RawObservation, ...]:
    category = {
        "mkdir": "directory_mutation",
        "rm": "file_write",
        "mv": "file_write",
        "cp": "file_write",
        "install": "file_write",
        "touch": "file_write",
        "ln": "symlink_mutation",
    }.get(command_name, "file_write")
    target = last_positional(args)
    destructive = command_name in {"rm", "mv"}
    observations = [
        file_effect_observation(
            "shell.file_write",
            relative_path,
            line_number,
            command_source_id,
            command_name,
            operation=command_name,
            target=target,
            via="command",
            context=context,
        ),
        host_mutation_observation(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            mutation_category=category,
            operation=command_name,
            target=target,
            destructive=destructive,
            privileged=privileged,
            context=context,
        ),
    ]
    return tuple(observations)


def archive_mutation_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    context: dict[str, Any],
    privileged: bool,
) -> tuple[RawObservation, ...]:
    if command_name == "tar" and not any("x" in arg for arg in args if arg.startswith("-")):
        return ()
    target = option_value(args, "-C") or option_value(args, "-d") or last_positional(args)
    return (
        host_mutation_observation(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            mutation_category="archive_extraction",
            operation=command_name,
            target=target,
            destructive=False,
            privileged=privileged,
            context=context,
        ),
    )


def network_side_effect_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    context: dict[str, Any],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = [
        network_call_observation(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            target=network_target(command_name, args),
            context=context,
        )
    ]
    output_target = network_output_target(command_name, args)
    if output_target is not None:
        observations.append(
            file_effect_observation(
                "shell.file_write",
                relative_path,
                line_number,
                command_source_id,
                command_name,
                operation="network-download",
                target=output_target,
                via="network-output",
                context=context,
            )
        )
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="network_download",
                operation="download",
                target=output_target,
                destructive=False,
                privileged=False,
                context=context,
            )
        )
    return tuple(observations)


def package_side_effect_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    context: dict[str, Any],
    privileged: bool,
) -> tuple[RawObservation, ...]:
    if command_name not in PACKAGE_MANAGERS:
        return ()
    if command_name == "brew" and args[:1] == ["services"]:
        return ()
    operation = package_operation(command_name, args)
    if operation not in PACKAGE_MUTATING_OPERATIONS:
        return ()
    package = package_name_for_operation(args, operation)
    metadata = {
        "manager": command_name,
        "operation": operation,
        "package": package,
        "package_kind": "dynamic" if package and is_dynamic_value(package) else "static" if package else "unknown",
        "privileged": privileged,
    }
    metadata.update(context)
    return (
        RawObservation(
            kind="shell.package_manager",
            source_id=f"{command_source_id}:package:{slug(operation)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=command_name,
            target=f"tool:{command_name}",
            confidence="heuristic",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bash_metadata(metadata),
        ),
        host_mutation_observation(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            mutation_category="package_management",
            operation=operation,
            target=package,
            destructive=operation in {"remove", "uninstall", "delete"},
            privileged=privileged,
            context=context,
        ),
    )


def operational_host_mutations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    args: list[str],
    *,
    context: dict[str, Any],
    privileged: bool,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    operation = first_operation(args, fallback=command_name)
    if command_name == "brew" and args[:1] == ["services"] and len(args) > 1:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="service_control",
                operation=f"services-{args[1]}",
                target=args[2] if len(args) > 2 else None,
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if command_name in SERVICE_MUTATIONS and operation in SERVICE_MUTATIONS[command_name]:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="service_control",
                operation=operation,
                target=last_positional(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if command_name in {"crontab", "systemd-run"}:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="scheduled_job",
                operation=operation,
                target=last_positional(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    container_operation = container_operation_for(command_name, args)
    if container_operation is not None:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="container_runtime",
                operation=container_operation,
                target=last_positional(args),
                destructive=container_operation in {"rm", "delete", "uninstall"},
                privileged=privileged,
                context=context,
            )
        )
    if command_name in INFRASTRUCTURE_MUTATIONS and operation in INFRASTRUCTURE_MUTATIONS[command_name]:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="infrastructure_runtime",
                operation=operation,
                target=last_positional(args),
                destructive=operation == "destroy",
                privileged=privileged,
                context=context,
            )
        )
    security_operation = security_policy_operation(command_name, args, operation)
    if security_operation is not None:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="security_policy",
                operation=security_operation,
                target=last_positional(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if is_credential_command(command_name, args):
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="credential_handling",
                operation=credential_operation(command_name, args),
                target=credential_target(args),
                destructive=False,
                privileged=privileged,
                context=context,
            )
        )
    if command_name in {"nohup", "exec", "kill", "pkill"}:
        observations.append(
            host_mutation_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                mutation_category="process_execution",
                operation=operation,
                target=last_positional(args),
                destructive=command_name in {"kill", "pkill"},
                privileged=privileged,
                context=context,
            )
        )
    return tuple(observations)
