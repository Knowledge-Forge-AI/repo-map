"""Generic storage and load summary row records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from repomap_kg.storage.row_helpers import (
    payload_int,
    payload_optional_int,
    payload_optional_text,
    payload_text,
)

__all__ = (
    "LoadSummary",
    "CanonicalLoadSummary",
    "CanonicalStorageSummaryRecord",
    "load_summary_from_payload",
    "canonical_load_summary_from_payload",
    "canonical_storage_summary_from_payload",
)


@dataclass(frozen=True)
class LoadSummary:
    repository_id: int
    run_id: int
    files: int
    publication_receipt: RunPublicationReceipt | None = None

    @property
    def publication_generations(self):
        return None if self.publication_receipt is None else self.publication_receipt.generations


@dataclass(frozen=True)
class CanonicalLoadSummary:
    repository_id: int
    run_id: int
    raw_observations: int
    canonical_nodes: int
    canonical_edges: int
    canonical_evidence: int
    canonical_node_evidence_links: int
    canonical_edge_evidence_links: int


@dataclass(frozen=True)
class CanonicalStorageSummaryRecord:
    root_path: str
    repository_name: str | None
    latest_run_id: int | None
    runs: int
    files: int
    raw_observations: int
    canonical_nodes: int
    canonical_edges: int
    canonical_evidence: int
    raw_observations_total: int | None = None
    latest_run_raw_observations: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["raw_observations_total"] is None:
            payload["raw_observations_total"] = self.raw_observations
        return payload


def canonical_storage_summary_from_payload(
    payload: Any,
) -> CanonicalStorageSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical storage summary"
        )
    raw_observations = payload_int(
        payload,
        "raw_observations",
        label="canonical storage summary",
    )
    raw_observations_total = payload_optional_int(
        payload,
        "raw_observations_total",
        label="canonical storage summary",
    )
    return CanonicalStorageSummaryRecord(
        root_path=payload_text(
            payload,
            "root_path",
            label="canonical storage summary",
        ),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="canonical storage summary",
        ),
        latest_run_id=payload_optional_int(
            payload,
            "latest_run_id",
            label="canonical storage summary",
        ),
        runs=payload_int(payload, "runs", label="canonical storage summary"),
        files=payload_int(payload, "files", label="canonical storage summary"),
        raw_observations=raw_observations,
        raw_observations_total=(
            raw_observations_total
            if raw_observations_total is not None
            else raw_observations
        ),
        latest_run_raw_observations=payload_optional_int(
            payload,
            "latest_run_raw_observations",
            label="canonical storage summary",
        ),
        canonical_nodes=payload_int(
            payload,
            "canonical_nodes",
            label="canonical storage summary",
        ),
        canonical_edges=payload_int(
            payload,
            "canonical_edges",
            label="canonical storage summary",
        ),
        canonical_evidence=payload_int(
            payload,
            "canonical_evidence",
            label="canonical storage summary",
        ),
    )


def load_summary_from_payload(payload: Any) -> LoadSummary:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed load summary")
    try:
        return LoadSummary(
            repository_id=int(payload["repository_id"]),
            run_id=int(payload["run_id"]),
            files=int(payload["files"]),
            publication_receipt=publication_receipt_from_mapping(payload),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError("psql returned a malformed load summary") from error


def canonical_load_summary_from_payload(payload: Any) -> CanonicalLoadSummary:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical load summary")
    try:
        return CanonicalLoadSummary(
            repository_id=int(payload["repository_id"]),
            run_id=int(payload["run_id"]),
            raw_observations=int(payload["raw_observations"]),
            canonical_nodes=int(payload["canonical_nodes"]),
            canonical_edges=int(payload["canonical_edges"]),
            canonical_evidence=int(payload["canonical_evidence"]),
            canonical_node_evidence_links=int(
                payload["canonical_node_evidence_links"]
            ),
            canonical_edge_evidence_links=int(
                payload["canonical_edge_evidence_links"]
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError(
            "psql returned a malformed canonical load summary"
        ) from error
