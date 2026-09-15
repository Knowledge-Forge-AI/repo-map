"""Bulk/API manifest summary records and payload decoders."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from repomap_kg.storage._summary_rows_api_manifest import (
    APISummaryRecord,
    api_manifest_summary_payload,
    api_summary_from_storage_payload,
    read_api_manifest_payloads,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    manifest_counter,
    manifest_int,
    manifest_list,
    optional_manifest_text,
    payload_bool,
    payload_count_map,
    payload_int,
    payload_optional_text,
    payload_string_tuple,
    payload_text,
)

__all__ = (
    "BulkSummaryRecord",
    "APISummaryRecord",
    "bulk_manifest_summary_payload",
    "read_bulk_manifest_payloads",
    "api_manifest_summary_payload",
    "read_api_manifest_payloads",
    "bulk_summary_from_storage_payload",
    "api_summary_from_storage_payload",
)


@dataclass(frozen=True)
class BulkSummaryRecord:
    root_path_summary: str
    repository_name: str | None
    bulk_runs: int
    sources: int
    source_ids: tuple[str, ...]
    corpus_kinds: dict[str, int]
    policy_statuses: dict[str, int]
    file_count_included: int
    file_count_skipped: int
    total_bytes_included: int
    extractor_counts: dict[str, int]
    skip_reasons: dict[str, int]
    diagnostic_counts: dict[str, int]
    redaction_counts: dict[str, int]
    limit_hit_count: int
    max_files_hit_count: int
    max_total_bytes_hit_count: int
    max_file_bytes_hit_count: int
    max_depth_hit_count: int
    archive_deferred: int
    warc_deferred: int
    email_export_runs: int
    mixed_corpus_runs: int
    observations_with_bulk_provenance: int
    no_provider_api: bool
    no_external_fetch: bool
    no_source_mutation: bool
    no_archive_decompression: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bulk_manifest_summary_payload(root_path: Path) -> dict[str, Any]:
    resolved_root = root_path.resolve()
    run_root = resolved_root / ".repomap" / "bulk-runs"
    manifests = read_bulk_manifest_payloads(run_root, root_path=resolved_root)
    source_ids: set[str] = set()
    run_ids: set[str] = set()
    corpus_kinds: Counter[str] = Counter()
    policy_statuses: Counter[str] = Counter()
    extractor_counts: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    redaction_counts: Counter[str] = Counter()
    file_count_included = 0
    file_count_skipped = 0
    total_bytes_included = 0
    limit_hit_count = 0
    max_files_hit_count = 0
    max_total_bytes_hit_count = 0
    max_file_bytes_hit_count = 0
    max_depth_hit_count = 0

    for manifest in manifests:
        if manifest.get("_manifest_parse_error"):
            diagnostic_counts["manifest_parse_error"] += 1
            continue
        source_id = optional_manifest_text(manifest, "source_id")
        run_id = optional_manifest_text(manifest, "bulk_run_id")
        corpus_kind = optional_manifest_text(manifest, "corpus_kind")
        policy_status = optional_manifest_text(manifest, "policy_status")
        if source_id is not None:
            source_ids.add(source_id)
        if run_id is not None:
            run_ids.add(run_id)
        if corpus_kind is not None:
            corpus_kinds[corpus_kind] += 1
        if policy_status is not None:
            policy_statuses[policy_status] += 1
        file_count_included += manifest_int(manifest, "file_count_included")
        file_count_skipped += manifest_int(manifest, "file_count_skipped")
        total_bytes_included += manifest_int(manifest, "total_bytes_included")
        extractor_counts.update(manifest_counter(manifest.get("extractor_counts")))
        diagnostic_counts.update(manifest_counter(manifest.get("diagnostic_counts")))
        redaction_counts.update(manifest_counter(manifest.get("redaction_counts")))
        for skipped_file in manifest_list(manifest.get("skipped_files")):
            reason = optional_manifest_text(skipped_file, "reason")
            if reason is not None:
                skip_reasons[reason] += 1
        if manifest.get("limit_hit") is True:
            limit_hit_count += 1
            limit_reason = optional_manifest_text(manifest, "limit_reason") or ""
            reasons = {item.strip() for item in limit_reason.split(",") if item.strip()}
            if "max_files_exceeded" in reasons:
                max_files_hit_count += 1
            if "max_total_bytes_exceeded" in reasons:
                max_total_bytes_hit_count += 1
            if "max_file_bytes_exceeded" in reasons:
                max_file_bytes_hit_count += 1
            if "max_depth_exceeded" in reasons:
                max_depth_hit_count += 1

    return {
        "root_path_summary": ".",
        "repository_name": None,
        "bulk_runs": len(run_ids),
        "sources": len(source_ids),
        "source_ids": sorted(source_ids),
        "corpus_kinds": dict(sorted(corpus_kinds.items())),
        "policy_statuses": dict(sorted(policy_statuses.items())),
        "file_count_included": file_count_included,
        "file_count_skipped": file_count_skipped,
        "total_bytes_included": total_bytes_included,
        "extractor_counts": dict(sorted(extractor_counts.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
        "redaction_counts": dict(sorted(redaction_counts.items())),
        "limit_hit_count": limit_hit_count,
        "max_files_hit_count": max_files_hit_count,
        "max_total_bytes_hit_count": max_total_bytes_hit_count,
        "max_file_bytes_hit_count": max_file_bytes_hit_count,
        "max_depth_hit_count": max_depth_hit_count,
        "archive_deferred": skip_reasons.get("archive_deferred", 0),
        "warc_deferred": skip_reasons.get("warc_deferred", 0),
        "email_export_runs": sum(
            corpus_kinds.get(kind, 0)
            for kind in ("email_export", "eml_export", "mbox_export")
        ),
        "mixed_corpus_runs": corpus_kinds.get("mixed_corpus", 0),
        "observations_with_bulk_provenance": 0,
        "no_provider_api": True,
        "no_external_fetch": True,
        "no_source_mutation": True,
        "no_archive_decompression": True,
    }


def read_bulk_manifest_payloads(
    run_root: Path,
    *,
    root_path: Path,
) -> tuple[dict[str, Any], ...]:
    if not run_root.is_dir():
        return ()
    resolved_run_root = run_root.resolve()
    try:
        resolved_run_root.relative_to(root_path)
    except ValueError:
        return ({"_manifest_parse_error": True},)
    payloads: list[dict[str, Any]] = []
    for manifest_path in sorted(run_root.glob("*/*/manifest.json")):
        try:
            resolved_manifest = manifest_path.resolve()
            resolved_manifest.relative_to(resolved_run_root)
            payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payloads.append({"_manifest_parse_error": True})
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        else:
            payloads.append({"_manifest_parse_error": True})
    return tuple(payloads)


def bulk_summary_from_storage_payload(payload: Any) -> BulkSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed bulk summary")
    return BulkSummaryRecord(
        root_path_summary=payload_text(
            payload,
            "root_path_summary",
            label="bulk summary",
        ),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="bulk summary",
        ),
        bulk_runs=payload_int(payload, "bulk_runs", label="bulk summary"),
        sources=payload_int(payload, "sources", label="bulk summary"),
        source_ids=payload_string_tuple(
            payload,
            "source_ids",
            label="bulk summary",
        ),
        corpus_kinds=payload_count_map(
            payload,
            "corpus_kinds",
            label="bulk summary",
        ),
        policy_statuses=payload_count_map(
            payload,
            "policy_statuses",
            label="bulk summary",
        ),
        file_count_included=payload_int(
            payload,
            "file_count_included",
            label="bulk summary",
        ),
        file_count_skipped=payload_int(
            payload,
            "file_count_skipped",
            label="bulk summary",
        ),
        total_bytes_included=payload_int(
            payload,
            "total_bytes_included",
            label="bulk summary",
        ),
        extractor_counts=payload_count_map(
            payload,
            "extractor_counts",
            label="bulk summary",
        ),
        skip_reasons=payload_count_map(
            payload,
            "skip_reasons",
            label="bulk summary",
        ),
        diagnostic_counts=payload_count_map(
            payload,
            "diagnostic_counts",
            label="bulk summary",
        ),
        redaction_counts=payload_count_map(
            payload,
            "redaction_counts",
            label="bulk summary",
        ),
        limit_hit_count=payload_int(
            payload,
            "limit_hit_count",
            label="bulk summary",
        ),
        max_files_hit_count=payload_int(
            payload,
            "max_files_hit_count",
            label="bulk summary",
        ),
        max_total_bytes_hit_count=payload_int(
            payload,
            "max_total_bytes_hit_count",
            label="bulk summary",
        ),
        max_file_bytes_hit_count=payload_int(
            payload,
            "max_file_bytes_hit_count",
            label="bulk summary",
        ),
        max_depth_hit_count=payload_int(
            payload,
            "max_depth_hit_count",
            label="bulk summary",
        ),
        archive_deferred=payload_int(
            payload,
            "archive_deferred",
            label="bulk summary",
        ),
        warc_deferred=payload_int(
            payload,
            "warc_deferred",
            label="bulk summary",
        ),
        email_export_runs=payload_int(
            payload,
            "email_export_runs",
            label="bulk summary",
        ),
        mixed_corpus_runs=payload_int(
            payload,
            "mixed_corpus_runs",
            label="bulk summary",
        ),
        observations_with_bulk_provenance=payload_int(
            payload,
            "observations_with_bulk_provenance",
            label="bulk summary",
        ),
        no_provider_api=payload_bool(
            payload,
            "no_provider_api",
            label="bulk summary",
        ),
        no_external_fetch=payload_bool(
            payload,
            "no_external_fetch",
            label="bulk summary",
        ),
        no_source_mutation=payload_bool(
            payload,
            "no_source_mutation",
            label="bulk summary",
        ),
        no_archive_decompression=payload_bool(
            payload,
            "no_archive_decompression",
            label="bulk summary",
        ),
    )
