from __future__ import annotations

from repomap_test_support.scale28_fix11_characterization import (
    ACCEPTED_TRACE_SUMMARY,
    COMPONENT_AGGREGATES,
    CORRECTED_PATCH_SHA256,
    Fix11Outcome,
    PreparationFork,
    PROVENANCE_SUMMARY,
    RECOVERED_RECEIPT_SHA256,
    TEST_COV5K_AUTHORIZED,
    decision,
)


def test_fix11_public_provenance_summary_is_closed_and_nonunique() -> None:
    assert CORRECTED_PATCH_SHA256 == (
        "c46003e5af8b72e2669b44764fc5daed"
        "ba051d71cf6ee5091fbe485e67767f74"
    )
    assert RECOVERED_RECEIPT_SHA256 == (
        "32d6ef1c1fc1dfbc953dc28383e3c864"
        "be144c75999a1709f9c3391197d0e94c"
    )
    assert PROVENANCE_SUMMARY.result == "nonunique_base"
    assert PROVENANCE_SUMMARY.changed_path_count == 23
    assert PROVENANCE_SUMMARY.matching_commit_count == 5
    assert PROVENANCE_SUMMARY.matching_full_tree_count == 5
    assert PROVENANCE_SUMMARY.canonical_base is None
    assert PROVENANCE_SUMMARY.corrected_result_tree is None


def test_fix11_public_trace_summary_retains_every_final_execution() -> None:
    assert ACCEPTED_TRACE_SUMMARY.execution_count == 40
    assert ACCEPTED_TRACE_SUMMARY.attempt_record_count == 50
    assert ACCEPTED_TRACE_SUMMARY.success_count == 11
    assert ACCEPTED_TRACE_SUMMARY.preparation_timeout_count == 29
    assert ACCEPTED_TRACE_SUMMARY.controlled_failure_count == 10
    assert ACCEPTED_TRACE_SUMMARY.candidate_execution_count == 0
    assert ACCEPTED_TRACE_SUMMARY.cleanup_limitation_count == 0
    assert ACCEPTED_TRACE_SUMMARY.attempt_overlap_count == 0
    assert ACCEPTED_TRACE_SUMMARY.condition_counts == {
        "quiet": 5,
        "bounded_cpu_contention": 5,
        "bounded_filesystem_contention": 5,
        "bounded_connection_churn": 5,
        "complete_gate_prelude": 10,
        "immediate_second_attempt_reacquisition": 10,
    }


def test_fix11_owned_resource_group_proves_fork_b() -> None:
    container_rss = COMPONENT_AGGREGATES["container_rss_ms"]
    group = COMPONENT_AGGREGATES["concurrent_resource_group_ms"]

    assert container_rss.median > 1_800
    assert container_rss.maximum > 1_800
    assert group.median > 1_800
    assert group.maximum < 5_000
    assert decision() == (PreparationFork.B, Fix11Outcome.C)
    assert not TEST_COV5K_AUTHORIZED


def test_fix11_public_aggregates_are_closed_and_privacy_safe() -> None:
    assert set(COMPONENT_AGGREGATES) == {
        "allocated_tree_ms",
        "backing_free_ms",
        "client_rss_ms",
        "container_rss_ms",
        "concurrent_resource_group_ms",
        "connection_ms",
        "temporary_bytes_ms",
        "wal_bytes_ms",
    }
    for aggregate in COMPONENT_AGGREGATES.values():
        assert (
            aggregate.minimum
            <= aggregate.median
            <= aggregate.p95
            <= aggregate.maximum
        )
