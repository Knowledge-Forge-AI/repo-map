from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.test_cov5h_characterization import (
    BLOCKED_GROUPS,
    CANDIDATE_PATCH_DIGEST,
    FIX8_BASE,
    FIX8_COMMIT,
    FIX9_ACCEPTANCE_TESTS,
    GroupStatus,
    QUALIFIED_RUNTIME_DIGEST,
    SAFE_GROUPS,
    TIMING_PROTOCOL_DIGEST,
    completed_operations,
    verify_source_freeze,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_cov5h_freezes_the_pushed_fix8_tree_and_protocol() -> None:
    with pytest.raises(ValueError, match="source or protocol changed"):
        verify_source_freeze(_REPOSITORY_ROOT)

    assert len(FIX8_BASE) == len(FIX8_COMMIT) == 40
    assert len(CANDIDATE_PATCH_DIGEST) == 64
    assert len(QUALIFIED_RUNTIME_DIGEST) == 64
    assert len(TIMING_PROTOCOL_DIGEST) == 64


def test_cov5h_accepted_tree_does_not_misstate_candidate_authority() -> None:
    policy = DEFAULT_OBSERVER_DEADLINE_POLICY

    assert policy.server_statement_timeout_ms == 400
    assert policy.client_cancel_after_seconds == pytest.approx(0.45)
    assert policy.cancel_request_timeout_seconds == pytest.approx(0.25)
    assert (_REPOSITORY_ROOT / "tools" / "scale28_runtime_identity.py").is_file()


@pytest.mark.parametrize("group", SAFE_GROUPS, ids=lambda item: item.name)
def test_cov5h_records_only_completed_safe_groups(group) -> None:
    assert group.status is GroupStatus.COMPLETED
    assert group.completed_count == group.required_count


@pytest.mark.parametrize("group", BLOCKED_GROUPS, ids=lambda item: item.name)
def test_cov5h_records_configured_path_blocks_without_inflation(group) -> None:
    assert group.status is not GroupStatus.COMPLETED
    assert group.completed_count == 0


def test_cov5h_safe_characterization_total_is_fixed() -> None:
    assert completed_operations() == 612


@pytest.mark.parametrize("acceptance_test", FIX9_ACCEPTANCE_TESTS)
def test_cov5h_fix9_acceptance_is_exact_and_bounded(
    acceptance_test: str,
) -> None:
    assert acceptance_test
    assert "retune" not in acceptance_test
    assert "suppress ambient" not in acceptance_test
