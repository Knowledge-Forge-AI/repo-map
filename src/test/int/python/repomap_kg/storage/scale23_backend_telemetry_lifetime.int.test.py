from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_build_profile

from repomap_kg.storage.run_authority import read_run_authority
from repomap_test_support.postgres_harness import require_postgres_binaries
from scale15_async_storage import AsyncStorageStatistics
from repomap_test_support.scale15_runtime_campaign import (
    expected_authority,
    run_ordinary_refresh,
    run_supervised_refresh,
    start_scale15_runtime,
    stop_scale15_runtime,
)
from scale13_actual_path_readback import read_actual_path_state
from scale14_actual_refresh_supervisor import ProtectedLaunchLimits
from scale15_terminal_contracts import (
    CleanupState,
    ControlFailureCode,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalControlResult,
    TerminalCategory,
)


GRAPH_IDS = (
    "scale23-reference",
    "scale23-long-1",
    "scale23-long-2",
    "scale23-long-3",
    "scale23-early-1",
    "scale23-early-2",
    "scale23-early-3",
    "scale23-premature-eof",
    "scale23-prior",
)
ACK_GRAPH_IDS = ("scale23-ack-reference", "scale23-ack-failure")
EXTRACTION = "refresh.extraction"
LIMITS = ProtectedLaunchLimits(30, 30, 30, 30)


def test_scale23_direct_child_backend_telemetry_lifetime_campaign(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, GRAPH_IDS)
    source_before = fixture.repository.joinpath("app.py").read_bytes()
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference = run_ordinary_refresh(fixture, "scale23-reference")
        assert reference.returncode == 0, reference.stderr
        reference_state = read_actual_path_state(
            fixture.psql_args("scale23-reference")
        )

        for graph_id in ("scale23-long-1", "scale23-long-2", "scale23-long-3"):
            expected = _expected(fixture, graph_id, reference_state)
            long_refresh = run_supervised_refresh(
                fixture,
                graph_id,
                expected,
                cancel_code=EXTRACTION,
                limits=LIMITS,
                control_wait_seconds=5.5,
            )
            assert len(long_refresh) == 2
            result, storage = long_refresh

            assert isinstance(result, TerminalControlResult)
            assert isinstance(storage, AsyncStorageStatistics)
            _assert_published(result)
            assert storage.maximum_in_flight == 1
            assert storage.timeout_count == 0

        for graph_id in (
            "scale23-early-1",
            "scale23-early-2",
            "scale23-early-3",
        ):
            expected = _expected(fixture, graph_id, reference_state)
            early_refresh = run_supervised_refresh(
                fixture,
                graph_id,
                expected,
                cancel_code=EXTRACTION,
                limits=LIMITS,
                control_wait_seconds=0.05,
                fail_after_control=True,
                private_observer_evidence=True,
            )
            assert len(early_refresh) == 3
            result, _storage, evidence = early_refresh

            assert isinstance(result, TerminalControlResult)
            _assert_prebinding_exit_reconciled(result, evidence=evidence)

        prior_refresh = run_ordinary_refresh(fixture, "scale23-prior")
        assert prior_refresh.returncode == 0, prior_refresh.stderr
        prior_state = read_actual_path_state(fixture.psql_args("scale23-prior"))
        prior_structural_digest = prior_state["structural_digest"]
        assert isinstance(prior_structural_digest, str)
        prior_authority = read_run_authority(
            fixture.psql_args("scale23-prior"), "public-fixture"
        )
        prior_publication = prior_authority.latest_receipt_bearing_publication
        prior_latest = prior_authority.latest_recorded_run
        assert prior_publication is not None
        assert prior_latest is not None
        prior_expected = expected_authority(
            fixture,
            "scale23-prior",
            prior_state["family_counts"],
            prior_structural_digest,
            prior_publication_run_id=int(prior_publication.run_id),
            prior_family_counts=prior_state["family_counts"],
            prior_structural_digest=prior_state["structural_digest"],
            prior_latest_recorded_run_id=int(prior_latest.run_id),
        )
        preserved_refresh = run_supervised_refresh(
            fixture,
            "scale23-prior",
            prior_expected,
            cancel_code=EXTRACTION,
            limits=LIMITS,
            control_wait_seconds=5.0,
            close_telemetry_after_control=True,
            private_observer_evidence=True,
        )
        assert len(preserved_refresh) == 3
        preserved, _storage, preserved_evidence = preserved_refresh
        assert isinstance(preserved, TerminalControlResult)
        assert preserved.primary_control_failure is (
            ControlFailureCode.BACKEND_TELEMETRY_FAILED
        ), (preserved.to_payload(), preserved_evidence)
        assert preserved.signal_count == 1
        assert preserved.reconciliation_status is ReconciliationStatus.RECONCILED
        assert preserved.child_quiescent is True
        assert preserved.backend_quiescent is True
        assert preserved.publication_state is (
            PublicationState.PRIOR_PUBLICATION_PRESERVED
        )
        assert preserved.stage_state is StageState.PRE_BINDING_RECONCILED
        assert preserved.cleanup_state is CleanupState.NOT_ELIGIBLE

        premature_expected = _expected(
            fixture,
            "scale23-premature-eof",
            reference_state,
        )
        premature_refresh = run_supervised_refresh(
            fixture,
            "scale23-premature-eof",
            premature_expected,
            cancel_code=EXTRACTION,
            limits=LIMITS,
            control_wait_seconds=5.0,
            close_telemetry_after_control=True,
        )
        assert len(premature_refresh) == 2
        premature, _storage = premature_refresh
        assert isinstance(premature, TerminalControlResult)
        assert premature.primary_control_failure is (
            ControlFailureCode.BACKEND_TELEMETRY_FAILED
        ), premature.to_payload()
        assert premature.signal_count == 1
        assert premature.reconciliation_status is ReconciliationStatus.RECONCILED
        assert premature.child_quiescent is True
        assert premature.backend_quiescent is True
        assert premature.publication_state is PublicationState.NOT_PUBLISHED
        assert premature.stage_state is StageState.PRE_BINDING_RECONCILED
        assert premature.cleanup_state is CleanupState.NOT_ELIGIBLE

        assert fixture.repository.joinpath("app.py").read_bytes() == source_before
    finally:
        stop_scale15_runtime(fixture)


