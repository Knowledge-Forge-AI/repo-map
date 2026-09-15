from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_build_profile

from actual_refresh_failure_causality import FailureCandidate
from repomap_kg.storage.run_authority import read_run_authority
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.scale15_runtime_campaign import (
    Scale15RuntimeFixture,
    expected_authority,
    run_ordinary_refresh,
    run_supervised_refresh,
    start_scale15_runtime,
    stop_scale15_runtime,
)
from repomap_test_support.test_cov5k_r2_fix3_sibling_oracle import (
    validate_sibling_campaign_oracle,
)
from scale13_actual_path_readback import read_actual_path_state
from scale14_actual_refresh_supervisor import ProtectedLaunchLimits
from scale15_async_storage import AsyncStorageStatistics
from scale15_terminal_contracts import (
    ControlFailureCode,
    ExpectedRefreshAuthority,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalCategory,
    TerminalControlResult,
)
from scale28_backend_observer_session import (
    ObserverSessionSnapshot,
    ObserverSessionState,
)
from scale28_preparation_authority_cleanup import PreparationAuthoritySnapshot
from typing import TypedDict


EXTRACTION = "refresh.extraction"
LIMITS = ProtectedLaunchLimits(30, 30, 30, 30)
LONG_GRAPH_IDS = ("scale28-long-reference",) + tuple(f"scale28-long-{i:02d}" for i in range(20))
MIXED_GRAPH_IDS = (
    "scale28-mixed-reference", "scale28-prior", "scale28-preconnection-exit",
) + tuple(f"scale28-mixed-{i:02d}" for i in range(10))
FIX12_MIXED_GRAPH_IDS = ("scale28-fix12-mixed-reference",) + tuple(
    f"scale28-fix12-mixed-{i:02d}" for i in range(15)
)


class ObserverEvidence(TypedDict):
    causality: tuple[FailureCandidate, ...]
    session: ObserverSessionSnapshot
    preparation: PreparationAuthoritySnapshot


def _run_supervised(
    fixture: Scale15RuntimeFixture, graph_id: str, expected: ExpectedRefreshAuthority,
    *, cancel_code: str | None, limits: ProtectedLaunchLimits, injection: str | None = None,
    control_wait_seconds: float = 5.0, fail_after_control: bool = False,
    private_observer_evidence: bool = True,
) -> tuple[TerminalControlResult, AsyncStorageStatistics, ObserverEvidence]:
    outcome = run_supervised_refresh(
        fixture, graph_id, expected, cancel_code=cancel_code, limits=limits,
        injection=injection, control_wait_seconds=control_wait_seconds,
        fail_after_control=fail_after_control,
        private_observer_evidence=private_observer_evidence,
    )
    assert len(outcome) == 3
    result, storage, raw = outcome
    assert isinstance(raw, dict)
    causality, session, preparation = raw.get("causality"), raw.get("session"), raw.get("preparation")
    assert isinstance(causality, tuple)
    assert all(isinstance(candidate, FailureCandidate) for candidate in causality)
    assert isinstance(session, ObserverSessionSnapshot)
    assert isinstance(preparation, PreparationAuthoritySnapshot)
    evidence = ObserverEvidence(
        causality=tuple(c for c in causality if isinstance(c, FailureCandidate)),
        session=session,
        preparation=preparation,
    )
    return result, storage, evidence


def test_scale28_twenty_long_extraction_observer_campaigns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, LONG_GRAPH_IDS)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference_state = _reference_state(fixture, "scale28-long-reference")
        for graph_id in LONG_GRAPH_IDS[1:]:
            result, storage, evidence = _run_supervised(
                fixture, graph_id, _expected(fixture, graph_id, reference_state),
                cancel_code=EXTRACTION, limits=LIMITS, control_wait_seconds=5.5,
                private_observer_evidence=True,
            )
            _assert_published(result, evidence)
            assert storage.maximum_in_flight == 1
            assert storage.timeout_count == 0
            assert evidence["causality"] == ()
            assert evidence["session"].state is ObserverSessionState.CLOSED
    finally:
        stop_scale15_runtime(fixture)


