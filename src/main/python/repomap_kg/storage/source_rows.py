"""Source-ingestion storage readback records and payload decoders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    payload_int,
    payload_optional_bool,
    payload_optional_int,
    payload_optional_text,
    payload_string_tuple,
    payload_text,
)

__all__ = (
    "IngestedSourceRecord",
    "SourceSummaryRecord",
    "SourceRunRecord",
    "SourceFeedItemRecord",
    "SourceReferenceRecord",
    "ingested_source_record_from_storage_payload",
    "source_summary_from_storage_payload",
    "source_run_record_from_storage_payload",
    "source_feed_item_record_from_storage_payload",
    "source_reference_record_from_storage_payload",
)


@dataclass(frozen=True)
class IngestedSourceRecord:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    latest_source_run_id: str | None
    latest_artifact_id: str | None
    latest_artifact_path: str | None
    latest_acquired_at: str | None
    feed_observation_count: int
    canonical_feed_item_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceSummaryRecord:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    configured_url_summary: str | None
    latest_source_run_id: str | None
    latest_artifact_id: str | None
    latest_artifact_path: str | None
    latest_acquired_at: str | None
    feed_documents: int
    feed_channels: int
    feed_items: int
    feed_authors: int
    feed_categories: int
    link_references: int
    enclosure_references: int
    parse_errors: int
    known_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceRunRecord:
    source_run_id: str
    acquired_at: str | None
    artifact_id: str | None
    artifact_path: str | None
    artifact_byte_length: int | None
    artifact_sha256: str | None
    http_status: int | None
    content_type: str | None
    observation_count: int
    status_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceFeedItemRecord:
    item_key: str
    title: str | None
    published_at: str | None
    updated_at: str | None
    identity_source: str | None
    identity_strength: str | None
    duplicate_identity: bool
    link_targets: tuple[str, ...]
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    source_run_id: str | None
    artifact_id: str | None
    artifact_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceReferenceRecord:
    source_item_key: str
    relation: str
    target_key: str
    target_display: str | None
    not_fetched: bool
    media_type: str | None
    source_run_id: str | None
    artifact_id: str | None
    artifact_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ingested_source_record_from_storage_payload(payload: Any) -> IngestedSourceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed ingested source record")
    return IngestedSourceRecord(
        source_id=payload_text(payload, "source_id", label="ingested source record"),
        source_type=payload_text(payload, "source_type", label="ingested source record"),
        display_name=payload_optional_text(
            payload,
            "display_name",
            label="ingested source record",
        ),
        policy_status=payload_text(
            payload,
            "policy_status",
            label="ingested source record",
        ),
        latest_source_run_id=payload_optional_text(
            payload,
            "latest_source_run_id",
            label="ingested source record",
        ),
        latest_artifact_id=payload_optional_text(
            payload,
            "latest_artifact_id",
            label="ingested source record",
        ),
        latest_artifact_path=payload_optional_text(
            payload,
            "latest_artifact_path",
            label="ingested source record",
        ),
        latest_acquired_at=payload_optional_text(
            payload,
            "latest_acquired_at",
            label="ingested source record",
        ),
        feed_observation_count=payload_int(
            payload,
            "feed_observation_count",
            label="ingested source record",
        ),
        canonical_feed_item_count=payload_int(
            payload,
            "canonical_feed_item_count",
            label="ingested source record",
        ),
    )


def source_summary_from_storage_payload(payload: Any) -> SourceSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source summary")
    return SourceSummaryRecord(
        source_id=payload_text(payload, "source_id", label="source summary"),
        source_type=payload_optional_text(
            payload,
            "source_type",
            label="source summary",
        )
        or "unknown",
        display_name=payload_optional_text(
            payload,
            "display_name",
            label="source summary",
        ),
        policy_status=payload_text(payload, "policy_status", label="source summary"),
        configured_url_summary=payload_optional_text(
            payload,
            "configured_url_summary",
            label="source summary",
        ),
        latest_source_run_id=payload_optional_text(
            payload,
            "latest_source_run_id",
            label="source summary",
        ),
        latest_artifact_id=payload_optional_text(
            payload,
            "latest_artifact_id",
            label="source summary",
        ),
        latest_artifact_path=payload_optional_text(
            payload,
            "latest_artifact_path",
            label="source summary",
        ),
        latest_acquired_at=payload_optional_text(
            payload,
            "latest_acquired_at",
            label="source summary",
        ),
        feed_documents=payload_int(payload, "feed_documents", label="source summary"),
        feed_channels=payload_int(payload, "feed_channels", label="source summary"),
        feed_items=payload_int(payload, "feed_items", label="source summary"),
        feed_authors=payload_int(payload, "feed_authors", label="source summary"),
        feed_categories=payload_int(
            payload,
            "feed_categories",
            label="source summary",
        ),
        link_references=payload_int(
            payload,
            "link_references",
            label="source summary",
        ),
        enclosure_references=payload_int(
            payload,
            "enclosure_references",
            label="source summary",
        ),
        parse_errors=payload_int(payload, "parse_errors", label="source summary"),
        known_limitations=payload_string_tuple(
            payload,
            "known_limitations",
            label="source summary",
        ),
    )


def source_run_record_from_storage_payload(payload: Any) -> SourceRunRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source run record")
    return SourceRunRecord(
        source_run_id=payload_text(payload, "source_run_id", label="source run record"),
        acquired_at=payload_optional_text(
            payload,
            "acquired_at",
            label="source run record",
        ),
        artifact_id=payload_optional_text(
            payload,
            "artifact_id",
            label="source run record",
        ),
        artifact_path=payload_optional_text(
            payload,
            "artifact_path",
            label="source run record",
        ),
        artifact_byte_length=payload_optional_int(
            payload,
            "artifact_byte_length",
            label="source run record",
        ),
        artifact_sha256=payload_optional_text(
            payload,
            "artifact_sha256",
            label="source run record",
        ),
        http_status=payload_optional_int(
            payload,
            "http_status",
            label="source run record",
        ),
        content_type=payload_optional_text(
            payload,
            "content_type",
            label="source run record",
        ),
        observation_count=payload_int(
            payload,
            "observation_count",
            label="source run record",
        ),
        status_summary=payload_text(
            payload,
            "status_summary",
            label="source run record",
        ),
    )


def source_feed_item_record_from_storage_payload(payload: Any) -> SourceFeedItemRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source feed item record")
    return SourceFeedItemRecord(
        item_key=payload_text(payload, "item_key", label="source feed item record"),
        title=payload_optional_text(
            payload,
            "title",
            label="source feed item record",
        ),
        published_at=payload_optional_text(
            payload,
            "published_at",
            label="source feed item record",
        ),
        updated_at=payload_optional_text(
            payload,
            "updated_at",
            label="source feed item record",
        ),
        identity_source=payload_optional_text(
            payload,
            "identity_source",
            label="source feed item record",
        ),
        identity_strength=payload_optional_text(
            payload,
            "identity_strength",
            label="source feed item record",
        ),
        duplicate_identity=payload_optional_bool(
            payload,
            "duplicate_identity",
            label="source feed item record",
        )
        or False,
        link_targets=payload_string_tuple(
            payload,
            "link_targets",
            label="source feed item record",
        ),
        authors=payload_string_tuple(payload, "authors", label="source feed item record"),
        categories=payload_string_tuple(
            payload, "categories", label="source feed item record"
        ),
        source_run_id=payload_optional_text(
            payload, "source_run_id", label="source feed item record"
        ),
        artifact_id=payload_optional_text(
            payload, "artifact_id", label="source feed item record"
        ),
        artifact_path=payload_optional_text(
            payload, "artifact_path", label="source feed item record"
        ),
    )


def source_reference_record_from_storage_payload(payload: Any) -> SourceReferenceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source reference record")
    return SourceReferenceRecord(
        source_item_key=payload_text(payload, "source_item_key", label="source reference record"),
        relation=payload_text(payload, "relation", label="source reference record"),
        target_key=payload_text(payload, "target_key", label="source reference record"),
        target_display=payload_optional_text(
            payload, "target_display", label="source reference record"
        ),
        not_fetched=payload_optional_bool(
            payload, "not_fetched", label="source reference record"
        )
        or False,
        media_type=payload_optional_text(payload, "media_type", label="source reference record"),
        source_run_id=payload_optional_text(
            payload, "source_run_id", label="source reference record"
        ),
        artifact_id=payload_optional_text(
            payload, "artifact_id", label="source reference record"
        ),
        artifact_path=payload_optional_text(
            payload, "artifact_path", label="source reference record"
        ),
    )
