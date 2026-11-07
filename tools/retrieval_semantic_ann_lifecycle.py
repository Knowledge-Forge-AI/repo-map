"""Source-only lifecycle receipts and cost accounting for disposable HNSW."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Literal

from retrieval_semantic_ann_contracts import (
    FixedDdlExecutor,
    HnswCleanupReport,
    HnswIndexCatalogState,
    IndexCatalogReader,
    cleanup_owned_hnsw_index,
    verify_hnsw_index_catalog,
)
from retrieval_semantic_ann_sql import HnswIndexSpec, build_hnsw_index_create_sql
from common_lore_index.storage.semantic_candidates import checked_identity


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
EmbeddingImportStatus = Literal["external_not_measured", "measured"]
CleanupStatus = Literal["verified_absent", "failed", "ownership_refused"]


def _seconds(value: float, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"invalid {field}")
    return float(value)


def _bytes(value: int, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid {field}")
    return value


def _digest(value: str, field: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    return value


def _optional_reason(value: str | None) -> str | None:
    if value is not None and _REASON.fullmatch(value) is None:
        raise ValueError("invalid lifecycle failure reason")
    return value


@dataclass(frozen=True, slots=True)
class HnswCostEvidence:
    """Complete HNSW lifecycle measurements; embedding import is explicit external scope."""

    lifecycle_wall_seconds: float
    index_build_wall_seconds: float
    explain_wall_seconds: float
    query_wall_seconds: float
    index_footprint_bytes: int
    work_candidates_inspected: int
    embedding_import_status: EmbeddingImportStatus
    embedding_import_wall_seconds: float | None = None

    def validate(self) -> HnswCostEvidence:
        for value, field in (
            (self.lifecycle_wall_seconds, "lifecycle wall time"),
            (self.index_build_wall_seconds, "index build wall time"),
            (self.explain_wall_seconds, "EXPLAIN wall time"),
            (self.query_wall_seconds, "query wall time"),
        ):
            _seconds(value, field)
        _bytes(self.index_footprint_bytes, "index footprint")
        _bytes(self.work_candidates_inspected, "candidate work")
        if self.embedding_import_status not in {"external_not_measured", "measured"}:
            raise ValueError("invalid embedding import measurement status")
        if self.embedding_import_status == "external_not_measured":
            if self.embedding_import_wall_seconds is not None:
                raise ValueError("external import cannot carry a measured duration")
        elif self.embedding_import_wall_seconds is None:
            raise ValueError("measured import requires a duration")
        else:
            _seconds(self.embedding_import_wall_seconds, "embedding import wall time")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "lifecycle_wall_seconds": self.lifecycle_wall_seconds,
            "index_build_wall_seconds": self.index_build_wall_seconds,
            "explain_wall_seconds": self.explain_wall_seconds,
            "query_wall_seconds": self.query_wall_seconds,
            "index_footprint_bytes": self.index_footprint_bytes,
            "work_candidates_inspected": self.work_candidates_inspected,
            "embedding_import_status": self.embedding_import_status,
            "embedding_import_wall_seconds": self.embedding_import_wall_seconds,
        }


@dataclass(frozen=True, slots=True)
class HnswCreationReceipt:
    """Hash-bound proof that this invocation created and owned the exact index."""

    attempt_identity: str
    spec: HnswIndexSpec
    index_oid: int
    table_oid: int
    index_owner: str
    current_user: str
    definition_digest: str
    predicate_digest: str
    created: bool

    def validate(self) -> HnswCreationReceipt:
        checked_identity(self.attempt_identity)
        self.spec.validate()
        if self.spec.attempt_identity != self.attempt_identity:
            raise ValueError("HNSW creation receipt attempt identity differs from index spec")
        if type(self.index_oid) is not int or self.index_oid <= 0:
            raise ValueError("invalid HNSW index OID")
        if type(self.table_oid) is not int or self.table_oid <= 0:
            raise ValueError("invalid HNSW table OID")
        if self.index_owner != self.spec.owner_identity or self.current_user != self.spec.owner_identity:
            raise ValueError("HNSW creation owner is not the invocation owner")
        _digest(self.definition_digest, "index definition digest")
        _digest(self.predicate_digest, "index predicate digest")
        if type(self.created) is not bool or not self.created:
            raise ValueError("HNSW creation receipt must prove a fresh creation")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "attempt_identity": self.attempt_identity,
            "index_name": self.spec.name,
            "rebuild_id": self.spec.rebuild_id,
            "query_digest": self.spec.query_digest,
            "index_attempt_identity": self.spec.attempt_identity,
            "owner_identity": self.spec.owner_identity,
            "index_oid": self.index_oid,
            "table_oid": self.table_oid,
            "index_owner": self.index_owner,
            "current_user": self.current_user,
            "definition_digest": self.definition_digest,
            "predicate_digest": self.predicate_digest,
            "created": self.created,
        }


def cleanup_created_hnsw_index(
    receipt: HnswCreationReceipt,
    *,
    read_catalog: IndexCatalogReader,
    execute_ddl: FixedDdlExecutor,
) -> HnswCleanupReport:
    """Clean only the OIDs proved by this invocation's creation receipt."""
    receipt.validate()
    return cleanup_owned_hnsw_index(
        receipt.spec,
        expected_index_oid=receipt.index_oid,
        expected_table_oid=receipt.table_oid,
        read_catalog=read_catalog,
        execute_ddl=execute_ddl,
    )


