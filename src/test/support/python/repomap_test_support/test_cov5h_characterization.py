"""Public-safe TEST-COV5H characterization after FIX8 Outcome B."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path


FIX8_COMMIT = "941867abc38a86844c1b3fe8621b1b919eb591c0"
FIX8_BASE = "89a2195fd8dea35b4a8495bef2243591e2ab33e9"
CANDIDATE_PATCH_DIGEST = (
    "41d98237ea4f5b0065ce973c0ba17afcec92d6e67971aad8f5c2a7a603192f67"
)
QUALIFIED_RUNTIME_DIGEST = (
    "866beffa8f83584035f80c014f6dfedac3b029090a5a4a15d744207cb636161d"
)
TIMING_PROTOCOL_DIGEST = (
    "a8627f55150408e654d542bd088001652267e2c5c3bb76b6e9a50c1c589d88e7"
)

FROZEN_SOURCE_DIGESTS = {
    "tools/scale14_backend_monitor.py": (
        "ef99e804d92aa4304089ca84e8d2222b9ea0a201a9d29f0564129d718b991d97"
    ),
    "tools/scale28_backend_observer_session.py": (
        "35799e4f3f1abb444c769f0b15bc48ed66e782ec7e336c0e6de984e8a31e5920"
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
    "src/test/support/python/repomap_test_support/"
    "test_cov5g_r1_characterization.py": (
        "7773378a869fccb8c41f0de978e7c1d5eacb921e1c353879cbf66d9e17ee210b"
    ),
}


class GroupStatus(str, Enum):
    """Closed characterization status."""

    COMPLETED = "completed"
    BLOCKED_BY_CONFIGURED_PATH = "blocked_by_configured_path"
    NOT_APPLICABLE_WITHOUT_CANDIDATE = "not_applicable_without_candidate"


@dataclass(frozen=True, slots=True)
class CharacterizationGroup:
    """One fixed-count evidence group and its truthful status."""

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


SAFE_GROUPS = (
    CharacterizationGroup(
        "exact_stack_timing_requalification",
        500,
        500,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "request_origin_schedules",
        30,
        30,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "request_publication_schedules",
        30,
        30,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "triple_fault_decision_cases",
        12,
        12,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "runtime_identity_comparisons",
        20,
        20,
        GroupStatus.COMPLETED,
    ),
    CharacterizationGroup(
        "final_release_repetitions",
        20,
        20,
        GroupStatus.COMPLETED,
    ),
)

BLOCKED_GROUPS = (
    CharacterizationGroup(
        "actual_owning_executions",
        50,
        0,
        GroupStatus.BLOCKED_BY_CONFIGURED_PATH,
    ),
    CharacterizationGroup(
        "mixed_campaigns",
        15,
        0,
        GroupStatus.BLOCKED_BY_CONFIGURED_PATH,
    ),
    CharacterizationGroup(
        "fresh_public_rehearsals",
        3,
        0,
        GroupStatus.BLOCKED_BY_CONFIGURED_PATH,
    ),
    CharacterizationGroup(
        "prior_publication_rehearsal",
        1,
        0,
        GroupStatus.BLOCKED_BY_CONFIGURED_PATH,
    ),
    CharacterizationGroup(
        "complete_acceptance_gates",
        4,
        0,
        GroupStatus.NOT_APPLICABLE_WITHOUT_CANDIDATE,
    ),
)

FIX9_ACCEPTANCE_TESTS = (
    "ten SCALE14 owning executions complete",
    "ten SCALE23 owning executions complete",
    "ten SCALE28 owning executions complete",
    "ten SCALE28-FIX1 owning executions complete",
    "ten hybrid FIX8 owning executions complete",
    "injected ambient client still refuses release",
    "terminal backend quiescence is proved",
    "600 ms final window remains unchanged",
    "50 ms sample floor remains unchanged",
    "420 ms SQL dispatch floor remains unchanged",
    "250 ms request and 300 ms publication remain unchanged",
    "qualified runtime digest matches",
)


def verify_source_freeze(repository_root: Path) -> None:
    """Reject any production or inherited-protocol mutation."""

    for relative_path, expected in FROZEN_SOURCE_DIGESTS.items():
        observed = hashlib.sha256(
            repository_root.joinpath(relative_path).read_bytes()
        ).hexdigest()
        if observed != expected:
            raise ValueError("TEST-COV5H source or protocol changed")


def completed_operations() -> int:
    """Return fixed-count safe evidence without blocked-group inflation."""

    return sum(group.completed_count for group in SAFE_GROUPS)
