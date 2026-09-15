from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_build_profile

from repomap_kg.storage.run_authority import read_run_authority
from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_kg.storage.staging_phase_events import STAGING_PHASE_CODES
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.scale15_runtime_campaign import (
    expected_authority,
    run_ordinary_refresh,
    run_supervised_refresh,
    start_scale15_runtime,
    stop_scale15_runtime,
)
from actual_refresh_failure_causality import FailureCandidate
from scale13_actual_path_readback import read_actual_path_state
from scale14_actual_refresh_supervisor import ProtectedLaunchLimits
from scale15_actual_path_readback import read_scale15_terminal_state
from scale15_terminal_contracts import (
    ControlFailureCode,
    TerminalControlResult,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalCategory,
)
from scale15_async_storage import AsyncStorageStatistics


GRAPH_IDS = (
    "scale15-reference",
    "scale15-success",
    "scale15-threshold",
    "scale15-prior",
    "scale15-sustained",
    "scale15-startup-ambient",
    "scale15-ambient",
    "scale15-telemetry",
    "scale15-event",
    "scale15-resource",
    "scale15-attribution",
)
TARGET_OPERATION = "staging.family_copy.files"


def _normalize_refresh(
    value: tuple[object, ...],
) -> tuple[TerminalControlResult, AsyncStorageStatistics, dict[str, object] | None]:
    if len(value) not in {2, 3}:
        raise AssertionError("unexpected supervised refresh result")
    result = value[0]
    storage = value[1]
    assert isinstance(result, TerminalControlResult)
    assert isinstance(storage, AsyncStorageStatistics)
    evidence = value[2] if len(value) == 3 else None
    if evidence is not None:
        assert isinstance(evidence, dict)
    return result, storage, evidence


