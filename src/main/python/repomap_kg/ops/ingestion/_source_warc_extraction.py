"""WARC record parsing, payload materialization, and observation extraction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.graph.keys import warc_record_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.source_warc import (
    _http_content_type,
    _next_warc_record,
    _normalise_warc_record_id,
    _parse_http_message_payload,
    _safe_warc_headers,
    _warc_payload_extension,
    _warc_payload_route,
    _warc_record_identity,
    _warc_target,
)
from repomap_kg.ops.ingestion.source_warc_records import (
    WarcManifest,
    WarcRecordSummary,
    WarcSourceConfig,
)

EXTRACTOR = "source-ingestion"
EXTRACTOR_VERSION = "0.1.0"


def _parse_warc_records(
    *,
    config: WarcSourceConfig,
    root: Path,
    artifact_path: Path,
    document_key: str,
    materialization_root: Path,
) -> tuple[list[WarcRecordSummary], str | None, list[str], list[str]]:
    data = artifact_path.read_bytes()
    offset = 0
    records: list[WarcRecordSummary] = []
    warnings: list[str] = []
    errors: list[str] = []
    warc_version: str | None = None
    total_payload_bytes = 0
    routed_files = 0
    seen_identity_counts: dict[str, int] = {}

    while offset < len(data):
        while offset < len(data) and data[offset : offset + 1] in (b"\r", b"\n"):
            offset += 1
        if offset >= len(data):
            break
        if len(records) >= config.max_warc_records:
            errors.append(f"max_warc_records exceeded: {config.max_warc_records}")
            break

        parsed = _next_warc_record(data, offset)
        if isinstance(parsed, str):
            errors.append(parsed)
            break
        (
            next_offset,
            version,
            headers,
            raw_header_bytes,
            block,
        ) = parsed
        if warc_version is None:
            warc_version = version

        total_record_bytes = len(raw_header_bytes) + len(block)
        if total_record_bytes > config.max_record_bytes:
            errors.append(
                f"max_record_bytes exceeded at record {len(records) + 1}: "
                f"{total_record_bytes} > {config.max_record_bytes}"
            )
            offset = next_offset
            continue

        record, payload_bytes = _warc_record_summary(
            config=config,
            root=root,
            document_key=document_key,
            materialization_root=materialization_root,
            ordinal=len(records) + 1,
            headers=headers,
            block=block,
            seen_identity_counts=seen_identity_counts,
            total_payload_bytes=total_payload_bytes,
            routed_files=routed_files,
        )
        if record.materialized_path is not None:
            routed_files += 1
            total_payload_bytes += payload_bytes
        records.append(record)
        offset = next_offset

    return records, warc_version, warnings, errors


def _warc_record_summary(
    *,
    config: WarcSourceConfig,
    root: Path,
    document_key: str,
    materialization_root: Path,
    ordinal: int,
    headers: Mapping[str, str],
    block: bytes,
    seen_identity_counts: dict[str, int],
    total_payload_bytes: int,
    routed_files: int,
) -> tuple[WarcRecordSummary, int]:
    record_type = headers.get("warc-type", "unknown").strip().lower() or "unknown"
    target_summary, target_key, target_redacted = _warc_target(headers.get("warc-target-uri"))
    identity, identity_source, identity_strength = _warc_record_identity(
        headers=headers,
        record_type=record_type,
        target_uri_summary=target_summary,
        ordinal=ordinal,
    )
    seen_identity_counts[identity] = seen_identity_counts.get(identity, 0) + 1
    duplicate_count = seen_identity_counts[identity]
    duplicate = duplicate_count > 1
    duplicate_disambiguator: str | None = None
    record_identity = identity
    if duplicate:
        duplicate_disambiguator = f"duplicate-{duplicate_count}"
        record_identity = f"{identity}:{duplicate_disambiguator}"
    record_key = warc_record_key(document_key, record_identity)
    content_type = headers.get("content-type")
    payload = b""
    payload_content_type = content_type
    extractor_route: str | None = None
    materialized_path: str | None = None
    skip_reason: str | None = None

    if record_type == "response":
        http_headers, payload = _parse_http_message_payload(block, response=True)
        payload_content_type = _http_content_type(http_headers) or content_type
        extractor_route = _warc_payload_route(payload_content_type)
    elif record_type == "resource":
        payload = block
        extractor_route = _warc_payload_route(payload_content_type)
    elif record_type in {
        "warcinfo",
        "request",
        "metadata",
        "revisit",
        "conversion",
    }:
        skip_reason = "metadata-only"
    elif record_type == "continuation":
        skip_reason = "continuation-deferred"
    else:
        skip_reason = "unsupported-record-type"

    payload_sha256: str | None = None
    routed_payload_bytes = 0
    if extractor_route is not None:
        if not payload:
            skip_reason = "empty-payload"
        elif total_payload_bytes + len(payload) > config.max_total_payload_bytes:
            skip_reason = "max_total_payload_bytes"
        elif routed_files >= config.max_file_count:
            skip_reason = "max_file_count"
        else:
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            materialized_path = _materialize_warc_payload(
                config=config,
                root=root,
                materialization_root=materialization_root,
                ordinal=ordinal,
                extractor_route=extractor_route,
                payload=payload,
            )
            routed_payload_bytes = len(payload)

    if materialized_path is None and skip_reason is None and extractor_route is None:
        skip_reason = "metadata-only"

    return (
        WarcRecordSummary(
            ordinal=ordinal,
            record_type=record_type,
            record_id=_normalise_warc_record_id(headers.get("warc-record-id")),
            record_key=record_key,
            identity_source=identity_source,
            identity_strength=identity_strength,
            duplicate_identity=duplicate,
            duplicate_disambiguator=duplicate_disambiguator,
            target_uri_summary=target_summary,
            target_key=target_key,
            target_uri_redacted=target_redacted,
            warc_date=headers.get("warc-date"),
            content_type=payload_content_type,
            payload_byte_length=len(payload),
            payload_sha256=payload_sha256,
            extractor_route=extractor_route,
            materialized_path=materialized_path,
            skip_reason=skip_reason,
            safe_headers=_safe_warc_headers(headers),
        ),
        routed_payload_bytes,
    )


def _materialize_warc_payload(
    *,
    config: WarcSourceConfig,
    root: Path,
    materialization_root: Path,
    ordinal: int,
    extractor_route: str,
    payload: bytes,
) -> str:
    extension = _warc_payload_extension(extractor_route)
    directory = materialization_root / f"record-{ordinal:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    payload_path = directory / f"payload{extension}"
    payload_path.write_bytes(payload)
    return payload_path.relative_to(root).as_posix()


def _warc_record_observations(
    manifest: WarcManifest,
    record: WarcRecordSummary,
    document_key: str,
) -> list[RawObservation]:
    path = manifest.artifact_path
    metadata = _warc_record_metadata(manifest, record, document_key)
    observations = [
        RawObservation(
            kind="warc.record",
            source_id=f"{path}#warc-record:{record.ordinal}",
            path=path,
            target=record.record_key,
            name=f"{record.record_type} record {record.ordinal}",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata=metadata,
        ),
        RawObservation(
            kind="warc.header",
            source_id=f"{path}#warc-header:{record.ordinal}",
            path=path,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata={
                **metadata,
                "safe_headers": dict(record.safe_headers),
            },
        ),
    ]
    if record.target_key is not None:
        observations.append(
            RawObservation(
                kind="warc.reference",
                source_id=f"{path}#warc-reference:{record.ordinal}",
                path=path,
                target=record.target_key,
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={
                    **metadata,
                    "source_key": record.record_key,
                    "target_key": record.target_key,
                    "reference_kind": "warc-target-uri",
                    "target_kind": record.target_key.split(":", 1)[0],
                    "not_fetched": True,
                },
            )
        )
    if record.payload_byte_length or record.materialized_path is not None:
        observations.append(
            RawObservation(
                kind="warc.payload",
                source_id=f"{path}#warc-payload:{record.ordinal}",
                path=record.materialized_path or path,
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={
                    **metadata,
                    "warc_payload_path": record.materialized_path,
                    "payload_sha256": record.payload_sha256,
                    "payload_materialized": record.materialized_path is not None,
                    "not_executed": True,
                    "not_rendered": True,
                },
            )
        )
    return observations


def _warc_record_metadata(
    manifest: WarcManifest,
    record: WarcRecordSummary,
    document_key: str,
) -> dict[str, Any]:
    return {
        "format": "warc",
        "warc_version": manifest.warc_version,
        "document_key": document_key,
        "record_key": record.record_key,
        "warc_record_key": record.record_key,
        "record_ordinal": record.ordinal,
        "record_type": record.record_type,
        "record_id": record.record_id,
        "identity_source": record.identity_source,
        "identity_strength": record.identity_strength,
        "duplicate_identity": record.duplicate_identity,
        "duplicate_disambiguator": record.duplicate_disambiguator,
        "target_uri_summary": record.target_uri_summary,
        "target_uri_redacted": record.target_uri_redacted,
        "warc_date": record.warc_date,
        "content_type": record.content_type,
        "payload_byte_length": record.payload_byte_length,
        "extractor_route": record.extractor_route,
        "skip_reason": record.skip_reason,
        "artifact_manifest_id": manifest.artifact_manifest_id,
        "artifact_run_id": manifest.artifact_run_id,
    }


def _annotate_warc_observations(
    observations: Sequence[RawObservation],
    config: WarcSourceConfig,
    manifest: WarcManifest,
    record_by_materialized_path: Mapping[str, WarcRecordSummary],
) -> tuple[RawObservation, ...]:
    annotated: list[RawObservation] = []
    for observation in observations:
        record = record_by_materialized_path.get(observation.path or "")
        metadata = {
            **dict(observation.metadata),
            "source_id": config.source_id,
            "source_id_configured": config.source_id,
            "source_type": config.source_type,
            "source_display_name": config.display_name,
            "source_policy_status": config.policy_status,
            "source_run_id": manifest.artifact_run_id,
            "source_artifact_id": manifest.artifact_manifest_id,
            "artifact_policy_status": config.policy_status,
            "artifact_run_id": manifest.artifact_run_id,
            "artifact_manifest_id": manifest.artifact_manifest_id,
            "artifact_profile": config.artifact_profile,
            "artifact_relative_path": observation.path,
            "source_artifact_path": observation.path,
            "artifact_retention_policy": config.retention_policy,
            "retention_policy": config.retention_policy,
            "config_redacted_keys": list(config.redacted_config_keys),
        }
        if record is not None:
            metadata.update(
                {
                    "warc_record_ordinal": record.ordinal,
                    "warc_record_key": record.record_key,
                    "warc_record_type": record.record_type,
                    "warc_payload_path": record.materialized_path,
                    "artifact_byte_length": record.payload_byte_length,
                    "source_artifact_bytes": record.payload_byte_length,
                    "artifact_sha256": record.payload_sha256,
                    "source_artifact_sha256": record.payload_sha256,
                    "artifact_extractor_route": record.extractor_route,
                }
            )
        annotated.append(replace(observation, metadata=metadata))
    return tuple(annotated)
