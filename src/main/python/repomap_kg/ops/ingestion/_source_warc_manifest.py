"""WARC manifest building, observation generation, and import coordination."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.languages.python import PythonModuleIndex
from repomap_kg.graph.discovery import classify_path
from repomap_kg.graph.keys import warc_document_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._source_warc_extraction import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    _annotate_warc_observations,
    _parse_warc_records,
    _warc_record_observations,
)
from repomap_kg.ops.ingestion.acquisition_contracts import non_publication_result
from repomap_kg.ops.ingestion.source_archive import (
    _observations_for_archive_file,
    _resolve_archive_artifact_path,
)
from repomap_kg.ops.ingestion.source_common import (
    SourcePolicyError,
    _utc_now,
    json_dumps_stable,
)
from repomap_kg.ops.ingestion.source_warc_config import (
    _warc_policy_snapshot,
    load_warc_source_config,
)
from repomap_kg.ops.ingestion.source_warc_records import (
    WarcImportSummary,
    WarcManifest,
    WarcSourceConfig,
)

Clock = Callable[[], datetime]


def build_warc_manifest(
    config: WarcSourceConfig,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> WarcManifest:
    root = Path(root_path).resolve()
    artifact_path = _resolve_archive_artifact_path(root, config.artifact_path)
    if artifact_path.is_symlink():
        raise SourcePolicyError("artifact.path must not be a symlink")
    if not artifact_path.is_file():
        raise SourcePolicyError("artifact.path must be an existing WARC file")
    if artifact_path.suffix != ".warc":
        raise SourcePolicyError("WARC1 supports local .warc files only")
    artifact_bytes = artifact_path.stat().st_size
    if artifact_bytes > config.max_artifact_bytes:
        raise SourcePolicyError("artifact exceeds policy.max_artifact_bytes")
    now = clock() if clock is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    artifact_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    document_key = warc_document_key(config.artifact_path)
    materialization_root = (
        root
        / ".repomap"
        / "source-artifacts"
        / config.source_id
        / artifact_run_id
        / "warc-payloads"
    )
    records, warc_version, warnings, errors = _parse_warc_records(
        config=config,
        root=root,
        artifact_path=artifact_path,
        document_key=document_key,
        materialization_root=materialization_root,
    )
    policy_snapshot = _warc_policy_snapshot(config)
    manifest_payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "policy_status": config.policy_status,
        "artifact_run_id": artifact_run_id,
        "artifact_profile": config.artifact_profile,
        "artifact_path": config.artifact_path,
        "warc_version": warc_version,
        "records": [record.to_jsonable() for record in records],
        "policy_snapshot": policy_snapshot,
        "warnings": list(warnings),
        "errors": list(errors),
    }
    artifact_manifest_id = hashlib.sha256(
        json_dumps_stable(manifest_payload).encode("utf-8")
    ).hexdigest()[:16]
    return WarcManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=artifact_run_id,
        artifact_manifest_id=artifact_manifest_id,
        artifact_profile=config.artifact_profile,
        artifact_path=config.artifact_path,
        warc_version=warc_version,
        records=tuple(records),
        policy_snapshot=policy_snapshot,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def warc_observations_from_manifest(
    config: WarcSourceConfig,
    manifest: WarcManifest,
    *,
    root_path: Path | str,
) -> tuple[RawObservation, ...]:
    root = Path(root_path).resolve()
    document_key = warc_document_key(manifest.artifact_path)
    observations: list[RawObservation] = [
        RawObservation(
            kind="warc.document",
            source_id=f"{manifest.artifact_path}#warc-document",
            path=manifest.artifact_path,
            target=document_key,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata={
                "format": "warc",
                "warc_version": manifest.warc_version,
                "parser": "stdlib-bytes",
                "parser_mode": "plain-warc-local-only",
                "record_count": manifest.record_count,
                "parsed_record_count": manifest.parsed_record_count,
                "skipped_record_count": manifest.skipped_record_count,
                "routed_payload_count": manifest.routed_payload_count,
                "artifact_manifest_id": manifest.artifact_manifest_id,
            },
        )
    ]
    record_by_materialized_path = {
        record.materialized_path: record
        for record in manifest.records
        if record.materialized_path is not None
    }
    for record in manifest.records:
        observations.extend(_warc_record_observations(manifest, record, document_key))
    for index, message in enumerate(manifest.errors):
        observations.append(
            RawObservation(
                kind="warc.parse_error",
                source_id=f"{manifest.artifact_path}#warc-parse-error:{index}",
                path=manifest.artifact_path,
                confidence="unknown",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={"error_kind": "warc-parse", "message": message},
            )
        )
    routed_infos = [
        classify_path(root, root / relative_path)
        for relative_path in sorted(record_by_materialized_path)
    ]
    module_index = PythonModuleIndex.from_python_paths((), repository_root=root)
    repository_paths = frozenset(file_info.path for file_info in routed_infos)
    markdown_anchors: dict[str, frozenset[str]] = {}
    routed_observations: list[RawObservation] = []
    for file_info in routed_infos:
        routed_observations.extend(
            _observations_for_archive_file(
                root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
    routed_observations.extend(
        extract_css_selector_match_observations(routed_observations)
    )
    observations.extend(routed_observations)
    return _annotate_warc_observations(
        observations,
        config,
        manifest,
        record_by_materialized_path,
    )


def import_warc_source(
    config_path: Path | str,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> WarcImportSummary:
    config = load_warc_source_config(config_path)
    manifest = build_warc_manifest(config, root_path=root_path, clock=clock)
    observations = warc_observations_from_manifest(
        config,
        manifest,
        root_path=root_path,
    )
    return WarcImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=manifest.artifact_run_id,
        artifact_manifest_id=manifest.artifact_manifest_id,
        record_count=manifest.record_count,
        parsed_records=manifest.parsed_record_count,
        skipped_records=manifest.skipped_record_count,
        routed_payloads=manifest.routed_payload_count,
        observations=len(observations),
        raw_observations=tuple(observations),
        manifest=manifest,
        publication=non_publication_result(),
    )
