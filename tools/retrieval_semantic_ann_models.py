"""Immutable JSON, plan, candidate, and result models for W5 HNSW."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import TypeAlias


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
CandidateIdentity: TypeAlias = tuple[str, str]
SourceSnapshotPair: TypeAlias = tuple[str, str]
HnswSourceScope: TypeAlias = tuple[SourceSnapshotPair, ...]

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EVIDENCE_FIELDS = frozenset({
    "evidence_key", "path", "start_line", "end_line", "raw_kind", "extractor",
    "extractor_version", "confidence",
})
_CANDIDATE_FIELDS = frozenset({
    "node_id", "canonical_key", "kind", "display_name", "confidence", "conflict",
    "source_binding_id", "input_digest", "snapshot_id", "distance", "evidence",
})


class HnswExecutionState(StrEnum):
    COMPLETED = "completed"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"
    REFUSED = "refused"
    FAILED = "failed"


class HnswEvaluationError(ValueError):
    """Sanitized evaluator contract failure with a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class HnswPlanSummary:
    node_types: tuple[str, ...]
    index_names: tuple[str, ...]
    actual_rows: int
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int
    used_expected_index: bool
    used_seq_scan: bool
    distance_order_present: bool
    planner_forced: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "node_types": list(self.node_types), "index_names": list(self.index_names),
            "actual_rows": self.actual_rows, "planning_time_ms": self.planning_time_ms,
            "execution_time_ms": self.execution_time_ms, "shared_hit_blocks": self.shared_hit_blocks,
            "shared_read_blocks": self.shared_read_blocks, "used_expected_index": self.used_expected_index,
            "used_seq_scan": self.used_seq_scan, "distance_order_present": self.distance_order_present,
            "planner_forced": self.planner_forced,
        }


@dataclass(frozen=True, slots=True)
class HnswCandidate:
    node_id: int
    canonical_key: str
    source_binding_id: str
    raw_rank: int
    cosine_distance: float
    input_digest: str
    snapshot_id: str
    kind: str | None
    display_name: str | None
    evidence: tuple[JsonObject, ...]

    @property
    def identity(self) -> CandidateIdentity:
        return self.canonical_key, self.source_binding_id


@dataclass(frozen=True, slots=True)
class HnswRecallSummary:
    exact_count: int
    ann_count: int
    overlap_at_k: int
    recall_at_k: float | None
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "exact_count": self.exact_count, "ann_count": self.ann_count,
            "overlap_at_k": self.overlap_at_k, "recall_at_k": self.recall_at_k,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class HnswProvenance:
    repository_identity: str
    run_id: int
    receipt_identity: str
    profile_identity: str
    rebuild_id: str
    index_name: str
    query_digest: str
    attempt_identity: str
    source_scope: HnswSourceScope
    dimensions: int
    ef_search: int
    iterative_scan: str
    ann_scan_limit: int
    owner_identity: str
    baseline_sql_digest: str
    privacy_class: str = "public"
    search: str = "hnsw-disposable"
    input_digest_validation: str = "enrichment_principal_assertion"

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_identity": self.repository_identity, "run_id": self.run_id,
            "receipt_identity": self.receipt_identity, "profile_identity": self.profile_identity,
            "rebuild_id": self.rebuild_id, "index_name": self.index_name,
            "query_digest": self.query_digest, "attempt_identity": self.attempt_identity,
            "source_scope": [list(pair) for pair in self.source_scope],
            "dimensions": self.dimensions, "ef_search": self.ef_search,
            "iterative_scan": self.iterative_scan, "ann_scan_limit": self.ann_scan_limit,
            "owner_identity": self.owner_identity, "baseline_sql_digest": self.baseline_sql_digest,
            "privacy_class": self.privacy_class, "search": self.search,
            "input_digest_validation": self.input_digest_validation,
        }


@dataclass(frozen=True, slots=True)
class HnswResult:
    state: HnswExecutionState
    reason: str | None
    candidates: tuple[HnswCandidate, ...]
    plan: HnswPlanSummary | None
    recall: HnswRecallSummary | None
    provenance: HnswProvenance | None

    @property
    def truncated(self) -> bool:
        """Expose filter/scan underfill without turning it into absence."""
        return self.recall is not None and self.recall.truncated

    @property
    def recall_status(self) -> str:
        if self.recall is not None:
            return "known"
        if self.reason is not None and self.reason.startswith("exact_baseline_"):
            return "unknown_exact_baseline"
        return "not_measured"

    @property
    def truncation_status(self) -> str:
        return self.recall_status

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value, "reason": self.reason,
            "truncated": self.truncated, "recall_status": self.recall_status,
            "truncation_status": self.truncation_status,
            "candidates": [
                {"node_id": c.node_id, "canonical_key": c.canonical_key,
                 "source_binding_id": c.source_binding_id,
                 "raw_rank": c.raw_rank, "cosine_distance": c.cosine_distance,
                 "input_digest": c.input_digest, "snapshot_id": c.snapshot_id,
                 "kind": c.kind, "display_name": c.display_name, "evidence": c.evidence}
                for c in self.candidates
            ],
            "plan": None if self.plan is None else self.plan.to_dict(),
            "recall": None if self.recall is None else self.recall.to_dict(),
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
        }


def finite_number(value: object, code: str) -> float:
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    else:
        raise HnswEvaluationError(code, "expected a finite number")
    if not math.isfinite(number):
        raise HnswEvaluationError(code, "expected a finite number")
    return number


def nonnegative_int(value: object, code: str) -> int:
    if type(value) is not int or value < 0:
        raise HnswEvaluationError(code, "expected a non-negative integer")
    return value


def optional_text(row: Mapping[str, JsonValue], field: str) -> str | None:
    value = row.get(field)
    if value is not None and type(value) is not str:
        raise HnswEvaluationError("malformed_ann_payload", f"{field} is not text")
    return value


def evidence_fields() -> frozenset[str]:
    return _EVIDENCE_FIELDS


def candidate_fields() -> frozenset[str]:
    return _CANDIDATE_FIELDS


def digest_matches(value: str) -> bool:
    return _DIGEST.fullmatch(value) is not None