def test_scale15_real_storage_terminal_authority_campaigns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, GRAPH_IDS)
    source_before = fixture.repository.joinpath("app.py").read_bytes()
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference = run_ordinary_refresh(fixture, "scale15-reference")
        assert reference.returncode == 0, reference.stderr
        reference_state = read_actual_path_state(
            fixture.psql_args("scale15-reference")
        )
        structural_digest = reference_state["structural_digest"]
        assert isinstance(structural_digest, str)
        reference_expected = expected_authority(
            fixture,
            "scale15-reference",
            reference_state["family_counts"],
            structural_digest,
        )
        assert read_scale15_terminal_state(
            fixture.psql_args("scale15-reference"), reference_expected
        ).publication_state is PublicationState.PUBLISHED

        success_expected = expected_authority(
            fixture,
            "scale15-success",
            reference_state["family_counts"],
            structural_digest,
        )
        success, success_storage, success_evidence = _normalize_refresh(
            run_supervised_refresh(
                fixture,
                "scale15-success",
                success_expected,
                cancel_code=None,
                limits=ProtectedLaunchLimits(30, 30, 30, 30),
                private_observer_evidence=True,
            )
        )
        _assert_success(success, success_evidence)
        expected_phases = tuple(
            code
            for code in STAGING_PHASE_CODES
            if not code.startswith("staging.family_spool.")
            and code != "refresh.observation_spool_cleanup"
        ) + ("refresh.observation_spool_cleanup",)
        assert success.phase_sequence == expected_phases
        assert success.operation_sequence == tuple(
            code
            for code in STAGING_OPERATION_DESCRIPTORS
            if code != "cleanup.stage"
        )
        assert success_storage.maximum_in_flight == 1

        threshold_expected = expected_authority(
            fixture,
            "scale15-threshold",
            reference_state["family_counts"],
            structural_digest,
        )
        threshold, threshold_storage, _ = _normalize_refresh(
            run_supervised_refresh(
                fixture,
                "scale15-threshold",
                threshold_expected,
                cancel_code=TARGET_OPERATION,
                limits=ProtectedLaunchLimits(30, 1, 30, 30),
            )
        )
        _assert_cancelled(threshold, TerminalCategory.THRESHOLD_CANCELLED_RECONCILED)
        assert threshold.active_boundary_at_stop == TARGET_OPERATION
        assert threshold.failure_order[0] == "threshold_limit_crossed"
        assert threshold_storage.maximum_in_flight == 1

        prior = run_ordinary_refresh(fixture, "scale15-prior")
        assert prior.returncode == 0, prior.stderr
        prior_state = read_actual_path_state(fixture.psql_args("scale15-prior"))
        prior_structural_digest = prior_state["structural_digest"]
        assert isinstance(prior_structural_digest, str)
        prior_authority = read_run_authority(
            fixture.psql_args("scale15-prior"), "public-fixture"
        )
        prior_publication = prior_authority.latest_receipt_bearing_publication
        assert prior_publication is not None
        prior_expected = expected_authority(
            fixture,
            "scale15-prior",
            prior_state["family_counts"],
            prior_structural_digest,
            prior_publication_run_id=int(prior_publication.run_id),
            prior_family_counts=prior_state["family_counts"],
            prior_structural_digest=prior_structural_digest,
            prior_latest_recorded_run_id=int(prior_publication.run_id),
        )
        preserved, _, _ = _normalize_refresh(
            run_supervised_refresh(
                fixture,
                "scale15-prior",
                prior_expected,
                cancel_code=TARGET_OPERATION,
                limits=ProtectedLaunchLimits(30, 1, 30, 30),
            )
        )
        _assert_cancelled(
            preserved, TerminalCategory.THRESHOLD_CANCELLED_RECONCILED
        )
        assert preserved.publication_state is (
            PublicationState.PRIOR_PUBLICATION_PRESERVED
        )
        assert preserved.failure_order[0] == "threshold_limit_crossed"

        sustained_expected = expected_authority(
            fixture,
            "scale15-sustained",
            reference_state["family_counts"],
            structural_digest,
        )
        sustained, sustained_storage, _ = _normalize_refresh(
            run_supervised_refresh(
                fixture,
                "scale15-sustained",
                sustained_expected,
                cancel_code=TARGET_OPERATION,
                limits=ProtectedLaunchLimits(30, 30, 30, 30),
            )
        )
        _assert_success(sustained)
        assert sustained_storage.completed_samples >= 2
        assert sustained_storage.maximum_in_flight == 1
        assert sustained_storage.timeout_count == 0

        startup_ambient_expected = expected_authority(
            fixture,
            "scale15-startup-ambient",
            reference_state["family_counts"],
            structural_digest,
        )
        startup_ambient, _storage, _ = _normalize_refresh(
            run_supervised_refresh(
                fixture,
                "scale15-startup-ambient",
                startup_ambient_expected,
                cancel_code=None,
                limits=ProtectedLaunchLimits(30, 30, 30, 30),
                injection="startup_ambient_client",
            )
        )
        assert startup_ambient.primary_control_failure is (
            ControlFailureCode.AMBIENT_CLIENT_DETECTED
        ), startup_ambient.to_payload()
        assert startup_ambient.failure_order[0] == "ambient_client_detected"
        assert startup_ambient.failure_order.count("ambient_client_detected") == 1
        assert startup_ambient.launch_binding_state == "launch_authority_missing"
        assert startup_ambient.launch_binding_match == "unbound"
        assert startup_ambient.signal_count == 1
        assert startup_ambient.child_quiescent is True
        assert startup_ambient.backend_quiescent is True

        control_cases = (
            (
                "scale15-ambient",
                "ambient_client_detected",
                ControlFailureCode.AMBIENT_CLIENT_DETECTED,
                TARGET_OPERATION,
            ),
            (
                "scale15-telemetry",
                "backend_telemetry_failed",
                ControlFailureCode.BACKEND_TELEMETRY_FAILED,
                TARGET_OPERATION,
            ),
            (
                "scale15-event",
                "event_transport_failed",
                ControlFailureCode.EVENT_TRANSPORT_FAILED,
                "guard.source_index_stage",
            ),
            (
                "scale15-resource",
                "resource_reader_unavailable",
                ControlFailureCode.RESOURCE_READER_UNAVAILABLE,
                "guard.source_index_stage",
            ),
            (
                "scale15-attribution",
                "operation_attribution_unknown",
                ControlFailureCode.OPERATION_ATTRIBUTION_UNKNOWN,
                "guard.source_index_stage",
            ),
        )
        for graph_id, injection, expected_failure, target in control_cases:
            expected = expected_authority(
                fixture,
                graph_id,
                reference_state["family_counts"],
                structural_digest,
            )
            result, storage, evidence = _normalize_refresh(
                run_supervised_refresh(
                    fixture,
                    graph_id,
                    expected,
                    cancel_code=target,
                    limits=ProtectedLaunchLimits(30, 30, 30, 30),
                    injection=injection,
                    private_observer_evidence=True,
                )
            )
            assert evidence is not None
            causality = evidence["causality"]
            assert isinstance(causality, tuple)
            first_failure = next(iter(causality), None)
            assert first_failure is None or isinstance(first_failure, FailureCandidate)
            authoritative_failure = (
                ControlFailureCode.BACKEND_OBSERVER_FAILED
                if first_failure is not None
                and first_failure.lifecycle_boundary
                == "observer_operation_wait_timeout"
                and first_failure.test_injected is False
                else expected_failure
            )
            assert result.primary_control_failure is authoritative_failure, (
                graph_id,
                result.to_payload(),
                evidence,
            )
            assert result.failure_order[0] == authoritative_failure.value
            _assert_cancelled(
                result,
                TerminalCategory.CONTROL_FAILURE_CANCELLED_RECONCILED,
            )
            assert storage.maximum_in_flight == 1
        assert fixture.repository.joinpath("app.py").read_bytes() == source_before
    finally:
        stop_scale15_runtime(fixture)


def _assert_success(result, evidence=None) -> None:
    assert result.terminal_category is TerminalCategory.COMPLETED, (
        result.to_payload(),
        evidence,
    )
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert result.signal_count == 0
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    assert result.terminal_resource_available is True
    assert result.publication_state is PublicationState.PUBLISHED
    assert result.stage_state is StageState.PUBLISHED_RECONCILED
    assert result.launch_binding_state == "launch_authority_bound"
    assert result.launch_binding_match == "matched"


def _assert_cancelled(result, category: TerminalCategory) -> None:
    assert result.terminal_category is category, result.to_payload()
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert result.signal_count == 1
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    assert result.publication_state in {
        PublicationState.NOT_PUBLISHED,
        PublicationState.PRIOR_PUBLICATION_PRESERVED,
    }
    assert result.stage_state is StageState.FAILED_RECONCILED
    assert result.launch_binding_state == "launch_authority_bound"
    assert result.launch_binding_match == "matched"
