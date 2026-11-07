"""Current policy declarations do not rewrite historical gap interpretations."""
from __future__ import annotations

import pytest

from retrieval_semantic_baseline_expectations import W5_EXPECTED_BASELINE_GAPS_BY_ARM, is_expected_baseline_gap


def test_current_declared_denial_and_legacy_absent_graph_outcome_are_distinct() -> None:
    arm = "current_graph_baseline:postgresql"
    old_gap = "unavailable:captured_text_surface_unsupported_by_metadata_graph"
    new_gap = "refused:binding_privacy_not_authorized"
    assert is_expected_baseline_gap(arm, "cal-21", "gap", old_gap)
    assert W5_EXPECTED_BASELINE_GAPS_BY_ARM[arm]["cal-21"] == ("gap", old_gap)
    assert not is_expected_baseline_gap(arm, "cal-21", "gap", new_gap)
    assert is_expected_baseline_gap(arm, "cal-21", "gap", new_gap, policy_version="cloe-w5-admission-v1")
    assert not is_expected_baseline_gap(arm, "cal-21", "gap", old_gap, policy_version="cloe-w5-admission-v1")
    assert is_expected_baseline_gap(
        arm, "cal-21", "gap", old_gap, policy_version="cloe-w5-baseline-correspondence-v1",
    )
    assert not is_expected_baseline_gap(
        arm, "cal-21", "gap", new_gap, policy_version="cloe-w5-baseline-correspondence-v1",
    )


@pytest.mark.parametrize("task_id", ["cal-16", "cal-17"])
def test_public_feed_metadata_remains_a_capability_gap(task_id: str) -> None:
    assert is_expected_baseline_gap(
        "captured_projection_reference:sqlite", task_id, "gap",
        "unavailable:non_body_feed_or_mailbox_excluded_from_text_projection",
    )
    assert not is_expected_baseline_gap(
        "captured_projection_reference:sqlite", task_id, "gap",
        "refused:binding_privacy_not_authorized",
    )


def test_unknown_policy_or_unplanned_gap_is_not_silently_accepted() -> None:
    assert not is_expected_baseline_gap("unknown-arm", "cal-21", "gap", "refused:binding_privacy_not_authorized")
    assert not is_expected_baseline_gap("native_tools_baseline", "unplanned-task", "gap", None)
    with pytest.raises(ValueError, match="unknown W5 expected-gap policy"):
        is_expected_baseline_gap("native_tools_baseline", "cal-21", "gap", None, policy_version="future")