def test_scale28_ten_mixed_observer_success_and_failure_campaigns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, MIXED_GRAPH_IDS)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference_state = _reference_state(fixture, "scale28-mixed-reference")
        scenarios = (
            (None, None), ("observer_active_summary_failed", "observer_active_summary"),
            ("observer_event_apply_failed", "observer_event_apply"),
            ("observer_connection_lost", "observer_connection_lost"),
        ) * 2 + ((None, None), ("observer_active_summary_failed", "observer_active_summary"))
        published = 0
        observed_injected_boundaries: set[str] = set()
        source_owned_preemptions = 0
        for graph_id, (injection, boundary) in zip(
            MIXED_GRAPH_IDS[3:], scenarios, strict=True
        ):
            result, _storage, evidence = _run_supervised(
                fixture, graph_id, _expected(fixture, graph_id, reference_state),
                cancel_code=EXTRACTION, limits=LIMITS, injection=injection,
                control_wait_seconds=5.0, private_observer_evidence=True,
            )
            first = next(iter(evidence["causality"]), None)
            if (
                first is not None
                and first.lifecycle_boundary == "observer_operation_wait_timeout"
                and first.test_injected is False
            ):
                _assert_observer_deadline_preemption(result, evidence)
                source_owned_preemptions += 1
            elif injection is None:
                _assert_published(result, evidence)
                assert evidence["causality"] == ()
                published += 1
            else:
                assert boundary is not None
                _assert_observer_failure(result, evidence, boundary)
                observed_injected_boundaries.add(boundary)

        validate_sibling_campaign_oracle(
            published=published, observed_injected_boundaries=observed_injected_boundaries,
            source_owned_preemptions=source_owned_preemptions,
        )

        _assert_prior_publication_preserved(fixture, reference_state)
        _assert_child_exit_before_connection_is_not_observer_failure(fixture, reference_state)
    finally:
        stop_scale15_runtime(fixture)


def test_scale28_hybrid_prior_publication_preserves_source_owned_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, ("scale28-mixed-reference", "scale28-prior"))
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference_state = _reference_state(fixture, "scale28-mixed-reference")
        _assert_prior_publication_preserved(fixture, reference_state)
    finally:
        stop_scale15_runtime(fixture)


def test_scale28_fix12_fifteen_consecutive_mixed_configured_campaigns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, FIX12_MIXED_GRAPH_IDS)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        reference_state = _reference_state(fixture, "scale28-fix12-mixed-reference")
        scenarios = (
            (None, None), ("observer_active_summary_failed", "observer_active_summary"),
            ("observer_event_apply_failed", "observer_event_apply"),
            ("observer_connection_lost", "observer_connection_lost"),
        ) * 3 + (
            (None, None), ("observer_active_summary_failed", "observer_active_summary"),
            ("observer_event_apply_failed", "observer_event_apply"),
        )
        published = 0
        observed_injected_boundaries: set[str] = set()
        source_owned_preemptions = 0
        for graph_id, (injection, boundary) in zip(
            FIX12_MIXED_GRAPH_IDS[1:], scenarios, strict=True
        ):
            result, _storage, evidence = _run_supervised(
                fixture, graph_id, _expected(fixture, graph_id, reference_state),
                cancel_code=EXTRACTION, limits=LIMITS, injection=injection,
                control_wait_seconds=5.0, private_observer_evidence=True,
            )
            first = next(iter(evidence["causality"]), None)
            if (
                first is not None
                and first.lifecycle_boundary == "observer_operation_wait_timeout"
                and first.test_injected is False
            ):
                _assert_observer_deadline_preemption(result, evidence)
                source_owned_preemptions += 1
            elif injection is None:
                _assert_published(result, evidence)
                assert evidence["causality"] == ()
                published += 1
            else:
                assert boundary is not None
                _assert_observer_failure(result, evidence, boundary)
                observed_injected_boundaries.add(boundary)
            assert all(
                c != "preparation_timeout"
                for c, _ in evidence["preparation"].attempt_failures
            )
        assert published >= 1
        assert observed_injected_boundaries == {
            "observer_active_summary",
            "observer_connection_lost",
            "observer_event_apply",
        }
        assert source_owned_preemptions <= 1
    finally:
        stop_scale15_runtime(fixture)


def test_scale28_fix12_three_entirely_fresh_public_rehearsals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    runtime_homes: set[Path] = set()
    runtime_identities: set[tuple[str, str]] = set()
    for rehearsal in range(3):
        monkeypatch.delenv("REPOMAP_PG_PASSWORD", raising=False)
        monkeypatch.delenv("PGPASSWORD", raising=False)
        root = tmp_path / f"fresh-rehearsal-{rehearsal}"
        root.mkdir()
        reference_id = f"scale28-fresh-reference-{rehearsal}"
        rehearsal_id = f"scale28-fresh-candidate-{rehearsal}"
        fixture = start_scale15_runtime(root, (reference_id, rehearsal_id))
        runtime_homes.add(fixture.home)
        runtime_identities.add((fixture.plan.identity.home_hash, fixture.plan.identity.postgres_container))
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
        monkeypatch.setenv("PGPASSWORD", fixture.password)
        try:
            reference_state = _reference_state(fixture, reference_id)
            result, storage, evidence = _run_supervised(
                fixture, rehearsal_id, _expected(fixture, rehearsal_id, reference_state),
                cancel_code=EXTRACTION, limits=LIMITS, control_wait_seconds=5.5,
                private_observer_evidence=True,
            )
            _assert_published(result, evidence)
            assert storage.maximum_in_flight == 1
            assert storage.timeout_count == 0
            assert evidence["preparation"].attempt_failures == ()
        finally:
            stop_scale15_runtime(fixture)

    assert len(runtime_homes) == 3
    assert len(runtime_identities) == 3


