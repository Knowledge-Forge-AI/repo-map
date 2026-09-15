"""Storage readback JSONable projection helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from repomap_kg.storage.canonical_readback_rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
)
from repomap_kg.storage.source_rows import (
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
)
from repomap_kg.storage.summary_rows_domains import (
    EmailSummaryRecord,
    OpenAPISummaryRecord,
    TerraformSummaryRecord,
)
from repomap_kg.storage.summary_rows_languages import (
    JSFrameworkSummaryRecord,
    JSSummaryRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
)
from repomap_kg.storage.summary_rows_manifest import (
    APISummaryRecord,
    BulkSummaryRecord,
)
from repomap_kg.storage.summary_rows_nix import NixSummaryRecord
from repomap_kg.storage.summary_rows_storage import CanonicalStorageSummaryRecord

__all__ = (
    "canonical_node_records_to_jsonable",
    "canonical_edge_records_to_jsonable",
    "canonical_edge_explanation_to_jsonable",
    "canonical_neighborhood_to_jsonable",
    "canonical_storage_summary_to_jsonable",
    "ruby_summary_to_jsonable",
    "js_summary_to_jsonable",
    "js_framework_summary_to_jsonable",
    "openapi_summary_to_jsonable",
    "terraform_summary_to_jsonable",
    "python_summary_to_jsonable",
    "nix_summary_to_jsonable",
    "email_summary_to_jsonable",
    "bulk_summary_to_jsonable",
    "api_summary_to_jsonable",
    "ingested_source_records_to_jsonable",
    "source_summary_to_jsonable",
    "source_run_records_to_jsonable",
    "source_feed_item_records_to_jsonable",
    "source_reference_records_to_jsonable",
)


def canonical_node_records_to_jsonable(
    records: Sequence[CanonicalNodeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def canonical_edge_records_to_jsonable(
    records: Sequence[CanonicalEdgeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def canonical_edge_explanation_to_jsonable(
    record: CanonicalEdgeExplanationRecord,
) -> dict[str, Any]:
    return record.to_dict()


def canonical_neighborhood_to_jsonable(
    record: CanonicalNeighborhoodRecord,
) -> dict[str, Any]:
    return record.to_dict()


def canonical_storage_summary_to_jsonable(
    record: CanonicalStorageSummaryRecord,
) -> dict[str, Any]:
    return record.to_dict()


def ruby_summary_to_jsonable(record: RubySummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def js_summary_to_jsonable(record: JSSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def js_framework_summary_to_jsonable(
    record: JSFrameworkSummaryRecord,
) -> dict[str, Any]:
    return record.to_dict()


def openapi_summary_to_jsonable(record: OpenAPISummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def terraform_summary_to_jsonable(record: TerraformSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def python_summary_to_jsonable(record: PythonSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def nix_summary_to_jsonable(record: NixSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def email_summary_to_jsonable(record: EmailSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def bulk_summary_to_jsonable(record: BulkSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def api_summary_to_jsonable(record: APISummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def ingested_source_records_to_jsonable(
    records: Sequence[IngestedSourceRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_summary_to_jsonable(record: SourceSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def source_run_records_to_jsonable(
    records: Sequence[SourceRunRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_feed_item_records_to_jsonable(
    records: Sequence[SourceFeedItemRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_reference_records_to_jsonable(
    records: Sequence[SourceReferenceRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]
