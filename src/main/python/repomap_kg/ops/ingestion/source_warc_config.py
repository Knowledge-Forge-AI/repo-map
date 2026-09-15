"""Policy-gated WARC source configuration parsing."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion.source_common import (
    SourcePolicyError,
    _mapping,
    _optional_bool,
    _optional_text,
    _reject_archive_network_fields,
    _required_positive_int,
    _required_text,
    _secret_key_paths,
    _validate_disallowed_flags,
    _validate_local_artifact_path,
    _validate_policy_status,
    _validate_source_id,
    _validate_warc_source_type,
)
from repomap_kg.ops.ingestion.source_warc_records import WarcSourceConfig


def load_warc_source_config(path: Path | str) -> WarcSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    _reject_archive_network_fields(payload)
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    artifact = _mapping(payload, "artifact")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_file_count = _required_positive_int(
        policy,
        "max_file_count",
        "policy.max_file_count",
    )
    max_warc_records = _required_positive_int(
        policy,
        "max_warc_records",
        "policy.max_warc_records",
    )
    max_record_bytes = _required_positive_int(
        policy,
        "max_record_bytes",
        "policy.max_record_bytes",
    )
    max_total_payload_bytes = _required_positive_int(
        policy,
        "max_total_payload_bytes",
        "policy.max_total_payload_bytes",
    )
    retention_policy = _required_text(
        policy,
        "retention_policy",
        "policy.retention_policy",
    )
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )
    artifact_path = _required_text(artifact, "path", "artifact.path")
    artifact_kind = _required_text(artifact, "kind", "artifact.kind")
    artifact_profile = _required_text(artifact, "profile", "artifact.profile")

    _validate_source_id(source_id)
    _validate_warc_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before WARC import")
    if artifact_kind != "warc":
        raise SourcePolicyError("artifact.kind must be warc")
    _validate_local_artifact_path(artifact_path)

    return WarcSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        max_artifact_bytes=max_artifact_bytes,
        max_file_count=max_file_count,
        max_warc_records=max_warc_records,
        max_record_bytes=max_record_bytes,
        max_total_payload_bytes=max_total_payload_bytes,
        retention_policy=retention_policy,
        requires_manual_review=requires_manual_review,
        artifact_path=artifact_path,
        artifact_kind=artifact_kind,
        artifact_profile=artifact_profile,
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def _warc_policy_snapshot(config: WarcSourceConfig) -> dict[str, Any]:
    return {
        "status": config.policy_status,
        "max_artifact_bytes": config.max_artifact_bytes,
        "max_file_count": config.max_file_count,
        "max_warc_records": config.max_warc_records,
        "max_record_bytes": config.max_record_bytes,
        "max_total_payload_bytes": config.max_total_payload_bytes,
        "retention_policy": config.retention_policy,
        "requires_manual_review": config.requires_manual_review,
    }
