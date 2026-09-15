"""Zsh canonicalization metadata and target helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.shell_shared_helpers import (
    _safe_relative_shell_target,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    file_key,
    parse_key,
)
from repomap_kg.observations.raw import RawObservation


def _zsh_base_metadata() -> dict[str, Any]:
    return {
        "language": "zsh",
        "dialect": "zsh",
        "static_only": True,
        "shell_executed": False,
        "zsh_executed": False,
        "startup_executed": False,
        "plugins_loaded": False,
    }

def _zsh_container_node_metadata() -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["node_role"] = "script"
    return summary

def _zsh_script_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_container_node_metadata()
    for key in ("file_type", "classification_evidence", "parser"):
        if key in metadata:
            summary[key] = metadata[key]
    summary["shebang_present"] = bool(_metadata_text(metadata, "shebang"))
    return summary

def _zsh_function_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["node_role"] = "function"
    summary["body_modeled"] = False
    _append_metadata_text(summary, metadata, "syntax", "syntaxes")
    _append_metadata_text(summary, metadata, "zsh_function_kind", "zsh_function_kinds")
    return summary

def _zsh_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    _append_metadata_text(summary, metadata, "syntax", "syntaxes")
    _append_metadata_text(summary, metadata, "file_type", "file_types")
    evidence = metadata.get("classification_evidence")
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        summary["classification_evidence"] = list(evidence)
    return summary

def _zsh_startup_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["profile_loaded"] = False
    _append_metadata_text(summary, metadata, "startup_file_kind", "startup_file_kinds")
    _append_metadata_text(summary, metadata, "startup_order", "startup_orders")
    return summary

def _zsh_source_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["source_executed"] = False
    summary["file_read"] = False
    _append_metadata_text(summary, metadata, "syntax", "syntaxes")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_command_edge_metadata(
    metadata: Mapping[str, Any],
    command_name: str,
) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["commands"] = [command_name]
    summary["command_executed"] = False
    _append_metadata_text(summary, metadata, "command_family", "command_families")
    _append_metadata_text(summary, metadata, "wrapper_command", "wrapper_commands")
    _append_metadata_text(summary, metadata, "wrapped_command", "wrapped_commands")
    for source_key, target_key in (
        ("argument_count", "argument_counts"),
        ("pipeline_index", "pipeline_indexes"),
        ("chain_index", "chain_indexes"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, int):
            summary[target_key] = [value]
    configuration_intent = metadata.get("configuration_intent")
    if isinstance(configuration_intent, bool):
        summary["configuration_intent"] = configuration_intent
    return summary

def _zsh_autoload_edge_metadata(
    metadata: Mapping[str, Any],
    function_name: str,
) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["functions"] = [function_name]
    summary["autoload_executed"] = False
    summary["function_loaded"] = False
    summary["filesystem_checked"] = False
    flags = metadata.get("flags")
    if isinstance(flags, Sequence) and not isinstance(flags, (str, bytes)):
        summary["flags"] = list(flags)
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_module_edge_metadata(
    metadata: Mapping[str, Any],
    module_name: str,
) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["modules"] = [module_name]
    summary["module_loaded"] = False
    _append_metadata_text(summary, metadata, "operation", "operations")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_completion_edge_metadata(
    metadata: Mapping[str, Any],
    completion_name: str,
) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary["completions"] = [completion_name]
    summary["completion_loaded"] = False
    summary["compinit_executed"] = False
    uses_arguments = metadata.get("uses_arguments")
    if isinstance(uses_arguments, bool):
        summary["uses_arguments"] = uses_arguments
    return summary

def _zsh_plugin_manager_edge_metadata(
    metadata: Mapping[str, Any],
    manager: str,
) -> dict[str, Any]:
    summary = _zsh_plugin_edge_base_metadata()
    summary["managers"] = [manager]
    _append_metadata_text(summary, metadata, "declaration_kind", "declaration_kinds")
    return summary

def _zsh_plugin_edge_metadata(
    metadata: Mapping[str, Any],
    manager: str,
    plugin_name: str,
) -> dict[str, Any]:
    summary = _zsh_plugin_edge_base_metadata()
    summary["managers"] = [manager]
    summary["plugins"] = [plugin_name]
    _append_metadata_text(summary, metadata, "declaration_kind", "declaration_kinds")
    return summary

def _zsh_plugin_edge_base_metadata() -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary.update(
        {
            "configuration_intent": True,
            "plugin_loaded": False,
            "plugin_installed": False,
            "network_called": False,
            "plugins_loaded": False,
        }
    )
    return summary

def _zsh_env_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary = _zsh_runtime_intent_edge_metadata(metadata)
    summary["operations"] = ["read" if observation_kind == "shell.env_read" else "write"]
    _append_metadata_text(summary, metadata, "operation", "raw_operations")
    return summary

def _zsh_file_intent_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary = _zsh_runtime_intent_edge_metadata(metadata)
    summary["file_effects"] = ["read" if observation_kind == "shell.file_read" else "write"]
    _append_metadata_text(summary, metadata, "operation", "operations")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_network_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_runtime_intent_edge_metadata(metadata)
    summary["network_called"] = False
    _append_metadata_text(summary, metadata, "command_name", "commands")
    _append_metadata_text(summary, metadata, "operation", "operations")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_package_edge_metadata(
    metadata: Mapping[str, Any],
    manager: str,
) -> dict[str, Any]:
    summary = _zsh_runtime_intent_edge_metadata(metadata)
    summary["package_managers"] = [manager]
    summary["package_manager_executed"] = False
    _append_metadata_text(summary, metadata, "operation", "operations")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _zsh_host_mutation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_runtime_intent_edge_metadata(metadata)
    _append_metadata_text(summary, metadata, "mutation_category", "mutation_categories")
    _append_metadata_text(summary, metadata, "operation", "operations")
    _append_metadata_text(summary, metadata, "command_name", "commands")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    destructive = metadata.get("destructive")
    if isinstance(destructive, bool):
        summary["destructive_observed"] = destructive
    return summary

def _zsh_runtime_intent_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zsh_base_metadata()
    summary.update(
        {
            "configuration_intent": True,
            "runtime_intent": True,
            "command_executed": False,
            "network_called": False,
            "package_manager_executed": False,
            "filesystem_checked": False,
            "file_opened": False,
            "file_mutated": False,
            "host_mutation_proven": False,
            "plugin_loaded": False,
            "plugin_installed": False,
            "plugins_loaded": False,
        }
    )
    _append_metadata_text(summary, metadata, "startup_file_kind", "startup_file_kinds")
    return summary

def _zsh_command_name(observation: RawObservation) -> str | None:
    for key in ("command_name", "normalized_command", "original_token"):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.name:
        return observation.name
    if observation.target and observation.target.startswith("tool:"):
        try:
            parsed = parse_key(observation.target)
        except GraphKeyError:
            return None
        if parsed.namespace == "tool":
            return parsed.segments[0]
    return None

def _zsh_source_target_key(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "target_kind") != "static":
        return None
    if observation.target is not None and observation.target.startswith("file:"):
        parse_key(observation.target)
        return observation.target
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is not None:
        return file_key(resolved_path)
    return None

def _zsh_file_intent_target_key(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "target_kind") != "static":
        return None
    target_display = _metadata_text(observation.metadata, "target_display")
    if target_display is None:
        return None
    resolved_path = _zsh_safe_relative_target(observation.path, target_display)
    if resolved_path is None:
        return None
    return file_key(resolved_path)

def _zsh_safe_relative_target(source_path: str, target: str) -> str | None:
    return _safe_relative_shell_target(source_path, target)

def _zsh_network_target_name(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "target_kind") != "static":
        return None
    command_name = observation.name or _metadata_text(observation.metadata, "command_name")
    target_display = _metadata_text(observation.metadata, "target_display")
    if command_name is None:
        return None
    if target_display is None or target_display in {"[dynamic]", "[redacted]", "[unknown]"}:
        return command_name
    if "\n" in target_display or len(target_display) > 120:
        return None
    return f"{command_name}:{target_display}"