def test_scale23_direct_child_acknowledgement_failure_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, ACK_GRAPH_IDS)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference = run_ordinary_refresh(fixture, "scale23-ack-reference")
        assert reference.returncode == 0, reference.stderr
        reference_state = read_actual_path_state(
            fixture.psql_args("scale23-ack-reference")
        )
        expected = _expected(
            fixture,
            "scale23-ack-failure",
            reference_state,
        )
        ack_refresh = run_supervised_refresh(
            fixture,
            "scale23-ack-failure",
            expected,
            cancel_code=EXTRACTION,
            limits=LIMITS,
            control_wait_seconds=0.05,
            close_ack_after_control=True,
        )
        assert len(ack_refresh) == 2
        result, _storage = ack_refresh

        assert isinstance(result, TerminalControlResult)
        assert result.primary_control_failure is (
            ControlFailureCode.BACKEND_TELEMETRY_FAILED
        ), result.to_payload()
        assert result.reconciliation_status is (
            ReconciliationStatus.RECONCILED
        ), result.to_payload()
        assert result.child_quiescent is True
        assert result.backend_quiescent is True
        assert result.publication_state is PublicationState.NOT_PUBLISHED
        assert result.stage_state is StageState.PRE_STAGE_RECONCILED
        assert result.cleanup_state is CleanupState.NOT_ELIGIBLE
    finally:
        stop_scale15_runtime(fixture)


def _expected(fixture, graph_id, reference_state):
    return expected_authority(
        fixture,
        graph_id,
        reference_state["family_counts"],
        reference_state["structural_digest"],
    )


def _assert_published(result) -> None:
    assert result.terminal_category is TerminalCategory.COMPLETED, result.to_payload()
    assert result.primary_control_failure is None
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert result.signal_count == 0
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    assert result.publication_state is PublicationState.PUBLISHED
    assert result.stage_state is StageState.PUBLISHED_RECONCILED
    assert result.launch_binding_state == "launch_authority_bound"
    assert result.launch_binding_match == "matched"


def _assert_prebinding_exit_reconciled(
    result,
    *,
    publication_state=PublicationState.NOT_PUBLISHED,
    evidence=None,
) -> None:
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED, (
        result.to_payload(),
        evidence,
    )
    assert result.child_exit_code is not None
    if result.child_exit_code == 0:
        assert result.publication_state is PublicationState.PUBLISHED
        assert result.stage_state is StageState.PUBLISHED_RECONCILED
        assert result.primary_control_failure is not (
            ControlFailureCode.BACKEND_TELEMETRY_FAILED
        )
        return
    assert result.signal_count == 0, (result.to_payload(), evidence)
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    assert result.publication_state is publication_state
    assert result.stage_state is StageState.PRE_BINDING_RECONCILED
    assert result.cleanup_state is CleanupState.NOT_ELIGIBLE
    assert result.primary_control_failure is not (
        ControlFailureCode.BACKEND_TELEMETRY_FAILED
    )
    assert ControlFailureCode.BACKEND_TELEMETRY_FAILED not in (
        result.secondary_failures
    )
    assert result.launch_binding_state == "launch_authority_missing"
    assert result.launch_binding_match == "unbound"