def capture_creation_receipt(
    precreation_state: HnswIndexCatalogState,
    state: HnswIndexCatalogState,
    spec: HnswIndexSpec,
    *,
    attempt_identity: str,
    definition_digest: str | None = None,
    predicate_digest: str | None = None,
) -> HnswCreationReceipt:
    """Convert an owner-run catalog readback into a creation receipt; no SQL is run.

    Digests are derived from the accepted catalog readback.  Optional caller
    values are retained only as assertions, so a receipt cannot be minted from
    an unrelated hash supplied by the caller.
    """
    if precreation_state.present:
        raise ValueError("HNSW name was occupied before invocation; adoption is forbidden")
    reason = verify_hnsw_index_catalog(state, spec)
    if reason is not None:
        raise ValueError(f"HNSW catalog is not accepted: {reason}")
    assert state.index_oid is not None and state.table_oid is not None
    assert state.index_owner is not None and state.current_user is not None
    assert state.index_schema is not None and state.index_name is not None
    assert state.table_schema is not None and state.table_name is not None
    assert state.access_method is not None and state.opclass_schema is not None
    assert state.opclass_name is not None and state.expression is not None
    assert state.predicate is not None
    observed_definition_digest = digest_catalog_expression("|".join((
        state.index_schema, state.index_name, state.table_schema, state.table_name,
        state.access_method, state.opclass_schema, state.opclass_name, state.expression,
        build_hnsw_index_create_sql(spec),
    )))
    observed_predicate_digest = digest_catalog_expression(state.predicate)
    if definition_digest is not None and definition_digest != observed_definition_digest:
        raise ValueError("HNSW definition digest does not match catalog readback")
    if predicate_digest is not None and predicate_digest != observed_predicate_digest:
        raise ValueError("HNSW predicate digest does not match catalog readback")
    return HnswCreationReceipt(
        attempt_identity, spec, state.index_oid, state.table_oid,
        state.index_owner, state.current_user, observed_definition_digest,
        observed_predicate_digest, True,
    ).validate()


@dataclass(frozen=True, slots=True)
class HnswCleanupDisposition:
    status: CleanupStatus
    primary_reason: str | None
    report: HnswCleanupReport

    @classmethod
    def from_report(
        cls, primary_reason: str | None, report: HnswCleanupReport
    ) -> HnswCleanupDisposition:
        report.validate()
        if report.verified_absent:
            status: CleanupStatus = "verified_absent"
        elif report.ownership_refused:
            status = "ownership_refused"
        else:
            status = "failed"
        return cls(status, primary_reason, report).validate()

    def validate(self) -> HnswCleanupDisposition:
        self.report.validate()
        if self.status not in {"verified_absent", "failed", "ownership_refused"}:
            raise ValueError("invalid HNSW cleanup status")
        if self.status == "verified_absent" and not self.report.verified_absent:
            raise ValueError("verified cleanup status lacks absence proof")
        if self.status == "ownership_refused" and not self.report.ownership_refused:
            raise ValueError("ownership refusal status lacks refusal proof")
        if self.status == "failed" and self.report.failure_code is None:
            raise ValueError("failed cleanup status lacks failure code")
        _optional_reason(self.primary_reason)
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "status": self.status,
            "primary_reason": self.primary_reason,
            "report": self.report.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class HnswLifecycleReceipt:
    """Retain primary execution failure and cleanup outcome together."""

    attempt_identity: str
    creation: HnswCreationReceipt
    cost: HnswCostEvidence
    cleanup: HnswCleanupDisposition

    def validate(self) -> HnswLifecycleReceipt:
        checked_identity(self.attempt_identity)
        self.creation.validate()
        self.cost.validate()
        self.cleanup.validate()
        if self.creation.attempt_identity != self.attempt_identity:
            raise ValueError("creation receipt attempt identity differs")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "attempt_identity": self.attempt_identity,
            "creation": self.creation.to_dict(),
            "cost": self.cost.to_dict(),
            "cleanup": self.cleanup.to_dict(),
        }


def digest_catalog_expression(value: str) -> str:
    """Hash catalog text for a receipt without retaining raw SQL in public output."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