def _reference_state(fixture, graph_id):
    reference = run_ordinary_refresh(fixture, graph_id)
    assert reference.returncode == 0, reference.stderr
    return read_actual_path_state(fixture.psql_args(graph_id))


def _expected(fixture, graph_id, reference_state):
    return expected_authority(
        fixture,
        graph_id,
        reference_state["family_counts"],
        reference_state["structural_digest"],
    )


def _assert_published(result, evidence) -> None:
    assert result.terminal_category is TerminalCategory.COMPLETED, (result.to_payload(), evidence)
    assert result.primary_control_failure is None
    assert result.signal_count == 0
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    assert result.publication_state is PublicationState.PUBLISHED
    assert result.stage_state is StageState.PUBLISHED_RECONCILED


def _assert_observer_failure(
    result,
    evidence,
    boundary,
    *,
    publication_state=PublicationState.NOT_PUBLISHED,
) -> None:
    context = (result.to_payload(), evidence)
    assert result.primary_control_failure is ControlFailureCode.BACKEND_OBSERVER_FAILED, context
    assert result.signal_count == 1, context
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED, context
    assert result.child_quiescent is True, context
    assert result.backend_quiescent is True, context
    assert result.publication_state is publication_state, context
    assert evidence["session"].state is ObserverSessionState.CLOSED, context
    first = evidence["causality"][0]
    assert first.code == "backend_observer_failed", context
    assert first.lifecycle_boundary == boundary, (
        first.lifecycle_boundary, boundary, result.to_payload(), evidence,
    )
    assert first.test_injected is True, context


def _assert_observer_deadline_preemption(result, evidence) -> None:
    context = (result.to_payload(), evidence)
    assert result.primary_control_failure is ControlFailureCode.BACKEND_OBSERVER_FAILED, context
    assert result.signal_count == 1, context
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED, context
    assert result.child_quiescent is True, context
    assert result.backend_quiescent is True, context
    assert result.publication_state is PublicationState.NOT_PUBLISHED, context
    assert evidence["session"].state is ObserverSessionState.CLOSED, context
    first = evidence["causality"][0]
    assert first.code == "backend_observer_failed", context
    assert first.lifecycle_boundary == "observer_operation_wait_timeout", context
    assert first.existed_before_child_release is True, context
    assert first.test_injected is False, context


def _assert_prior_publication_preserved(fixture, reference_state) -> None:
    ordinary = run_ordinary_refresh(fixture, "scale28-prior")
    assert ordinary.returncode == 0, ordinary.stderr
    prior_state = read_actual_path_state(fixture.psql_args("scale28-prior"))
    prior_authority = read_run_authority(fixture.psql_args("scale28-prior"), "public-fixture")
    prior_publication = prior_authority.latest_receipt_bearing_publication
    prior_latest = prior_authority.latest_recorded_run
    assert prior_publication is not None
    assert prior_latest is not None
    expected = expected_authority(
        fixture, "scale28-prior",
        reference_state["family_counts"], reference_state["structural_digest"],
        prior_publication_run_id=int(prior_publication.run_id),
        prior_family_counts=prior_state["family_counts"],
        prior_structural_digest=prior_state["structural_digest"],
        prior_latest_recorded_run_id=int(prior_latest.run_id),
    )
    result, _storage, evidence = _run_supervised(
        fixture, "scale28-prior", expected,
        cancel_code=EXTRACTION, limits=LIMITS,
        injection="observer_active_summary_failed", control_wait_seconds=5.0,
        private_observer_evidence=True,
    )
    _assert_observer_failure(
        result, evidence, "observer_active_summary",
        publication_state=PublicationState.PRIOR_PUBLICATION_PRESERVED,
    )
    assert result.publication_state is PublicationState.PRIOR_PUBLICATION_PRESERVED
    assert result.stage_state is StageState.PRE_BINDING_RECONCILED


def _assert_child_exit_before_connection_is_not_observer_failure(fixture, reference_state) -> None:
    graph_id = "scale28-preconnection-exit"
    result, _storage, evidence = _run_supervised(
        fixture, graph_id, _expected(fixture, graph_id, reference_state),
        cancel_code=EXTRACTION, limits=LIMITS, control_wait_seconds=0.05,
        fail_after_control=True, private_observer_evidence=True,
    )

    assert (
        result.primary_control_failure is not ControlFailureCode.BACKEND_OBSERVER_FAILED
    ), result.to_payload()
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert result.child_quiescent is True
    assert result.backend_quiescent is True
    if result.child_exit_code == 0:
        assert result.publication_state is PublicationState.PUBLISHED
        assert result.stage_state is StageState.PUBLISHED_RECONCILED
    else:
        assert result.publication_state is PublicationState.NOT_PUBLISHED
        assert result.stage_state is StageState.PRE_BINDING_RECONCILED
    assert all(
        candidate.code != "backend_observer_failed"
        for candidate in evidence["causality"]
    )
