"""Claim-scoped timing qualification for cancellation-request evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import ipaddress
import json
import platform
import re
from typing import Iterable

import psycopg

from repomap_test_support.test_cov5g_r1_characterization import (
    RequestObservation,
    RequestOutcome,
)


CANCELLATION_REQUEST_TIMING_CLAIM = "cancellation_request_timing"
EXPECTED_TIMING_OBSERVATIONS = 500
NON_SUCCESS_MANIFEST_LIMIT = 20
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PUBLIC_OUTCOME = re.compile(r"[a-z][a-z0-9_]{0,63}")


class TimingQualificationDisposition(str, Enum):
    """Closed pre-observation authority for timing acceptance."""

    QUALIFIED = "qualified_timing_runtime"
    UNQUALIFIED = "unqualified_timing_runtime"


@dataclass(frozen=True, slots=True)
class TimingRuntimeIdentity:
    """Public-safe identity for cancellation-request timing authority."""

    os_family: str
    os_release: str
    machine_architecture: str
    python_implementation: str
    python_version: str
    psycopg_version: str
    psycopg_implementation: str
    libpq_version: str
    postgresql_server_version: str
    transport_class: str

    def to_mapping(self) -> dict[str, str]:
        """Return the exact public-safe identity fields."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class TimingQualificationReceipt:
    """One independently accepted authority for the exact timing claim."""

    claim: str
    phase_id: str
    outcome: str
    runtime_identity: TimingRuntimeIdentity
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class TimingQualificationDecision:
    """Frozen runtime disposition selected before empirical observations."""

    runtime_identity: TimingRuntimeIdentity
    disposition: TimingQualificationDisposition
    accepted_receipt_phase_id: str | None
    accepted_receipt_digest: str | None


@dataclass(frozen=True, slots=True)
class NonSuccessManifestEntry:
    """One closed public-safe timing-deviation diagnostic."""

    cohort: str
    condition: str
    case_number: int
    request_outcome: str
    request_elapsed_ms: float
    operation_outcome: str


