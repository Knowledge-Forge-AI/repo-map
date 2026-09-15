"""Public-safe TEST-COV5J characterization after FIX10 Outcome B."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from pathlib import Path

from repomap_test_support.scale28_fix10_preparation_trace import (
    CLOSED_EVENTS,
    PARENT_EVENTS,
    POSTGRES_EVENTS,
    WORKER_EVENTS,
    ClockDomain,
    expected_clock_domain,
)


FIX10_COMMIT = "634eb50abcecbbc1489932f65b4c4e15ae837590"
CORRECTED_CANDIDATE_PATCH_SHA256 = (
    "c46003e5af8b72e2669b44764fc5daedba051d71cf6ee5091fbe485e67767f74"
)

SUPERSEDED_R1_SOURCE_DIGESTS = {
    "tools/scale28_preparation_resources.py": (
        "ab0298a4f5f39c7f586e1b5a0912565f4fbe320b7540d7aa15e10bac04a0aa90"
    ),
}

FROZEN_SOURCE_DIGESTS = {
    "tools/scale28_preparation_worker.py": (
        "9ff6242a002de33ce24ef77c0ecce0c6a374f50ef933793df1ed6f716f4b709b"
    ),
    "tools/scale28_preparation_authority.py": (
        "6cac5359950a906d8cea1f3e73d42363e72314d2272f9b5ba97ab3b7596c4389"
    ),
    "tools/scale28_preparation_values.py": (
        "4f67703ae7c756e71b24938b26916c75d4f0ba5fec7e45ebf68eaf279100d8e9"
    ),
    "tools/scale28_preparation_policy.py": (
        "1f1082e375f51e84394c9a2a1de9331b754711af6c7b9f001898684b13c45a2f"
    ),
    "tools/scale14_actual_refresh_supervisor.py": (
        "134d04180249ab4d12ebc7fd12a13f22e9982e0ebe644bb12690a8371490233a"
    ),
    "tools/scale14_backend_monitor.py": (
        "ef99e804d92aa4304089ca84e8d2222b9ea0a201a9d29f0564129d718b991d97"
    ),
    "tools/scale28_hybrid_startup.py": (
        "f7aec398200b0f5c8420d9223fbd0e702879fb0e4dc2efd703b7d45a6580d90d"
    ),
    "tools/scale28_observer_deadlines.py": (
        "4a600a1d6d20b49c7166694b450a0a0b717201a9928ebe9438517f695e94b1ad"
    ),
    "tools/actual_refresh_failure_causality.py": (
        "f88ad8e0a518c522bc42022bc645f6852f4779a3edb9771a9600bccc4ad3767f"
    ),
    "tools/scale15_terminal_contracts.py": (
        "2411e5def1595114712750db36f760124db23a8288ebf5d87960a9329701bb1c"
    ),
    "src/test/support/python/repomap_test_support/"
    "test_cov5h_characterization.py": (
        "efc2d8f193dc5c3fe82d325f8150d49dbc25927d126028320434aee194c5d28a"
    ),
    "src/test/support/python/repomap_test_support/"
    "scale28_fix10_candidate_receipt.py": (
        "4caeeee73f5dbbeecd6f8677f9759a697b09f3282f658114dfff9fe1fa88ff1f"
    ),
    "src/test/support/python/repomap_test_support/"
    "scale28_fix10_preparation_trace.py": (
        "c157e701cb46dcf68fe630c23857e99a095b3e8192cf862baed5db7ea644a6df"
    ),
    "docs/superpowers/plans/"
    "2026-07-26-scale28-fix10-preparation-worker-critical-path-"
    "attribution-deadline-qualification.md": (
        "641c6476b6daa1f67097c7292396eb472b477c079421f0e7c45ec4cc14b71ed1"
    ),
}


def verify_source_freeze(repository_root: Path) -> None:
    """Reject non-superseded FIX10 production, policy, or protocol drift."""

    for relative_path, expected in FROZEN_SOURCE_DIGESTS.items():
        observed = hashlib.sha256(
            repository_root.joinpath(relative_path).read_bytes()
        ).hexdigest()
        if observed != expected:
            raise ValueError("TEST-COV5J source, policy, or protocol changed")


EXPECTED_PARENT_EVENTS = (
    "attempt_authority_created",
    "attempt_deadline_started",
    "process_spawn_requested",
    "process_started_parent_observed",
    "parent_frame_received",
    "parent_frame_validated",
    "ack_write_started",
    "ack_write_completed",
    "parent_receipt_received",
    "child_exit_observed",
    "process_tree_settled",
    "attempt_cleanup_started",
    "attempt_cleanup_completed",
    "next_attempt_authority_created",
)

EXPECTED_WORKER_EVENTS = (
    "worker_entry",
    "worker_import_initialization_complete",
    "request_received",
    "request_decoded",
    "request_validated",
    "pgdata_walk_started",
    "pgdata_walk_completed",
    "filesystem_observation_started",
    "filesystem_observation_completed",
    "resource_baseline_assembled",
    "canonical_encoding_started",
    "canonical_encoding_completed",
    "digest_completed",
    "observation_frame_write_started",
    "observation_frame_write_completed",
    "child_ack_received",
    "receipt_created",
    "receipt_write_started",
    "receipt_write_completed",
)

EXPECTED_POSTGRES_EVENTS = (
    "postgres_resource_read_started:temporary_bytes",
    "postgres_resource_read_completed:temporary_bytes",
    "postgres_resource_read_started:wal_bytes",
    "postgres_resource_read_completed:wal_bytes",
)


def verify_independent_trace_manifest() -> None:
    """Compare the pushed manifest with the independently derived contract."""

    if PARENT_EVENTS != EXPECTED_PARENT_EVENTS:
        raise ValueError("TEST-COV5J parent trace contract changed")
    if WORKER_EVENTS != EXPECTED_WORKER_EVENTS:
        raise ValueError("TEST-COV5J worker trace contract changed")
    if POSTGRES_EVENTS != EXPECTED_POSTGRES_EVENTS:
        raise ValueError("TEST-COV5J resource trace contract changed")
    expected = frozenset(
        EXPECTED_PARENT_EVENTS
        + EXPECTED_WORKER_EVENTS
        + EXPECTED_POSTGRES_EVENTS
    )
    if CLOSED_EVENTS != expected:
        raise ValueError("TEST-COV5J closed trace vocabulary changed")
    for event in EXPECTED_PARENT_EVENTS:
        if expected_clock_domain(event) is not ClockDomain.PARENT_MONOTONIC:
            raise ValueError("TEST-COV5J parent clock ownership changed")
    for event in EXPECTED_WORKER_EVENTS + EXPECTED_POSTGRES_EVENTS:
        if (
            expected_clock_domain(event)
            is not ClockDomain.WORKER_LOCAL_DURATION
        ):
            raise ValueError("TEST-COV5J worker clock ownership changed")


class GroupStatus(StrEnum):
    """Closed characterization completion state."""

    COMPLETED = "completed"
    BLOCKED_BY_MISSING_CANDIDATE_RECEIPT = (
        "blocked_by_missing_candidate_receipt"
    )


@dataclass(frozen=True, slots=True)
class CharacterizationGroup:
    """One fixed-count group with no blocked-count inflation."""

    name: str
    required_count: int
    completed_count: int
    status: GroupStatus

    def __post_init__(self) -> None:
        if not self.name or self.required_count < 1:
            raise ValueError("characterization group is invalid")
        if not 0 <= self.completed_count <= self.required_count:
            raise ValueError("characterization count is invalid")
        if (
            self.completed_count == self.required_count
        ) is not (self.status is GroupStatus.COMPLETED):
            raise ValueError("characterization status conflicts with count")


COMPLETED_GROUPS = (
    CharacterizationGroup(
        "pushed_fix10_source_policy_protocol_freeze",
        len(FROZEN_SOURCE_DIGESTS),
        len(FROZEN_SOURCE_DIGESTS),
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "independent_closed_critical_path_manifest",
        len(CLOSED_EVENTS),
        len(CLOSED_EVENTS),
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "corrected_candidate_receipt_diagnosis",
        1,
        1,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "accepted_tree_complete_gate",
        1,
        1,
        GroupStatus.COMPLETED,
    ),
)

BLOCKED_GROUPS = (
    CharacterizationGroup(
        "controlled_comparison_traces",
        80,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "preparation_qualification",
        180,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "source_causality_matrix",
        160,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "attempt_reacquisition",
        36,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "former_failure_candidate_closure",
        14,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "observer_integration",
        140,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "unchanged_timing_branch",
        150,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "five_actual_owning_areas",
        50,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "mixed_campaign_streak",
        15,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "fresh_public_rehearsals",
        3,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "prior_publication_failure_rehearsal",
        1,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
    CharacterizationGroup(
        "complete_candidate_gates",
        4,
        0,
        GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT,
    ),
)

FIX11_ACCEPTANCE_TESTS = (
    "one owner-private receipt binds the corrected patch to one exact base",
    "the receipt contains mode, digest, count, manifest, purpose, and phase",
    "the exact base exists and the patch applies cleanly only there",
    "the applied binary diff reproduces the complete receipt manifest",
    "the unmodified corrected candidate reproduces the preparation blocker",
    "accepted and candidate trees produce all eighty controlled traces",
    "every trace separates parent ordering from worker-local duration",
    "the active timeout stage and exact dominant component are observed",
    "attempt-one cleanup completes before attempt-two authority",
    "preparation timeout and resource failure source order is observed",
    "valid non-duplicated work is classified against 1800 milliseconds",
    "one deterministic regression distinguishes defect from policy",
    "any production correction is the smallest proved Fork A change",
    "all fourteen former failures pass the fully corrected candidate",
    "all five owning areas complete ten executions",
    "no production or policy value moves during TEST-COV5K qualification",
)
