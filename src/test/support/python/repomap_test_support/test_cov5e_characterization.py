"""Public-safe TEST-COV5E product-default characterization contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


FIX6_COMMIT = "3e5c564ac4f9b65be62647b4cddac2ae8e13d9e8"
FINAL_RELEASE_CAP_MS = 600
REQUIRED_SAMPLE_GAP_MS = 50
MINIMIZED_COMPRESSED_CALLER_MS = 440
FROZEN_SOURCE_MANIFEST_DIGEST = (
    "c182658b424d76b06ee5c11592a6fc88939bfa50b8c9e8c26d05b92f202fda27"
)
FROZEN_POLICY_DIGEST = (
    "8b0c48f00399956a777d337b28449dc50304519bfb84b7bcae496bf1c14a11c0"
)


@dataclass(frozen=True, slots=True)
class DeadlineTuple:
    """One independently recorded observer policy and handoff identity."""

    connection_ms: int
    server_statement_ms: int
    client_trigger_ms: int
    request_bound_ms: int
    caller_operation_ms: int
    handoff_ms: int

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("deadline tuple is invalid")
        if not (
            self.server_statement_ms
            < self.client_trigger_ms
            < self.caller_operation_ms
        ):
            raise ValueError("deadline hierarchy is invalid")
        if (
            self.request_bound_ms
            >= self.caller_operation_ms - self.client_trigger_ms
        ):
            raise ValueError("request reserve is invalid")

    def as_tuple(self) -> tuple[int, int, int, int, int, int]:
        """Return the comparison order used by the product identity test."""

        return (
            self.connection_ms,
            self.server_statement_ms,
            self.client_trigger_ms,
            self.request_bound_ms,
            self.caller_operation_ms,
            self.handoff_ms,
        )

    @property
    def digest(self) -> str:
        """Return a stable digest without importing product defaults."""

        encoded = json.dumps(
            {
                "caller_operation_ms": self.caller_operation_ms,
                "client_trigger_ms": self.client_trigger_ms,
                "connection_ms": self.connection_ms,
                "handoff_ms": self.handoff_ms,
                "request_bound_ms": self.request_bound_ms,
                "server_statement_ms": self.server_statement_ms,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


ACCEPTED_PRODUCT_TUPLE = DeadlineTuple(
    connection_ms=2_000,
    server_statement_ms=400,
    client_trigger_ms=450,
    request_bound_ms=40,
    caller_operation_ms=500,
    handoff_ms=500,
)
CANDIDATE_C120_420 = DeadlineTuple(
    connection_ms=2_000,
    server_statement_ms=400,
    client_trigger_ms=420,
    request_bound_ms=120,
    caller_operation_ms=570,
    handoff_ms=600,
)


@dataclass(frozen=True, slots=True)
class SourceDigest:
    """One frozen production source identity."""

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
        "tools/scale28_observer_deadlines.py",
        "4a600a1d6d20b49c7166694b450a0a0b717201a9928ebe9438517f695e94b1ad",
    ),
)


def source_manifest_digest(
    entries: Iterable[SourceDigest] = FROZEN_SOURCE_DIGESTS,
) -> str:
    """Digest a path-bound source manifest in deterministic order."""

    selected = tuple(entries)
    if not selected or len({entry.relative_path for entry in selected}) != len(
        selected
    ):
        raise ValueError("source manifest is invalid")
    payload = "".join(
        f"{entry.relative_path}\0{entry.sha256}\n"
        for entry in sorted(selected, key=lambda item: item.relative_path)
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def verify_source_manifest(repository_root: Path) -> str:
    """Return the frozen manifest digest or reject production source drift."""

    observed: list[SourceDigest] = []
    for expected in FROZEN_SOURCE_DIGESTS:
        source = repository_root / expected.relative_path
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        observed.append(SourceDigest(expected.relative_path, digest))
    observed_digest = source_manifest_digest(observed)
    if observed_digest != FROZEN_SOURCE_MANIFEST_DIGEST:
        raise ValueError("TEST-COV5E production source changed")
    return observed_digest


@dataclass(frozen=True, slots=True)
class CallerContext:
    """One product observer callsite and its outer budget form."""

    name: str
    boundary: str
    maximum_budget_ms: int
    budget_kind: str
    remaining_budget: bool


CALLER_CONTEXTS = (
    CallerContext(
        "registration",
        "BackendObserverSession.open",
        2_000,
        "connection",
        False,
    ),
    CallerContext(
        "identity_validation",
        "BackendOwnershipMonitor.validate_summary",
        500,
        "operation",
        False,
    ),
    CallerContext(
        "startup_summary",
        "BackendOwnershipMonitor.startup_summary",
        500,
        "operation",
        True,
    ),
    CallerContext(
        "active_summary",
        "BackendOwnershipMonitor._live_summary",
        500,
        "operation",
        True,
    ),
    CallerContext(
        "event_application",
        "BackendOwnershipMonitor._consume",
        500,
        "operation",
        False,
    ),
    CallerContext(
        "resource_read",
        "BackendOwnershipMonitor.read",
        500,
        "operation",
        False,
    ),
    CallerContext(
        "ownership_sample_one",
        "BackendOwnershipMonitor.release_when_ready.sample_one",
        500,
        "operation",
        True,
    ),
    CallerContext(
        "ownership_sample_two",
        "BackendOwnershipMonitor.release_when_ready.sample_two",
        500,
        "operation",
        True,
    ),
    CallerContext(
        "local_terminal_settlement",
        "BackendOwnershipMonitor.close_with_timeout",
        500,
        "settlement",
        True,
    ),
)


def current_policy_deadlines(
    policy: DeadlineTuple,
    caller_ms: float,
) -> tuple[float, float]:
    """Independently model the accepted tree's current compression rule."""

    if (
        isinstance(caller_ms, bool)
        or not isinstance(caller_ms, (int, float))
        or not math.isfinite(caller_ms)
        or caller_ms <= 0
    ):
        raise ValueError("caller budget is invalid")
    if caller_ms < policy.caller_operation_ms:
        reserve = min(policy.request_bound_ms, caller_ms / 4)
        return caller_ms - reserve, reserve
    scale = caller_ms / policy.caller_operation_ms
    trigger = min(
        caller_ms - policy.request_bound_ms,
        policy.client_trigger_ms * scale,
    )
    if trigger <= policy.server_statement_ms:
        trigger = policy.client_trigger_ms
    reserve = min(policy.request_bound_ms, caller_ms - trigger)
    if reserve <= 0:
        raise ValueError("request reserve is invalid")
    return trigger, reserve