@dataclass(frozen=True, slots=True)
class NonSuccessManifest:
    """Bounded timing-deviation evidence for one observed campaign."""

    total_non_successes: int
    omitted_non_successes: int
    entries: tuple[NonSuccessManifestEntry, ...]

    def to_json(self) -> str:
        """Serialize only the closed manifest schema."""

        return json.dumps(
            {
                "total_non_successes": self.total_non_successes,
                "omitted_non_successes": self.omitted_non_successes,
                "entries": [asdict(entry) for entry in self.entries],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class TimingQualificationAssessment:
    """Outcome of applying the frozen decision to one complete campaign."""

    disposition: TimingQualificationDisposition
    sample_count: int
    non_success_count: int
    timing_acceptance_applied: bool
    timing_qualification_accepted: bool | None


def classify_postgres_transport(host: str) -> str:
    """Classify a Postgres endpoint without retaining its address."""

    if not isinstance(host, str) or not host:
        raise ValueError("Postgres transport host is invalid")
    if host.casefold() == "localhost":
        return "loopback_tcp"
    try:
        return (
            "loopback_tcp"
            if ipaddress.ip_address(host).is_loopback
            else "tcp"
        )
    except ValueError:
        return "tcp"


def capture_timing_runtime_identity(
    *,
    postgresql_server_version: str,
    transport_class: str,
) -> TimingRuntimeIdentity:
    """Capture claim-scoped identity without granting qualification."""

    if not postgresql_server_version or transport_class not in {
        "loopback_tcp",
        "tcp",
    }:
        raise ValueError("timing runtime identity input is invalid")
    return TimingRuntimeIdentity(
        os_family=platform.system(),
        os_release=platform.release(),
        machine_architecture=platform.machine(),
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        psycopg_version=psycopg.__version__,
        psycopg_implementation=str(getattr(psycopg.pq, "__impl__", "unknown")),
        libpq_version=str(psycopg.pq.version()),
        postgresql_server_version=postgresql_server_version,
        transport_class=transport_class,
    )


def decide_timing_qualification(
    identity: TimingRuntimeIdentity,
    accepted_receipt: TimingQualificationReceipt | None,
) -> TimingQualificationDecision:
    """Freeze timing authority from identity and accepted receipt only."""

    matches = (
        isinstance(accepted_receipt, TimingQualificationReceipt)
        and accepted_receipt.claim == CANCELLATION_REQUEST_TIMING_CLAIM
        and accepted_receipt.outcome == "A"
        and bool(accepted_receipt.phase_id)
        and _SHA256.fullmatch(accepted_receipt.receipt_digest) is not None
        and accepted_receipt.runtime_identity == identity
    )
    if not matches:
        return TimingQualificationDecision(
            runtime_identity=identity,
            disposition=TimingQualificationDisposition.UNQUALIFIED,
            accepted_receipt_phase_id=None,
            accepted_receipt_digest=None,
        )
    assert accepted_receipt is not None
    return TimingQualificationDecision(
        runtime_identity=identity,
        disposition=TimingQualificationDisposition.QUALIFIED,
        accepted_receipt_phase_id=accepted_receipt.phase_id,
        accepted_receipt_digest=accepted_receipt.receipt_digest,
    )


def verify_portable_observation(
    observation: RequestObservation,
) -> RequestObservation:
    """Require portable structural and cleanup safety on every runtime."""

    failed = tuple(
        name
        for name, accepted in (
            ("request_settled", observation.request_settled is True),
            ("operation_settled", observation.operation_settled is True),
            ("close_eligible", observation.close_eligible is True),
            ("close_count", observation.close_count == 1),
            ("backend_disappeared", observation.backend_disappeared is True),
            ("cleanup_succeeded", observation.cleanup_succeeded is True),
        )
        if not accepted
    )
    if failed:
        raise AssertionError(
            "portable cancellation safety failed: " + ",".join(failed)
        )
    return observation


def _safe_operation_outcome(value: object) -> str:
    if isinstance(value, str) and _PUBLIC_OUTCOME.fullmatch(value):
        return value
    return "unavailable_operation_outcome"


def _safe_request_outcome(value: object) -> str:
    if isinstance(value, RequestOutcome):
        return value.value
    return "invalid_request_outcome"


def build_non_success_manifest(
    observations: Iterable[RequestObservation],
) -> NonSuccessManifest:
    """Project natural timing deviations into bounded public-safe evidence."""

    non_successes = tuple(
        observation
        for observation in observations
        if (
            observation.request_outcome is not RequestOutcome.SUCCESS
            or observation.operation_outcome == "ordinary_completion"
        )
    )
    entries = tuple(
        NonSuccessManifestEntry(
            cohort=observation.cohort,
            condition=observation.condition.value,
            case_number=observation.case_number,
            request_outcome=_safe_request_outcome(observation.request_outcome),
            request_elapsed_ms=round(observation.request_elapsed_ms, 3),
            operation_outcome=_safe_operation_outcome(
                observation.operation_outcome
            ),
        )
        for observation in non_successes[:NON_SUCCESS_MANIFEST_LIMIT]
    )
    return NonSuccessManifest(
        total_non_successes=len(non_successes),
        omitted_non_successes=len(non_successes) - len(entries),
        entries=entries,
    )


def verify_timing_qualification_acceptance(
    decision: TimingQualificationDecision,
    observations: Iterable[RequestObservation],
) -> TimingQualificationAssessment:
    """Apply timing acceptance only when pre-observation authority exists."""

    selected = tuple(observations)
    if len(selected) != EXPECTED_TIMING_OBSERVATIONS:
        raise AssertionError("timing campaign sample count changed")
    manifest = build_non_success_manifest(selected)
    if decision.disposition is TimingQualificationDisposition.UNQUALIFIED:
        return TimingQualificationAssessment(
            disposition=decision.disposition,
            sample_count=len(selected),
            non_success_count=manifest.total_non_successes,
            timing_acceptance_applied=False,
            timing_qualification_accepted=None,
        )
    if manifest.total_non_successes:
        raise AssertionError(
            "qualified timing runtime observed non-successes: "
            + manifest.to_json()
        )
    return TimingQualificationAssessment(
        disposition=decision.disposition,
        sample_count=len(selected),
        non_success_count=0,
        timing_acceptance_applied=True,
        timing_qualification_accepted=True,
    )


__all__ = [
    "CANCELLATION_REQUEST_TIMING_CLAIM",
    "EXPECTED_TIMING_OBSERVATIONS",
    "NON_SUCCESS_MANIFEST_LIMIT",
    "NonSuccessManifest",
    "NonSuccessManifestEntry",
    "TimingQualificationAssessment",
    "TimingQualificationDecision",
    "TimingQualificationDisposition",
    "TimingQualificationReceipt",
    "TimingRuntimeIdentity",
    "build_non_success_manifest",
    "capture_timing_runtime_identity",
    "classify_postgres_transport",
    "decide_timing_qualification",
    "verify_portable_observation",
    "verify_timing_qualification_acceptance",
]
