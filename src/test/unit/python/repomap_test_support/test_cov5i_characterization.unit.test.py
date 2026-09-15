from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.scale28_fix9_failure_inventory import (
    FORMER_FAILURES,
    PrimaryCandidate,
)
from repomap_test_support.test_cov5i_characterization import (
    BLOCKED_GROUPS,
    CATEGORY_CONTRACTS,
    COMPLETED_GROUPS,
    FIX10_ACCEPTANCE_TESTS,
    FIX9_COMMIT,
    FIX9_INCOMPLETE_PATCH_SHA256,
    FROZEN_SOURCE_DIGESTS,
    GroupStatus,
    verify_source_freeze,
)
from scale15_terminal_contracts import ControlFailureCode
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_cov5i_freezes_pushed_fix9_source_policy_and_protocol() -> None:
    with pytest.raises(ValueError, match="source or protocol changed"):
        verify_source_freeze(_REPOSITORY_ROOT)
    assert len(FIX9_COMMIT) == 40
    assert len(FIX9_INCOMPLETE_PATCH_SHA256) == 64
    assert len(FROZEN_SOURCE_DIGESTS) == 8


def test_cov5i_maps_every_former_failure_to_one_executable_node() -> None:
    assert len(FORMER_FAILURES) == 14
    assert len({case.case_id for case in FORMER_FAILURES}) == 14
    assert len({case.node_id for case in FORMER_FAILURES}) == 14
    for case in FORMER_FAILURES:
        relative_path, separator, node = case.node_id.partition("::")
        assert separator == "::"
        assert node.startswith("test_")
        assert _REPOSITORY_ROOT.joinpath(relative_path).is_file()
        assert case.primary_candidate is not PrimaryCandidate.UNCLASSIFIED


@pytest.mark.parametrize(
    ("source_event", "outer_category"),
    CATEGORY_CONTRACTS,
)
def test_cov5i_category_contract_uses_closed_public_vocabulary(
    source_event: str,
    outer_category: str,
) -> None:
    assert source_event
    closed = {code.value for code in ControlFailureCode}
    assert outer_category in closed | {"observer_budget_insufficient"}


@pytest.mark.parametrize("group", COMPLETED_GROUPS, ids=lambda item: item.name)
def test_cov5i_counts_only_completed_safe_groups(group) -> None:
    assert group.status is GroupStatus.COMPLETED
    assert group.completed_count == group.required_count


@pytest.mark.parametrize("group", BLOCKED_GROUPS, ids=lambda item: item.name)
def test_cov5i_does_not_inflate_blocked_candidate_groups(group) -> None:
    assert group.status is not GroupStatus.COMPLETED
    assert group.completed_count == 0


def test_cov5i_characterization_does_not_misstate_candidate_authority() -> None:
    policy = DEFAULT_OBSERVER_DEADLINE_POLICY

    assert policy.cancel_request_timeout_seconds == pytest.approx(0.25)
    assert (_REPOSITORY_ROOT / "tools/scale28_runtime_identity.py").is_file()
    assert not (
        _REPOSITORY_ROOT / "tools/scale28_backend_observer_contracts.py"
    ).exists()


@pytest.mark.parametrize("acceptance_test", FIX10_ACCEPTANCE_TESTS)
def test_cov5i_fix10_boundary_is_exact_and_requires_no_retuning(
    acceptance_test: str,
) -> None:
    assert acceptance_test
    assert "increase" not in acceptance_test
    assert "retune" not in acceptance_test
    assert "suppress ambient" not in acceptance_test
