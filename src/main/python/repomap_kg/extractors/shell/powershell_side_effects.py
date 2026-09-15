"""PowerShell side-effect observation helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    _is_dynamic_token,
    _is_secret_like_name,
    _secret_like_observation,
    _strip_quotes,
    slug,
)
from repomap_kg.extractors.shell.powershell_tokens import (
    _skip_hashtable,
    _token_has_argument_value,
    _token_is_positional_argument,
)
from repomap_kg.observations.raw import RawObservation


FILE_READ_COMMANDS = {
    "Get-ChildItem": ("Path", 0),
    "Get-Content": ("Path", 0),
    "Test-Path": ("Path", 0),
}
FILE_WRITE_COMMANDS = {
    "Add-Content": ("file_write", "Path", 0, False),
    "Copy-Item": ("file_write", "Destination", 1, False),
    "Move-Item": ("file_write", "Destination", 1, False),
    "New-Item": ("directory_mutation", "Path", 0, False),
    "Remove-Item": ("file_write", "Path", 0, True),
    "Set-Content": ("file_write", "Path", 0, False),
}
REGISTRY_READ_COMMANDS = {"Get-ItemProperty"}
REGISTRY_WRITE_COMMANDS = {"New-ItemProperty", "Remove-ItemProperty", "Set-ItemProperty"}
NETWORK_COMMANDS = {
    "Invoke-RestMethod": "Uri",
    "Invoke-WebRequest": "Uri",
    "Start-BitsTransfer": "Source",
}
REMOTING_COMMANDS = {"Enter-PSSession", "Invoke-Command", "New-PSSession"}
PROCESS_MUTATION_COMMANDS = {
    "Start-Process": "process_execution",
    "Stop-Process": "process_execution",
}
SERVICE_MUTATION_COMMANDS = {
    "New-Service": "service_control",
    "Set-Service": "service_control",
    "Start-Service": "service_control",
    "Stop-Service": "service_control",
}
SCHEDULED_TASK_COMMANDS = {
    "Register-ScheduledTask": "scheduled_task",
    "Unregister-ScheduledTask": "scheduled_task",
}
SECURITY_POLICY_COMMANDS = {
    "Set-AuthenticodeSignature": "security_policy",
    "Set-ExecutionPolicy": "security_policy",
}
CREDENTIAL_COMMANDS = {
    "ConvertTo-SecureString",
    "Get-Credential",
    "New-Object",
}
PACKAGE_CMDLETS = {
    "Install-Module": ("PowerShellGet", "install", "Name", 0),
    "Install-Package": ("PackageManagement", "install", "Name", 0),
    "Uninstall-Module": ("PowerShellGet", "uninstall", "Name", 0),
    "Uninstall-Package": ("PackageManagement", "uninstall", "Name", 0),
    "Update-Module": ("PowerShellGet", "update", "Name", 0),
}
EXTERNAL_PACKAGE_MANAGERS = {
    "choco": {"install", "upgrade", "uninstall"},
    "scoop": {"install", "update", "uninstall"},
    "winget": {"install", "upgrade", "uninstall"},
}


def _target_from_arguments(
    parsed: dict[str, Any],
    argument_name: str,
    positional_index: int,
) -> dict[str, Any]:
    value = _argument_value(parsed, argument_name)
    if value is None and positional_index >= 0:
        positional = parsed["positional"]
        if positional_index < len(positional):
            value = positional[positional_index]
    return _target_summary(value)


def _argument_value(parsed: dict[str, Any], argument_name: str) -> str | None:
    return parsed["named"].get(argument_name.lower())


def _registry_target_from_arguments(parsed: dict[str, Any]) -> dict[str, Any]:
    target = _target_from_arguments(parsed, "Path", 0)
    if _is_registry_target(_target_display(target)):
        return target
    return _empty_target_summary()


def _target_summary(token: str | None) -> dict[str, Any]:
    if token is None:
        return _empty_target_summary()
    stripped = _strip_quotes(token)
    if not stripped:
        return _empty_target_summary()
    if _is_dynamic_token(stripped):
        return {
            "target_kind": "dynamic",
            "target_display": "[dynamic]",
            "target_redacted": True,
            "target_value_stored": False,
        }
    if _is_registry_target(stripped):
        return {
            "target_kind": "static",
            "target_display": stripped,
            "target_redacted": False,
            "target_value_stored": True,
        }
    if _is_secret_like_name(stripped):
        return {
            "target_kind": "static",
            "target_display": "[redacted]",
            "target_redacted": True,
            "target_value_stored": False,
        }
    return {
        "target_kind": "static",
        "target_display": stripped,
        "target_redacted": False,
        "target_value_stored": True,
    }


def _empty_target_summary() -> dict[str, Any]:
    return {
        "target_kind": "none",
        "target_display": "[unknown]",
        "target_redacted": True,
        "target_value_stored": False,
    }


def _target_display(target: dict[str, Any]) -> str:
    return str(target.get("target_display", "[unknown]"))


def _target_observation(
    kind: str,
    relative_path: str,
    line_number: int,
    *,
    operation: str,
    command_name: str,
    original_token: str,
    target: dict[str, Any],
    destructive: bool = False,
) -> RawObservation:
    metadata = _side_effect_metadata(
        operation=operation,
        command_name=command_name,
        original_token=original_token,
        target=target,
    )
    metadata["destructive"] = destructive
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.rsplit('.', 1)[1]}:{line_number}:{slug(operation)}:{slug(_target_display(target))}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=operation,
        target=_observation_target(kind, target),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _env_observation(
    kind: str,
    relative_path: str,
    line_number: int,
    name: str,
    *,
    operation: str,
) -> RawObservation:
    redacted = _is_secret_like_name(name)
    metadata = {
        "operation": operation,
        "target_kind": "env",
        "target_display": "[redacted]" if redacted else f"Env:{name}",
        "target_redacted": redacted,
        "redacted": redacted,
        "static_only": True,
        "powershell_executed": False,
    }
    if redacted:
        metadata["redaction_reason"] = "secret-like environment variable name"
        metadata["raw_value_stored"] = False
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.rsplit('.', 1)[1]}:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=None if redacted else f"env:{name}",
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _network_observation(
    relative_path: str,
    line_number: int,
    *,
    command_name: str,
    original_token: str,
    target: dict[str, Any],
    method: str | None,
) -> RawObservation:
    metadata = _side_effect_metadata(
        operation=command_name,
        command_name=command_name,
        original_token=original_token,
        target=target,
    )
    metadata["network_executed"] = False
    if method is not None:
        metadata["method"] = _strip_quotes(method)
    return RawObservation(
        kind="powershell.network_call",
        source_id=f"{relative_path}#network-call:{line_number}:{slug(command_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        target=_observation_target("powershell.network_call", target),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _remoting_observation(
    relative_path: str,
    line_number: int,
    *,
    command_name: str,
    original_token: str,
    target: dict[str, Any],
) -> RawObservation:
    metadata = _side_effect_metadata(
        operation=command_name,
        command_name=command_name,
        original_token=original_token,
        target=target,
    )
    metadata["remoting_executed"] = False
    return RawObservation(
        kind="powershell.remoting",
        source_id=f"{relative_path}#remoting:{line_number}:{slug(command_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        target=_observation_target("powershell.remoting", target),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _host_mutation_for_command_category(
    relative_path: str,
    line_number: int,
    original_token: str,
    command_name: str,
    mutation_category: str,
    target: dict[str, Any],
    *,
    destructive: bool,
) -> RawObservation:
    return _host_mutation_observation(
        relative_path,
        line_number,
        operation=command_name,
        command_name=command_name,
        original_token=original_token,
        mutation_category=mutation_category,
        target=target,
        destructive=destructive,
    )


def _package_host_mutation_observation(
    relative_path: str,
    line_number: int,
    *,
    original_token: str,
    command_name: str,
    manager: str,
    operation: str,
    target: dict[str, Any],
) -> RawObservation:
    observation = _host_mutation_observation(
        relative_path,
        line_number,
        operation=command_name,
        command_name=command_name,
        original_token=original_token,
        mutation_category="package_management",
        target=target,
        destructive=operation in {"uninstall", "remove"},
    )
    observation.metadata["manager"] = manager
    observation.metadata["package_operation"] = operation
    return observation


def _host_mutation_observation(
    relative_path: str,
    line_number: int,
    *,
    operation: str,
    command_name: str,
    original_token: str,
    mutation_category: str,
    target: dict[str, Any],
    destructive: bool,
) -> RawObservation:
    metadata = _side_effect_metadata(
        operation=operation,
        command_name=command_name,
        original_token=original_token,
        target=target,
    )
    metadata["mutation_category"] = mutation_category
    metadata["destructive"] = destructive
    return RawObservation(
        kind="powershell.host_mutation",
        source_id=(
            f"{relative_path}#host-mutation:{line_number}:"
            f"{slug(mutation_category)}:{slug(operation)}:{slug(_target_display(target))}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=f"{mutation_category}:{operation}",
        target=_observation_target("powershell.host_mutation", target),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _side_effect_metadata(
    *,
    operation: str,
    command_name: str,
    original_token: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "operation": operation,
        "command_name": command_name,
        "original_token": original_token,
        "target_kind": target["target_kind"],
        "target_display": target["target_display"],
        "target_redacted": target["target_redacted"],
        "static_only": True,
        "powershell_executed": False,
    }


def _observation_target(kind: str, target: dict[str, Any]) -> str | None:
    if target["target_redacted"] or target["target_kind"] == "none":
        return None
    display = target["target_display"]
    if kind in {"powershell.file_read", "powershell.file_write"}:
        return f"file:{display}"
    if kind in {"powershell.registry_read", "powershell.registry_write"}:
        return f"registry:{display}"
    if kind == "powershell.network_call":
        return f"url:{display}"
    if kind == "powershell.remoting":
        return f"host:{display}"
    return f"target:{display}"


def _is_registry_target(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith("hkcu:") or lowered.startswith("hklm:") or lowered.startswith("registry::")


def _process_target(command_name: str, parsed: dict[str, Any]) -> dict[str, Any]:
    if command_name == "Start-Process":
        return _target_from_arguments(parsed, "FilePath", 0)
    return _target_from_arguments(parsed, "Name", 0)


def _external_package_operation(command_name: str, tokens: list[str]) -> str | None:
    if len(tokens) < 2:
        return None
    operation = _strip_quotes(tokens[1]).lower()
    if operation in EXTERNAL_PACKAGE_MANAGERS[command_name]:
        return operation
    return None


def _external_package_name(tokens: list[str]) -> str | None:
    if len(tokens) >= 3:
        return tokens[2]
    return None


def _is_credential_command(parsed: dict[str, Any], tokens: list[str]) -> bool:
    if tokens and tokens[0].lower() != "new-object":
        return True
    return any(
        _strip_quotes(token).lower() == "system.management.automation.pscredential"
        for token in parsed["positional"]
    )


def _is_sensitive_command_argument(
    command_name: str,
    argument_name: str | None,
    argument_position: int | None,
) -> bool:
    return (
        command_name == "ConvertTo-SecureString"
        and argument_name is None
        and argument_position == 0
    )


def _mask_quoted_strings(line: str) -> str:
    return re.sub(r'"[^"]*"|\'[^\']*\'', '""', line)


def _side_effect_observations_for_command(
    relative_path: str,
    line_number: int,
    segment: str,
    *,
    original_token: str,
    command_name: str,
    command_family: str,
    tokens: list[str],
) -> tuple[RawObservation, ...]:
    parsed = _parsed_arguments(tokens[1:])
    observations: list[RawObservation] = []
    if command_name in FILE_READ_COMMANDS:
        argument_name, position = FILE_READ_COMMANDS[command_name]
        target = _target_from_arguments(parsed, argument_name, position)
        observations.append(
            _target_observation(
                "powershell.file_read",
                relative_path,
                line_number,
                operation=command_name,
                command_name=command_name,
                original_token=original_token,
                target=target,
            )
        )
    if command_name in FILE_WRITE_COMMANDS:
        mutation_category, argument_name, position, destructive = FILE_WRITE_COMMANDS[
            command_name
        ]
        target = _target_from_arguments(parsed, argument_name, position)
        observations.append(
            _target_observation(
                "powershell.file_write",
                relative_path,
                line_number,
                operation=command_name,
                command_name=command_name,
                original_token=original_token,
                target=target,
                destructive=destructive,
            )
        )
        observations.append(
            _host_mutation_observation(
                relative_path,
                line_number,
                operation=command_name,
                command_name=command_name,
                original_token=original_token,
                mutation_category=mutation_category,
                target=target,
                destructive=destructive,
            )
        )
    if command_name in REGISTRY_READ_COMMANDS:
        target = _registry_target_from_arguments(parsed)
        if target["target_kind"] != "none":
            observations.append(
                _target_observation(
                    "powershell.registry_read",
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    target=target,
                )
            )
    if command_name in REGISTRY_WRITE_COMMANDS:
        target = _registry_target_from_arguments(parsed)
        if target["target_kind"] != "none":
            observations.append(
                _target_observation(
                    "powershell.registry_write",
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    target=target,
                    destructive=command_name.startswith("Remove-"),
                )
            )
            observations.append(
                _host_mutation_observation(
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    mutation_category="registry_write",
                    target=target,
                    destructive=command_name.startswith("Remove-"),
                )
            )
    if command_name == "Set-Item":
        target = _target_from_arguments(parsed, "Path", 0)
        if _target_display(target).lower().startswith("env:"):
            env_name = _target_display(target).split(":", 1)[1]
            observations.append(
                _env_observation(
                    "powershell.env_write",
                    relative_path,
                    line_number,
                    env_name,
                    operation=command_name,
                )
            )
            observations.append(
                _host_mutation_observation(
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    mutation_category="env_write",
                    target=target,
                    destructive=False,
                )
            )
    if command_name in NETWORK_COMMANDS:
        target = _target_from_arguments(parsed, NETWORK_COMMANDS[command_name], 0)
        observations.append(
            _network_observation(
                relative_path,
                line_number,
                command_name=command_name,
                original_token=original_token,
                target=target,
                method=_argument_value(parsed, "Method"),
            )
        )
        output_target = _target_from_arguments(
            parsed,
            "OutFile" if command_name != "Start-BitsTransfer" else "Destination",
            -1,
        )
        if output_target["target_kind"] != "none":
            observations.append(
                _target_observation(
                    "powershell.file_write",
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    target=output_target,
                    destructive=False,
                )
            )
            observations.append(
                _host_mutation_observation(
                    relative_path,
                    line_number,
                    operation=command_name,
                    command_name=command_name,
                    original_token=original_token,
                    mutation_category="file_write",
                    target=output_target,
                    destructive=False,
                )
            )
    if command_name in REMOTING_COMMANDS:
        target = _target_from_arguments(parsed, "ComputerName", 0)
        observations.append(
            _remoting_observation(
                relative_path,
                line_number,
                command_name=command_name,
                original_token=original_token,
                target=target,
            )
        )
    if command_name in PROCESS_MUTATION_COMMANDS:
        observations.append(
            _host_mutation_for_command_category(
                relative_path,
                line_number,
                original_token,
                command_name,
                PROCESS_MUTATION_COMMANDS[command_name],
                _process_target(command_name, parsed),
                destructive=command_name.startswith("Stop-"),
            )
        )
    if command_name in SERVICE_MUTATION_COMMANDS:
        observations.append(
            _host_mutation_for_command_category(
                relative_path,
                line_number,
                original_token,
                command_name,
                SERVICE_MUTATION_COMMANDS[command_name],
                _target_from_arguments(parsed, "Name", 0),
                destructive=command_name.startswith("Stop-"),
            )
        )
    if command_name in SCHEDULED_TASK_COMMANDS:
        observations.append(
            _host_mutation_for_command_category(
                relative_path,
                line_number,
                original_token,
                command_name,
                SCHEDULED_TASK_COMMANDS[command_name],
                _target_from_arguments(parsed, "TaskName", 0),
                destructive=command_name.startswith("Unregister-"),
            )
        )
    if command_name in SECURITY_POLICY_COMMANDS:
        observations.append(
            _host_mutation_for_command_category(
                relative_path,
                line_number,
                original_token,
                command_name,
                SECURITY_POLICY_COMMANDS[command_name],
                _target_from_arguments(parsed, "FilePath", 0),
                destructive=False,
            )
        )
    if command_name in CREDENTIAL_COMMANDS and _is_credential_command(parsed, tokens):
        observations.append(
            _secret_like_observation(
                relative_path,
                line_number,
                command_name,
                secret_source="credential_command",
                reason="credential handling command",
            )
        )
        observations.append(
            _host_mutation_for_command_category(
                relative_path,
                line_number,
                original_token,
                command_name,
                "credential_handling",
                _target_from_arguments(parsed, "UserName", 0),
                destructive=False,
            )
        )
    if command_name in PACKAGE_CMDLETS:
        manager, operation, argument_name, position = PACKAGE_CMDLETS[command_name]
        target = _target_from_arguments(parsed, argument_name, position)
        observations.append(
            _package_host_mutation_observation(
                relative_path,
                line_number,
                original_token=original_token,
                command_name=command_name,
                manager=manager,
                operation=operation,
                target=target,
            )
        )
    if command_family == "external" and command_name in EXTERNAL_PACKAGE_MANAGERS:
        operation = _external_package_operation(command_name, tokens)
        if operation is not None:
            target = _target_summary(_external_package_name(tokens))
            observations.append(
                _package_host_mutation_observation(
                    relative_path,
                    line_number,
                    original_token=original_token,
                    command_name=command_name,
                    manager=command_name,
                    operation=operation,
                    target=target,
                )
            )
    return tuple(observations)


def _parsed_arguments(tokens: list[str]) -> dict[str, Any]:
    named: dict[str, str | None] = {}
    positional: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"|", ";", "&&", "||"}:
            break
        if token == "{":
            break
        if token == "@{":
            index = _skip_hashtable(tokens, index)
            continue
        if token.startswith("-") and len(token) > 1:
            argument_name, inline_value = _split_named_argument(token)
            if inline_value is not None:
                named[argument_name.lower()] = inline_value
                index += 1
                continue
            value: str | None = None
            if index + 1 < len(tokens) and _token_has_argument_value(tokens[index + 1]):
                value = tokens[index + 1]
                if value == "@{":
                    named[argument_name.lower()] = None
                    index = _skip_hashtable(tokens, index + 1)
                    continue
                index += 2
            else:
                index += 1
            named[argument_name.lower()] = value
            continue
        if _token_is_positional_argument(token):
            positional.append(token)
        index += 1
    return {"named": named, "positional": positional}


def _split_named_argument(token: str) -> tuple[str, str | None]:
    stripped = token.lstrip("-")
    if ":" in stripped:
        name, value = stripped.split(":", 1)
        return name, value
    return stripped, None
