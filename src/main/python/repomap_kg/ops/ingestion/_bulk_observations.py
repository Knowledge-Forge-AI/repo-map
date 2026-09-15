"""Observation extraction, annotation, and disk writing for bulk ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._bulk_helpers import (
    ensure_contained,
    write_json,
    write_jsonl,
)
from repomap_kg.ops.ingestion.bulk_records import (
    BulkIncludedFile,
    BulkManifest,
    BulkSourceConfig,
)




def annotate_observation(
    observation: RawObservation,
    *,
    config: BulkSourceConfig,
    manifest: BulkManifest,
    included: BulkIncludedFile,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "corpus_kind": config.corpus_kind,
            "bulk_run_id": manifest.bulk_run_id,
            "bulk_manifest_id": manifest.bulk_manifest_id,
            "bulk_relative_path": included.relative_path,
            "bulk_file_sha256": included.sha256,
            "bulk_file_byte_count": included.byte_count,
            "bulk_extractor_route": included.route,
            "bulk_policy_status": config.policy_status,
            "bulk_retention_policy": config.retention_policy,
            "bulk_sensitivity": config.sensitivity,
        }
    )
    return replace(observation, metadata=metadata)


def write_bulk_run_files(
    manifest: BulkManifest,
    *,
    observations: Sequence[RawObservation],
    repository_root: Path,
) -> Path:
    output_path = (
        repository_root
        / ".repomap"
        / "bulk-runs"
        / manifest.source_id
        / manifest.bulk_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "bulk output path")
    output_path.mkdir(parents=True, exist_ok=True)
    write_json(output_path / "plan.json", manifest.to_jsonable())
    write_json(output_path / "manifest.json", manifest.to_jsonable())
    write_jsonl(
        output_path / "included-files.jsonl",
        [item.to_jsonable() for item in manifest.included_files],
    )
    write_jsonl(
        output_path / "skipped-files.jsonl",
        [item.to_jsonable() for item in manifest.skipped_files],
    )
    write_jsonl(
        output_path / "diagnostics.jsonl",
        [
            {"reason": reason, "count": count}
            for reason, count in sorted(manifest.diagnostic_counts.items())
        ],
    )
    write_jsonl(
        output_path / "observations.jsonl",
        [observation.to_dict() for observation in observations],
    )
    return output_path