@dataclass(frozen=True, slots=True)
class FinalReleaseEnvelope:
    """One candidate caller plus the required two-sample separation."""

    required_ms: int
    available_ms: int

    @property
    def deficit_ms(self) -> int:
        return max(0, self.required_ms - self.available_ms)

    @property
    def fits(self) -> bool:
        return self.required_ms <= self.available_ms


def final_release_envelope(
    policy: DeadlineTuple,
    *,
    sample_gap_ms: int,
    cap_ms: int,
) -> FinalReleaseEnvelope:
    """Compare a full caller authority plus sample gap with the outer cap."""

    if sample_gap_ms <= 0 or cap_ms <= 0:
        raise ValueError("final release envelope is invalid")
    return FinalReleaseEnvelope(
        required_ms=policy.caller_operation_ms + sample_gap_ms,
        available_ms=cap_ms,
    )


@dataclass(frozen=True, slots=True)
class ContractComparison:
    """Accepted tree, rejected candidate, required contract, and exact gap."""

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
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("contract comparison is invalid")
        if len(set(values)) != len(values):
            raise ValueError("contract comparison collapses distinct states")
        return self


def build_contract_comparison() -> ContractComparison:
    """Return the frozen Outcome B comparison for FIX7 handoff."""

    return ContractComparison(
        accepted_tree="request_settlement_safe_but_request_bound_unqualified",
        candidate_tree=(
            "isolated_fallback_reliable_but_configured_callers_rejected"
        ),
        required_contract=(
            "reliable_request_bound_with_strict_server_precedence_in_every_caller"
        ),
        remaining_gap=(
            "complete_final_release_caller_budget_model_and_fitting_default_tuple"
        ),
    ).validate()


@dataclass(frozen=True, slots=True)
class ManifestGroup:
    """One independently reported semantic evidence group."""

    group_id: str
    required_cases: int | None


COV5E_SEMANTIC_MANIFEST = (
    ManifestGroup("close_order", 100),
    ManifestGroup("source_causality", 200),
    ManifestGroup("terminal_claim", 18),
    ManifestGroup("reacquisition", 36),
    ManifestGroup("postgres_cancellation", 20),
    ManifestGroup("request_round_trip_stability", None),
    ManifestGroup("three_party_request_settlement", 50),
    ManifestGroup("caller_budget_contract", 9),
)


@dataclass(frozen=True, slots=True)
class AcceptanceGroup:
    """One exact FIX7 acceptance group and its independent authority."""

    group_id: str
    required_cases: int
    acceptance_authority: str


FIX7_ACCEPTANCE_SUITE = (
    AcceptanceGroup("product_default_fallback", 30, "exact_connection"),
    AcceptanceGroup("server_timeout", 20, "postgres_statement_timeout"),
    AcceptanceGroup("cancellation_timeout", 20, "request_outcome"),
    AcceptanceGroup(
        "cancellation_transport_failure",
        20,
        "request_outcome",
    ),
    AcceptanceGroup("three_party_close", 50, "barrier_schedule"),
    AcceptanceGroup("close_under_use", 100, "barrier_schedule"),
    AcceptanceGroup("source_causality", 200, "source_sequence"),
    AcceptanceGroup("terminal_claim", 18, "terminal_contract"),
    AcceptanceGroup("reacquisition", 36, "generation_contract"),
    AcceptanceGroup("actual_caller_context", 9, "production_callsite"),
    AcceptanceGroup("actual_owning_path", 50, "configured_harness"),
    AcceptanceGroup("quiet_baseline", 1, "configured_harness"),
    AcceptanceGroup("bounded_contention", 1, "isolated_contention"),
    AcceptanceGroup("mixed_campaign", 15, "configured_campaign"),
    AcceptanceGroup("fresh_public_rehearsal", 3, "fresh_runtime"),
    AcceptanceGroup(
        "prior_publication_cancellation",
        1,
        "prior_state_rehearsal",
    ),
    AcceptanceGroup("focused_selection", 10, "black_box_selection"),
    AcceptanceGroup("complete_repository_gate", 4, "repository_gate"),
)
