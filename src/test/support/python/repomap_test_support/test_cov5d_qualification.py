"""Public-safe TEST-COV5D semantic characterization support."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from itertools import permutations
from typing import Callable, Mapping

from repomap_test_support.test_cov5c_qualification import (
    build_evidence,
)
from scale28_preparation_authority import HybridPreparationAuthority
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationDeadlinePolicy,
)
from scale28_preparation_worker import PreparationWorkerResult


SOURCE_MANIFEST_DIGEST = (
    "3f505bb7a53f83f8b34289df35998a3b24705d1e0ff0114116d85cc3e4f2eb1a"
)
SEMANTIC_GROUPS = (
    "close_order",
    "source_causality",
    "terminal_claim",
    "reacquisition",
    "postgres_cancellation",
    "request_round_trip_stability",
)
SOURCE_CODES = (
    "threshold_limit_crossed",
    "ambient_client_detected",
    "backend_ownership_unknown",
    "event_transport_eof",
    "event_transport_failed",
    "resource_reader_unavailable",
    "backend_observer_failed",
    "backend_quiescence_timeout",
    "child_exit_unavailable",
    "cleanup_eligibility_unproved",
    "terminal_resource_unavailable",
)
SOURCE_ORDER_SCHEDULES = (
    tuple(permutations(SOURCE_CODES, 2))
    + tuple(permutations(SOURCE_CODES, 3))[:90]
)
REACQUISITION_FIRST_FAILURES = {
    "stale_receipt": ("preparation_stale", "receipt"),
    "scope_mismatch": ("preparation_scope_mismatch", "request"),
    "generation_mismatch": ("preparation_generation_mismatch", "request"),
    "observation_overflow": ("preparation_observation_overflow", "observation"),
    "ack_timeout": ("preparation_ack_timeout", "acknowledgement"),
    "wrong_ack": ("preparation_ack_invalid", "acknowledgement"),
    "receipt_mismatch": ("preparation_receipt_invalid", "receipt"),
    "worker_crash": ("preparation_worker_crashed", "worker"),
    "worker_signal": ("preparation_worker_signaled", "worker"),
    "subordinate_cleanup_mismatch": (
        "preparation_subordinate_cleanup_mismatch",
        "terminal",
    ),
    "process_unsettled": ("preparation_process_unsettled", "terminal"),
    "observer_failure": ("backend_observer_failed", "observer"),
}
REACQUISITION_SECOND_OUTCOMES = {
    "success": None,
    "failure": ("preparation_second_attempt_failed", "worker"),
    "stale": ("preparation_stale", "receipt"),
}


def case_token(case_id: str) -> str:
    """Bind one semantic operation to its externally visible case identity."""

    if not isinstance(case_id, str) or not case_id:
        raise ValueError("semantic case id is invalid")
    return hashlib.sha256(case_id.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class ObservedSemanticResult:
    """One source-observed result before manifest admission."""

    actual_category: str
    cleanup_disposition: str
    case_evidence_token: str
    payload: Mapping[str, object]
    source_observed: bool = True

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "actual_category": self.actual_category,
                "case_evidence_token": self.case_evidence_token,
                "cleanup_disposition": self.cleanup_disposition,
                "payload": dict(self.payload),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    """One typed semantic authority admitted from observed evidence."""

    authority_id: str
    semantic_group: str
    case_id: str
    operation_kind: str
    entry_point: str
    result_digest: str
    expected_contract_category: str
    actual_category: str
    cleanup_disposition: str
    source_manifest_digest: str


@dataclass(frozen=True, slots=True)
class ContractComparison:
    """Accepted tree, available candidate, required contract, and exact gap."""

    accepted_tree: str
    candidate_tree: str
    required_contract: str
    remaining_gap: str

    def validate(self) -> ContractComparison:
        values = (
            self.accepted_tree,
            self.candidate_tree,
            self.required_contract,
            self.remaining_gap,
        )
        if any(
            not isinstance(value, str) or not value or len(value) > 256
            for value in values
        ):
            raise ValueError("contract comparison is invalid")
        if self.accepted_tree != self.candidate_tree:
            raise ValueError("unavailable candidate tree is claimed")
        return self


class QualificationManifest:
    """Validate and group source-frozen semantic characterization records."""

    def __init__(
        self,
        *,
        required_group_counts: Mapping[str, int],
        source_manifest_digest: str = SOURCE_MANIFEST_DIGEST,
    ) -> None:
        if (
            not required_group_counts
            or any(
                group not in SEMANTIC_GROUPS
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 1
                for group, count in required_group_counts.items()
            )
        ):
            raise ValueError("qualification manifest requirements are invalid")
        self._required = dict(required_group_counts)
        self._source_manifest_digest = source_manifest_digest
        self._records: list[QualificationRecord] = []
        self._authority_ids: set[str] = set()
        self._semantic_cases: set[tuple[str, str]] = set()

    def add(
        self,
        record: QualificationRecord,
        observed: ObservedSemanticResult,
        *,
        current_source_manifest_digest: str = SOURCE_MANIFEST_DIGEST,
    ) -> None:
        """Admit one independently observed and digest-bound record."""

        if record.authority_id in self._authority_ids:
            raise ValueError("qualification authority id is duplicate")
        semantic_case = (record.semantic_group, record.case_id)
        if semantic_case in self._semantic_cases:
            raise ValueError("qualification semantic case is duplicate")
        if record.semantic_group not in self._required:
            raise ValueError("qualification semantic group is unexpected")
        if (
            record.operation_kind == "preparation_request_round_trip"
            and record.semantic_group != "request_round_trip_stability"
        ):
            raise ValueError("request round trip is mislabeled")
        if not observed.source_observed:
            raise ValueError("qualification actual category is not observed")
        if observed.case_evidence_token != case_token(record.case_id):
            raise ValueError("qualification case parameter is unused")
        if observed.cleanup_disposition != "exact":
            raise ValueError("qualification cleanup is missing")
        if (
            record.source_manifest_digest != self._source_manifest_digest
            or current_source_manifest_digest != self._source_manifest_digest
        ):
            raise ValueError("qualification production source changed")
        if (
            record.result_digest != observed.digest
            or record.actual_category != observed.actual_category
            or record.cleanup_disposition != observed.cleanup_disposition
        ):
            raise ValueError("qualification result digest mismatches")
        self._authority_ids.add(record.authority_id)
        self._semantic_cases.add(semantic_case)
        self._records.append(record)

    def finish(self) -> dict[str, tuple[QualificationRecord, ...]]:
        """Return separate complete groups without an aggregate authority."""

        grouped = {
            group: tuple(
                record
                for record in self._records
                if record.semantic_group == group
            )
            for group in self._required
        }
        if any(
            len(grouped[group]) != required
            for group, required in self._required.items()
        ):
            raise ValueError("qualification manifest group is incomplete")
        return grouped


def observed_result(
    case_id: str,
    actual_category: str,
    *,
    payload: Mapping[str, object] | None = None,
    source_observed: bool = True,
) -> ObservedSemanticResult:
    """Construct a result as if returned by the selected test entry point."""

    return ObservedSemanticResult(
        actual_category=actual_category,
        cleanup_disposition="exact",
        case_evidence_token=case_token(case_id),
        payload=payload or {"selected_case": case_id},
        source_observed=source_observed,
    )


def qualification_record(
    *,
    authority_id: str,
    semantic_group: str,
    case_id: str,
    operation_kind: str,
    entry_point: str,
    expected_contract_category: str,
    observed: ObservedSemanticResult,
) -> QualificationRecord:
    """Bind one test-observed result into the frozen record schema."""

    return QualificationRecord(
        authority_id=authority_id,
        semantic_group=semantic_group,
        case_id=case_id,
        operation_kind=operation_kind,
        entry_point=entry_point,
        result_digest=observed.digest,
        expected_contract_category=expected_contract_category,
        actual_category=observed.actual_category,
        cleanup_disposition=observed.cleanup_disposition,
        source_manifest_digest=SOURCE_MANIFEST_DIGEST,
    )


class _InjectedAttemptError(RuntimeError):
    category: str
    boundary: str

    def __init__(self, message: str, *, category: str, boundary: str) -> None:
        super().__init__(message)
        self.category = category
        self.boundary = boundary


class _ReacquisitionAttempt:
    def __init__(
        self,
        request,
        outcome: tuple[str, str] | None,
        clock: Callable[[], int],
    ) -> None:
        self._request = request
        self._outcome = outcome
        self._clock = clock

    def run(self) -> PreparationWorkerResult:
        if self._outcome is not None:
            category, boundary = self._outcome
            raise _InjectedAttemptError(
                "public-safe preparation attempt failure",
                category=category,
                boundary=boundary,
            )
        evidence = build_evidence(expectations=self._request.expectations)
        observed = self._clock()
        return PreparationWorkerResult(
            evidence,
            observation_received_parent_ns=observed,
            receipt_received_parent_ns=observed + 1,
            worker_settled_parent_ns=observed + 2,
            worker_pid=123,
            attempt_elapsed_parent_ns=50_000_000,
        )


@dataclass(frozen=True, slots=True)
class _ResourceSpecification:
    digest: str = hashlib.sha256(b"test-cov5d-resource-specification").hexdigest()


def build_reacquisition_authority(
    *,
    first_failure: str,
    second_outcome: str,
    clock: Callable[[], int],
) -> tuple[HybridPreparationAuthority, list[object]]:
    """Build one two-attempt authority with a selected distinct failure path."""

    outcomes = iter(
        (
            REACQUISITION_FIRST_FAILURES[first_failure],
            REACQUISITION_SECOND_OUTCOMES[second_outcome],
        )
    )
    attempts: list[object] = []
    nonces = iter(("c" * 32, "d" * 32))
    policy = PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=1_000,
        maximum_attempts=2,
    )

    def attempt_factory(request, _specification, _policy):
        attempts.append(request.expectations)
        return _ReacquisitionAttempt(request, next(outcomes), clock)

    authority = HybridPreparationAuthority(
        _ResourceSpecification(),
        {
            field: hashlib.sha256(field.encode("ascii")).hexdigest()
            for field in BINDING_FIELDS
        },
        policy,
        clock_ns=clock,
        nonce_factory=nonces.__next__,
        attempt_factory=attempt_factory,
    )
    return authority, attempts


__all__ = [
    "ContractComparison",
    "ObservedSemanticResult",
    "QualificationManifest",
    "QualificationRecord",
    "REACQUISITION_FIRST_FAILURES",
    "REACQUISITION_SECOND_OUTCOMES",
    "SEMANTIC_GROUPS",
    "SOURCE_CODES",
    "SOURCE_MANIFEST_DIGEST",
    "SOURCE_ORDER_SCHEDULES",
    "build_reacquisition_authority",
    "case_token",
    "observed_result",
    "qualification_record",
]
