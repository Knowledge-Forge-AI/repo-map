"""Raw observation constructors for Bash side effects."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.base import slug
from repomap_kg.extractors.shell.bash_common import EXTRACTOR, bash_metadata
from repomap_kg.extractors.shell.bash_side_effect_rules import target_metadata
from repomap_kg.observations.raw import RawObservation


def file_effect_observation(
    kind: str,
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    operation: str,
    target: str | None,
    via: str,
    context: dict[str, Any],
) -> RawObservation:
    metadata = target_metadata(target)
    metadata.update(
        {
            "command_source_id": command_source_id,
            "command_name": command_name,
            "operation": operation,
            "via": via,
        }
    )
    metadata.update(context)
    return RawObservation(
        kind=kind,
        source_id=f"{command_source_id}:{kind}:{slug(operation)}:{slug(metadata['target_display'] or 'none')}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def file_effect_observation_from_metadata(
    kind: str,
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    operation: str,
    target_metadata: dict[str, Any],
    suffix: str,
    via: str,
    context: dict[str, Any],
) -> RawObservation:
    metadata = {
        "command_source_id": command_source_id,
        "command_name": command_name,
        "operation": operation,
        "via": via,
        "target_kind": target_metadata["target_kind"],
        "target_display": target_metadata["target_display"],
        "target_redacted": target_metadata["target_redacted"],
        "raw_value_stored": target_metadata["raw_value_stored"],
    }
    metadata.update(context)
    return RawObservation(
        kind=kind,
        source_id=f"{command_source_id}:{kind}:{suffix}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def network_call_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    target: str | None,
    context: dict[str, Any],
) -> RawObservation:
    metadata = target_metadata(target)
    metadata.update(
        {
            "command_source_id": command_source_id,
            "command_name": command_name,
            "operation": command_name,
            "network_executed": False,
        }
    )
    metadata.update(context)
    return RawObservation(
        kind="shell.network_call",
        source_id=f"{command_source_id}:network:{slug(metadata['target_display'] or 'none')}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def host_mutation_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    mutation_category: str,
    operation: str,
    target: str | None,
    destructive: bool,
    privileged: bool,
    context: dict[str, Any],
) -> RawObservation:
    metadata = target_metadata(target)
    metadata.update(
        {
            "command_source_id": command_source_id,
            "mutation_category": mutation_category,
            "operation": operation,
            "command_name": command_name,
            "original_token": command_name,
            "target_value_stored": metadata["raw_value_stored"],
            "destructive": destructive,
            "privileged": privileged,
        }
    )
    metadata.update(context)
    return RawObservation(
        kind="shell.host_mutation",
        source_id=f"{command_source_id}:host:{slug(mutation_category)}:{slug(operation)}:{slug(metadata['target_display'] or 'none')}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=mutation_category,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def host_mutation_from_target_metadata(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    mutation_category: str,
    operation: str,
    target_metadata: dict[str, Any],
    destructive: bool,
    suffix: str,
    context: dict[str, Any],
) -> RawObservation:
    metadata = {
        "command_source_id": command_source_id,
        "mutation_category": mutation_category,
        "operation": operation,
        "command_name": command_name,
        "original_token": command_name,
        "target_kind": target_metadata["target_kind"],
        "target_display": target_metadata["target_display"],
        "target_redacted": target_metadata["target_redacted"],
        "target_value_stored": target_metadata["raw_value_stored"],
        "destructive": destructive,
        "privileged": False,
    }
    metadata.update(context)
    return RawObservation(
        kind="shell.host_mutation",
        source_id=f"{command_source_id}:host:{suffix}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=mutation_category,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )
