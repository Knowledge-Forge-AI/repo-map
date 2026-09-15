from __future__ import annotations

import pytest

from repomap_kg.storage.authority import PublicationGenerations
from scale15_terminal_contracts import (
    CleanupState,
    ControlFailure,
    ControlFailureCode,
    ExpectedRefreshAuthority,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalCategory,
    TerminalControlResult,
)


def _expected() -> ExpectedRefreshAuthority:
    return ExpectedRefreshAuthority(
        repository_identity="repo1:public-fixture",
        repository_name="public-fixture",
        generations=PublicationGenerations(
            "sg1:source",
            "cg1:config",
            "eg1:extractor",
            "kg1:canonicalizer",
        ),
        execution_mode="direct",
        zero_state_first_publication=True,
        expected_family_counts={
            "files": 1,
            "raw_observations": 1,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "canonical_evidence": 0,
            "canonical_node_evidence": 0,
            "canonical_edge_evidence": 0,
        },
    )


def test_expected_refresh_authority_requires_exact_seven_family_projection() -> None:
    expected = _expected()

    assert expected.validate() is expected
    assert tuple(expected.expected_family_counts) == (
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    )

    with pytest.raises(ValueError, match="family"):
        ExpectedRefreshAuthority(
            expected.repository_identity,
            expected.repository_name,
            expected.generations,
            expected.execution_mode,
            True,
            {"files": 0},
        ).validate()


def test_expected_prior_authority_requires_prelaunch_run_marker() -> None:
    expected = _expected()

    with pytest.raises(ValueError, match="prior publication"):
        ExpectedRefreshAuthority(
            expected.repository_identity,
            expected.repository_name,
            expected.generations,
            expected.execution_mode,
            False,
            expected.expected_family_counts,
            prior_publication_run_id=1,
            prior_family_counts=expected.expected_family_counts,
        ).validate()


def test_control_failure_is_closed_and_does_not_expose_exception_text() -> None:
    failure = ControlFailure(
        ControlFailureCode.BACKEND_TELEMETRY_FAILED,
        cause=RuntimeError("/private/secret/runtime"),
    )

    assert failure.code is ControlFailureCode.BACKEND_TELEMETRY_FAILED
    assert str(failure) == "protected refresh control failed"
    assert "/private/secret" not in str(failure)


def test_terminal_result_payload_contains_only_closed_sanitized_facts() -> None:
    result = TerminalControlResult(
        terminal_category=TerminalCategory.CONTROL_FAILURE_CANCELLED_RECONCILED,
        primary_control_failure=ControlFailureCode.AMBIENT_CLIENT_DETECTED,
        secondary_failures=(ControlFailureCode.TERMINAL_RESOURCE_UNAVAILABLE,),
        reconciliation_status=ReconciliationStatus.RECONCILED,
        child_exit_code=1,
        signal_count=1,
        child_quiescent=True,
        backend_quiescent=True,
        terminal_resource_available=False,
        publication_state=PublicationState.NOT_PUBLISHED,
        stage_state=StageState.FAILED_RECONCILED,
        cleanup_state=CleanupState.ELIGIBLE,
        active_boundary_at_stop="merge.files",
        threshold_evaluation=None,
        phase_sequence=("refresh.source_discovery",),
        operation_sequence=("merge.files",),
    )

    payload = result.to_payload()

    assert payload["terminal_category"] == (
        "control_failure_cancelled_reconciled"
    )
    assert payload["primary_control_failure"] == "ambient_client_detected"
    assert payload["secondary_failures"] == ["terminal_resource_unavailable"]
    assert "/" not in repr(payload)


@pytest.mark.parametrize(
    "value",
    (
        "completed",
        "threshold_cancelled_reconciled",
        "control_failure_cancelled_reconciled",
        "child_failed_reconciled",
        "commit_unknown_reconciled_published",
        "commit_unknown_unresolved",
        "cancellation_unreconciled",
        "control_failure_unreconciled",
    ),
)
def test_terminal_category_vocabulary_is_closed(value: str) -> None:
    assert TerminalCategory(value).value == value
