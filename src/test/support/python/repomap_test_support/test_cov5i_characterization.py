"""Public-safe TEST-COV5I characterization after FIX9 Outcome B."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from pathlib import Path

from repomap_test_support.scale28_fix9_failure_inventory import FORMER_FAILURES


FIX9_COMMIT = "e32f87fb899962d7696409a7988080f4925e975b"
FIX9_INCOMPLETE_PATCH_SHA256 = (
    "c46003e5af8b72e2669b44764fc5daedba051d71cf6ee5091fbe485e67767f74"
)

FROZEN_SOURCE_DIGESTS = {
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
    "tools/scale28_preparation_authority.py": (
        "6cac5359950a906d8cea1f3e73d42363e72314d2272f9b5ba97ab3b7596c4389"
    ),
    "tools/actual_refresh_failure_causality.py": (
        "f88ad8e0a518c522bc42022bc645f6852f4779a3edb9771a9600bccc4ad3767f"
    ),
    "tools/scale15_terminal_contracts.py": (
        "2411e5def1595114712750db36f760124db23a8288ebf5d87960a9329701bb1c"
    ),
    "src/test/support/python/repomap_test_support/"
    "scale28_fix9_failure_inventory.py": (
        "b11bbfc110422ccb6bfceae774f2667e2b3689b49743c66a15b9a1f1c01b8dcc"
    ),
}


def verify_source_freeze(repository_root: Path) -> None:
    """Reject any production, category, terminal, or manifest drift."""

    for relative_path, expected in FROZEN_SOURCE_DIGESTS.items():
        observed = hashlib.sha256(
            repository_root.joinpath(relative_path).read_bytes()
        ).hexdigest()
        if observed != expected:
            raise ValueError("TEST-COV5I source or protocol changed")


class GroupStatus(StrEnum):
    """Closed characterization completion state."""

    COMPLETED = "completed"
    BLOCKED_BY_REJECTED_CANDIDATE = "blocked_by_rejected_candidate"
    FAILED_ACCEPTED_TREE_GATE = "failed_accepted_tree_gate"


@dataclass(frozen=True, slots=True)
class CharacterizationGroup:
    """One fixed-count group with no completed-count inflation."""

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


CATEGORY_CONTRACTS = (
    ("observer_mechanism", "backend_observer_failed"),
    ("structured_ambient", "ambient_client_detected"),
    ("unknown_ownership", "backend_ownership_unknown"),
    ("ownership_conflict", "backend_ownership_unknown"),
    ("pre_dispatch_budget", "observer_budget_insufficient"),
    ("lifecycle_contract", "lifecycle_incomplete"),
    ("terminal_limitation", "backend_quiescence_timeout"),
    ("cleanup_limitation", "cleanup_eligibility_unproved"),
)

COMPLETED_GROUPS = (
    CharacterizationGroup(
        "former_failure_executable_manifest",
        len(FORMER_FAILURES),
        len(FORMER_FAILURES),
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "path_bound_source_protocol_freeze",
        len(FROZEN_SOURCE_DIGESTS),
        len(FROZEN_SOURCE_DIGESTS),
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "closed_source_category_contract",
        len(CATEGORY_CONTRACTS),
        len(CATEGORY_CONTRACTS),
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "fix9_deterministic_red_green_cases",
        5,
        5,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "accepted_tree_complete_opening_gate",
        1,
        1,
        GroupStatus.COMPLETED,
    ),
)

BLOCKED_GROUPS = (
    CharacterizationGroup(
        "five_actual_owning_areas",
        50,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "terminal_independence_matrix",
        80,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "source_category_black_box",
        160,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "mixed_campaign_streak",
        15,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "fresh_public_rehearsals",
        3,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "prior_publication_failure_rehearsal",
        1,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "complete_candidate_gates",
        4,
        0,
        GroupStatus.BLOCKED_BY_REJECTED_CANDIDATE,
    ),
    CharacterizationGroup(
        "restored_tree_gate_repeat",
        1,
        0,
        GroupStatus.FAILED_ACCEPTED_TREE_GATE,
    ),
)

FIX10_ACCEPTANCE_TESTS = (
    "both frozen preparation attempts complete inside their existing ceilings",
    "preparation resource sampling identifies its slow exact owner",
    "no preparation timeout is hidden as backend_observer_failed",
    "all fourteen former failure nodes pass the corrected candidate",
    "all five actual owning areas complete ten executions",
    "ambient and unknown ownership still refuse release",
    "fresh terminal readback remains independent from live failure",
    "terminal quiescence is read and never inferred",
    "request and publication timing surfaces remain unchanged",
    "fifteen mixed campaigns complete consecutively",
    "three fresh rehearsals and one prior-state rehearsal complete",
    "four complete repository gates pass without policy changes",
)
