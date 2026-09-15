"""Public-safe TEST-COV5F characterization of the rejected FIX7 candidate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


FIX7_COMMIT = "1e2862f08d08281f8f09290fc83999f0f77f4a93"
FIX7_BASE_COMMIT = "d3bf10ed5b3ae45b1d83c22e6e94306dffbfcaf3"
PRIVATE_CANDIDATE_SHA256 = (
    "dcc02aeb6ca9c65a8bdc081742083985b652ca7543f0574506e222f8bf89f649"
)
FROZEN_ACCEPTED_POLICY_DIGEST = (
    "1d1e3a73f8fd908b8c991cb4f49f67ccd0b915f1c056d6502f16eed1aa059a16"
)


@dataclass(frozen=True, slots=True)
class SourceDigest:
    """One path-bound accepted production source digest."""

    relative_path: str
    sha256: str


FROZEN_SOURCE_DIGESTS = (
    SourceDigest(
        "tools/scale14_backend_monitor.py",
        "ef99e804d92aa4304089ca84e8d2222b9ea0a201a9d29f0564129d718b991d97",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session.py",
        "35799e4f3f1abb444c769f0b15bc48ed66e782ec7e336c0e6de984e8a31e5920",
    ),
    SourceDigest(
        "tools/scale28_hybrid_startup.py",
        "f7aec398200b0f5c8420d9223fbd0e702879fb0e4dc2efd703b7d45a6580d90d",
    ),
    SourceDigest(
        "tools/scale28_observer_deadlines.py",
        "4a600a1d6d20b49c7166694b450a0a0b717201a9928ebe9438517f695e94b1ad",
    ),
    SourceDigest(
        "tools/scale28_preparation_authority.py",
        "6cac5359950a906d8cea1f3e73d42363e72314d2272f9b5ba97ab3b7596c4389",
    ),
)


def verify_source_freeze(repository_root: Path) -> tuple[SourceDigest, ...]:
    """Return the exact accepted source identity or reject drift."""

    observed = tuple(
        SourceDigest(
            expected.relative_path,
            hashlib.sha256(
                (repository_root / expected.relative_path).read_bytes()
            ).hexdigest(),
        )
        for expected in FROZEN_SOURCE_DIGESTS
    )
    if observed != FROZEN_SOURCE_DIGESTS:
        raise ValueError("TEST-COV5F production source changed")
    return observed


@dataclass(frozen=True, slots=True)
class DeadlineIdentity:
    """One independently encoded private deadline-policy identity."""

    connection_ms: int
    server_ms: int
    client_ms: int
    request_ms: int
    caller_ms: int

    @property
    def digest(self) -> str:
        payload = {
            "caller_ms": self.caller_ms,
            "client_ms": self.client_ms,
            "connection_ms": self.connection_ms,
            "request_ms": self.request_ms,
            "server_ms": self.server_ms,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


ACCEPTED_POLICY = DeadlineIdentity(2_000, 400, 450, 40, 500)
ADR_0045_POLICY = DeadlineIdentity(2_000, 400, 450, 120, 500)


def adr_sql_deadlines(caller_ms: float) -> tuple[float, int]:
    """Model ADR 0045 directly without importing candidate constants."""

    if (
        isinstance(caller_ms, bool)
        or not isinstance(caller_ms, (int, float))
        or not math.isfinite(caller_ms)
        or caller_ms <= 0
    ):
        raise ValueError("caller budget is invalid")
    if caller_ms < 420:
        raise ValueError("caller budget is insufficient")
    return min(caller_ms, 450), 120


@dataclass(frozen=True, slots=True)
class OperationClassCase:
    """One ADR-labelled operation/class ownership case."""

    operation: str
    operation_class: str
    issues_sql: bool


OPERATION_CLASS_CASES = (
    OperationClassCase("connection_registration", "connection_startup", True),
    OperationClassCase("startup_active_summary", "sql_bounded", True),
    OperationClassCase("event_application", "sql_bounded", True),
    OperationClassCase("resource_and_transient_read", "sql_bounded", True),
    OperationClassCase("ownership_samples", "sql_bounded", True),
    OperationClassCase("summary_and_identity_validation", "serialization_only", False),
    OperationClassCase("activation_and_atomic_release", "serialization_only", False),
    OperationClassCase("close_and_request_settlement", "settlement", False),
)


@dataclass(frozen=True, slots=True)
class CallerContext:
    """One accepted production caller context."""

    name: str
    budget_owner: str


CALLER_CONTEXTS = (
    CallerContext("registration", "connection_startup"),
    CallerContext("identity_validation", "operation"),
    CallerContext("startup_summary", "prefinal"),
    CallerContext("active_summary", "prefinal"),
    CallerContext("event_application", "prefinal"),
    CallerContext("resource_read", "prefinal"),
    CallerContext("ownership_sample_one", "final_remaining"),
    CallerContext("ownership_sample_two", "final_remaining"),
    CallerContext("terminal_and_close", "settlement"),
)


@dataclass(frozen=True, slots=True)
class CharacterizationGroup:
    """One independently dispositioned semantic group."""

    group_id: str
    required_cases: int
    disposition: str


CHARACTERIZATION_GROUPS = (
    CharacterizationGroup("product_default_fallback", 30, "blocked"),
    CharacterizationGroup("server_timeout", 20, "completed"),
    CharacterizationGroup("cancellation_timeout", 20, "completed"),
    CharacterizationGroup("transport_failure", 20, "completed"),
    CharacterizationGroup("pre_dispatch", 12, "candidate_only"),
    CharacterizationGroup("operation_class", 8, "candidate_only"),
    CharacterizationGroup("three_party_close", 50, "completed"),
    CharacterizationGroup("close_under_use", 100, "completed"),
    CharacterizationGroup("source_causality", 200, "completed"),
    CharacterizationGroup("terminal_claim", 18, "completed"),
    CharacterizationGroup("reacquisition", 36, "completed"),
    CharacterizationGroup("caller_context", 9, "completed"),
    CharacterizationGroup("final_window", 20, "candidate_only"),
    CharacterizationGroup("actual_owning_path", 50, "blocked"),
    CharacterizationGroup("quiet_baseline", 1, "completed"),
    CharacterizationGroup("bounded_contention", 1, "completed"),
    CharacterizationGroup("mixed_campaign", 15, "blocked"),
    CharacterizationGroup("fresh_rehearsal", 3, "blocked"),
    CharacterizationGroup("prior_state", 1, "completed"),
    CharacterizationGroup("focused_selection", 10, "blocked"),
    CharacterizationGroup("complete_gate", 4, "blocked"),
)


@dataclass(frozen=True, slots=True)
class DecisionBoundary:
    """Exact decision needed before another production candidate."""

    decision_kind: str
    question: str
    minimum_evidence: tuple[str, ...]
    prohibited_shortcuts: tuple[str, ...]


NEXT_DECISION = DecisionBoundary(
    decision_kind="ADR_revision_and_platform_measurement",
    question=(
        "select a configured cancellation-request reliability contract and "
        "its settlement deadline before another implementation"
    ),
    minimum_evidence=(
        "configured cancel_safe round-trip distribution",
        "tail bound selected before product mutation",
        "operation and request settlement proof",
        "all actual final-release caller contexts",
    ),
    prohibited_shortcuts=(
        "raise the final-release window",
        "lower the server timeout",
        "accept CancellationTimeout as successful fallback",
        "restart a favorable cohort",
    ),
)


def group_map(
    groups: Iterable[CharacterizationGroup] = CHARACTERIZATION_GROUPS,
) -> dict[str, CharacterizationGroup]:
    """Return unique group identities or reject a collapsed manifest."""

    selected = tuple(groups)
    result = {group.group_id: group for group in selected}
    if len(result) != len(selected):
        raise ValueError("characterization group identity is duplicated")
    return result
