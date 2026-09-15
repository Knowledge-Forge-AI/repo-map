"""PowerShell canonical graph-key and metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    host_category_key,
    parse_key,
    powershell_manifest_export_key,
    powershell_manifest_key,
    powershell_module_key,
    powershell_script_key,
    tool_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _powershell_file_target_key(observation: RawObservation) -> str:
    if observation.kind == "powershell.module":
        return powershell_module_key(observation.path)
    if observation.kind == "powershell.manifest":
        return powershell_manifest_key(observation.path)
    return powershell_script_key(observation.path)

def _powershell_container_key(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".psm1"):
        return powershell_module_key(path)
    if lowered.endswith(".psd1"):
        return powershell_manifest_key(path)
    return powershell_script_key(path)

def _powershell_file_node_metadata(observation: RawObservation) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "language": "powershell",
        "static_only": True,
        "powershell_executed": False,
    }
    file_type = _metadata_text(observation.metadata, "file_type")
    if file_type is not None:
        metadata["file_type"] = file_type
    return metadata

def _powershell_container_node_metadata(path: str) -> dict[str, Any]:
    file_type = "module" if path.lower().endswith(".psm1") else "script"
    if path.lower().endswith(".psd1"):
        file_type = "manifest"
    return {
        "language": "powershell",
        "file_type": file_type,
        "static_only": True,
        "powershell_executed": False,
    }

def _powershell_function_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "static_only": True,
        "powershell_executed": False,
    }
    for key in ("scope_prefix", "function"):
        value = _metadata_text(metadata, key)
        if value is not None:
            summary[key] = value
    return summary

def _powershell_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"static_only": True, "powershell_executed": False}
    for source_key, target_key in (
        ("file_type", "file_types"),
        ("scope_prefix", "scope_prefixes"),
        ("function", "functions"),
        ("export_kind", "export_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    wildcard = metadata.get("wildcard")
    if isinstance(wildcard, bool):
        summary["wildcard_observed"] = wildcard
    return summary

def _powershell_command_name(observation: RawObservation) -> str | None:
    for key in ("normalized_command", "command_name", "original_token"):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.name:
        return observation.name
    if observation.target and observation.target.startswith("tool:"):
        try:
            return parse_key(observation.target).segments[0]
        except GraphKeyError:
            return None
    return None

def _powershell_command_edge_metadata(
    metadata: Mapping[str, Any], command_name: str
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "commands": [command_name],
        "static_only": True,
        "powershell_executed": False,
    }
    for source_key, target_key in (
        ("original_token", "original_tokens"),
        ("command_family", "command_families"),
        ("alias_expansion", "alias_expansions"),
        ("alias_source", "alias_sources"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    pipeline_id = metadata.get("pipeline_id")
    if isinstance(pipeline_id, str) and pipeline_id:
        summary["pipeline_ids"] = [pipeline_id]
    pipeline_index = metadata.get("pipeline_index")
    if isinstance(pipeline_index, int):
        summary["pipeline_indexes"] = [pipeline_index]
    return summary

def _powershell_env_edge_metadata(
    metadata: Mapping[str, Any], observation_kind: str
) -> dict[str, Any]:
    operation = "read" if observation_kind == "powershell.env_read" else "write"
    summary: dict[str, Any] = {
        "operations": [operation],
        "static_only": True,
        "powershell_executed": False,
    }
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary

def _powershell_host_mutation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "static_only": True,
        "powershell_executed": False,
    }
    for source_key, target_key in (
        ("mutation_category", "mutation_categories"),
        ("operation", "operations"),
        ("command_name", "commands"),
        ("original_token", "original_tokens"),
        ("manager", "managers"),
        ("package_operation", "package_operations"),
        ("target_kind", "target_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    destructive = metadata.get("destructive")
    if isinstance(destructive, bool):
        summary["destructive_observed"] = destructive
    target_redacted = metadata.get("target_redacted")
    if isinstance(target_redacted, bool):
        summary["target_redacted_observed"] = target_redacted
    return summary

def _powershell_reference_parts(
    observation: RawObservation,
) -> tuple[str, str, str, dict[str, Any]]:
    if observation.kind in ("powershell.import_module", "powershell.using_module"):
        source_key = _powershell_container_key(observation.path)
        target_key = _powershell_module_or_file_target_key(observation)
        return (
            source_key,
            target_key,
            "imports",
            _powershell_reference_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "powershell.dot_source":
        return (
            _powershell_container_key(observation.path),
            _powershell_file_target_key_from_observation(observation),
            "sources",
            _powershell_reference_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "powershell.manifest_dependency":
        return (
            powershell_manifest_key(observation.path),
            _powershell_manifest_dependency_target_key(observation),
            "depends_on",
            _powershell_manifest_dependency_edge_metadata(observation.metadata),
        )
    if observation.kind == "powershell.manifest_file_reference":
        return (
            powershell_manifest_key(observation.path),
            _powershell_file_target_key_from_observation(observation),
            "references",
            _powershell_reference_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "powershell.manifest_export":
        source_key = powershell_manifest_key(observation.path)
        export_kind = _metadata_text(observation.metadata, "export_kind") or "unknown"
        export_name = observation.name or _metadata_text(observation.metadata, "name")
        if export_name is None:
            export_name = "unknown"
        return (
            source_key,
            powershell_manifest_export_key(source_key, export_kind, export_name),
            "defines",
            _powershell_define_edge_metadata(observation.metadata),
        )
    if observation.kind == "powershell.network_call":
        return (
            file_key(observation.path),
            _powershell_network_target_key(observation),
            "references",
            _powershell_reference_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "powershell.remoting":
        return (
            file_key(observation.path),
            _powershell_remoting_target_key(observation),
            "references",
            _powershell_reference_edge_metadata(observation.metadata, observation.kind),
        )
    raise GraphKeyError(f"unsupported PowerShell reference kind: {observation.kind}")

def _powershell_module_or_file_target_key(observation: RawObservation) -> str:
    target = observation.target
    if isinstance(target, str) and target.startswith("file:"):
        parsed = parse_key(target)
        if parsed.namespace != "file":
            raise GraphKeyError("PowerShell file target must use file namespace")
        return target
    module_name = observation.name or _metadata_text(observation.metadata, "module_name")
    if module_name is None and isinstance(target, str) and target.startswith("module:"):
        module_name = target.split(":", 1)[1]
    if module_name is None:
        module_name = "missing-module"
    return external_key("powershell.module", module_name)

def _powershell_file_target_key_from_observation(observation: RawObservation) -> str:
    target = observation.target
    if isinstance(target, str) and target.startswith("file:"):
        parsed = parse_key(target)
        if parsed.namespace != "file":
            raise GraphKeyError("PowerShell file target must use file namespace")
        return target
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is not None:
        return file_key(resolved_path)
    reference = _metadata_text(observation.metadata, "reference")
    if reference is not None:
        return file_key(reference)
    dynamic_reason = _metadata_text(observation.metadata, "dynamic_reason")
    if dynamic_reason is not None:
        return dynamic_key("file", dynamic_reason)
    return unknown_key("file", "missing-powershell-file-reference")

def _powershell_manifest_dependency_target_key(observation: RawObservation) -> str:
    dependency_kind = _metadata_text(observation.metadata, "dependency_kind") or "module"
    if dependency_kind == "assembly":
        assembly_name = (
            _metadata_text(observation.metadata, "assembly_name")
            or observation.name
            or "missing-assembly"
        )
        return external_key("powershell.assembly", assembly_name)
    module_name = (
        _metadata_text(observation.metadata, "module_name")
        or observation.name
        or "missing-module"
    )
    return external_key("powershell.module", module_name)

def _powershell_network_target_key(observation: RawObservation) -> str:
    target_display = _metadata_text(observation.metadata, "target_display")
    if target_display and target_display.startswith(("http://", "https://")):
        return external_url_key(target_display)
    if target_display and target_display != "[dynamic]":
        return external_key("powershell.network", target_display)
    return dynamic_key("external.url", "powershell-network-target")

def _powershell_remoting_target_key(observation: RawObservation) -> str:
    target_display = _metadata_text(observation.metadata, "target_display")
    target_kind = _metadata_text(observation.metadata, "target_kind")
    if target_display and target_display != "[dynamic]" and target_kind == "static":
        return external_key("powershell.remoting", target_display)
    return dynamic_key("powershell.remoting", "dynamic-target")

def _powershell_reference_edge_metadata(
    metadata: Mapping[str, Any], observation_kind: str
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "observation_kinds": [observation_kind],
        "static_only": True,
        "powershell_executed": False,
    }
    for source_key, target_key in (
        ("module_name", "module_names"),
        ("field", "fields"),
        ("reference", "references"),
        ("resolved_path", "resolved_paths"),
        ("command_name", "commands"),
        ("target_kind", "target_kinds"),
        ("method", "methods"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    network_executed = metadata.get("network_executed")
    if isinstance(network_executed, bool):
        summary["network_executed"] = network_executed
    remoting_executed = metadata.get("remoting_executed")
    if isinstance(remoting_executed, bool):
        summary["remoting_executed"] = remoting_executed
    return summary

def _powershell_manifest_dependency_edge_metadata(
    metadata: Mapping[str, Any]
) -> dict[str, Any]:
    summary = _powershell_reference_edge_metadata(
        metadata, "powershell.manifest_dependency"
    )
    for source_key, target_key in (
        ("dependency_kind", "dependency_kinds"),
        ("module_version", "module_versions"),
        ("required_version", "required_versions"),
        ("maximum_version", "maximum_versions"),
        ("guid", "guids"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    return summary

def _powershell_reference_source_metadata(source_key: str, path: str) -> dict[str, Any]:
    if source_key.startswith("powershell."):
        return _powershell_container_node_metadata(path)
    return {}

def _powershell_display_name(source_key: str, path: str) -> str:
    if source_key.startswith("powershell."):
        return path
    return _display_name_from_key(source_key)
