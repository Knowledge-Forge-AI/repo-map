"""Heartbeat recovery diagnostics, acknowledgement and fail-closed contention."""
import pytest

from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import RecoveryDiagnostic
from repomap_test_support.coordinator_core_fakes import FakeStore, terminal


def _diagnostics(coordinator: SyntheticCoordinator) -> tuple[RecoveryDiagnostic, ...]:
    return coordinator.recovery_diagnostics


@pytest.mark.parametrize("error_type", ["LockNotAvailable", "QueryCanceled"])
def test_expected_closure_contention_retains_publication_uncertainty(error_type):
    from psycopg import errors

    store = FakeStore()

    def contended_runner(_claim, _cancel):
        raise getattr(errors, error_type)("bounded lock refusal")

    coordinator = SyntheticCoordinator(store, "coordinator-a", contended_runner)
    coordinator.startup(coordinator.recover_startup)
    try:
        assert coordinator.run_once() == "reconciliation_required"
        assert ("reconcile", "running", "publication_unknown") in store.calls
        assert not any(call[:1] == ("terminated",) for call in store.calls)
    finally:
        coordinator.shutdown()


def test_recovery_error_survives_successful_heartbeat_until_acknowledged():
    from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport

    store = FakeStore()
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda *_: terminal())
    coordinator.startup(lambda: StartupRecoveryReport(1, 0, 1, 0, 0, unexpected=("RuntimeError",)))
    try:
        diagnostic = _diagnostics(coordinator)[0]
        assert diagnostic.error_type == "RuntimeError"
        assert diagnostic.category == "unexpected_recovery_error"
        assert diagnostic.summary == "RuntimeError"
        assert diagnostic.sequence == 1
        assert diagnostic.to_dict() == {
            "category": "unexpected_recovery_error",
            "summary": "RuntimeError",
            "sequence": 1,
        }
        assert coordinator.heartbeat()
        report = coordinator.startup_recovery_report
        assert isinstance(report, StartupRecoveryReport) and report.unexpected == ()
        assert list(_diagnostics(coordinator)) == [diagnostic]
        coordinator._record_startup_recovery_report(StartupRecoveryReport(
            1, 0, 1, 0, 0, unexpected=("ValueError",),
        ))
        coordinator.acknowledge_recovery_diagnostics(diagnostic.sequence)
        assert [item.error_type for item in _diagnostics(coordinator)] == ["ValueError"]
        coordinator.acknowledge_recovery_diagnostics(_diagnostics(coordinator)[-1].sequence)
        assert len(_diagnostics(coordinator)) == 0
    finally:
        coordinator.shutdown()


def test_recovery_diagnostic_logger_is_safe_and_structured(caplog):
    import logging
    from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport

    store = FakeStore()
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda *_: terminal())
    with caplog.at_level(logging.WARNING):
        coordinator.startup(lambda: StartupRecoveryReport(
            1, 0, 1, 0, 0, unexpected=("RuntimeError", "postgresql://secret:credential@private/db")
        ))
    try:
        diags = _diagnostics(coordinator)
        assert len(diags) == 2
        assert diags[0].category == "unexpected_recovery_error"
        assert diags[0].summary == "RuntimeError"
        assert diags[1].category == "unexpected_recovery_error"
        assert diags[1].summary == "Exception"

        records = [r for r in caplog.records if r.name == "repomap_kg.coordinator.startup_recovery"]
        assert len(records) == 2
        for r in records:
            assert "secret" not in r.message
            assert "credential" not in r.message
            assert "private" not in r.message
            assert "postgresql://" not in r.message
            extra_diag = getattr(r, "recovery_diagnostic", None)
            assert extra_diag is not None
            assert set(extra_diag.keys()) == {"category", "summary", "sequence"}
            assert extra_diag["category"] == "unexpected_recovery_error"
            assert extra_diag["summary"] in {"RuntimeError", "Exception"}
    finally:
        coordinator.shutdown()


def test_recovery_diagnostics_are_bounded_redacted_and_contention_is_separate():
    from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport

    coordinator = SyntheticCoordinator(FakeStore(), "coordinator-a", lambda *_: terminal())
    coordinator.startup(coordinator.recover_startup)
    try:
        coordinator._record_startup_recovery_report(StartupRecoveryReport(
            1, 0, 1, 0, 0, refused=1,
        ))
        assert len(_diagnostics(coordinator)) == 0
        for _ in range(40):
            coordinator._record_startup_recovery_report(StartupRecoveryReport(
                1, 0, 1, 0, 0, unexpected=("postgresql://secret:credential@private/db",),
            ))
        assert len(_diagnostics(coordinator)) == 32
        assert _diagnostics(coordinator)[0].sequence == 9
        assert {item.error_type for item in _diagnostics(coordinator)} == {"Exception"}
        for invalid in (-1, True, "1"):
            with pytest.raises(ValueError, match="sequence"):
                getattr(coordinator, "acknowledge_recovery_diagnostics")(invalid)
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("site", ["reader", "reconciliation"])
def test_programming_errors_reach_health_and_log_without_raw_messages(tmp_path, monkeypatch, caplog, site):
    from dataclasses import replace
    from unittest.mock import create_autospec
    from repomap_kg.coordinator._coordinator_protocols import ServiceStore
    from repomap_kg.coordinator.service import CoordinatorService
    from repomap_test_support.coordinator_core_fakes import Claim

    store = FakeStore()
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda *_: terminal())
    coordinator.startup(coordinator.recover_startup)
    original = TypeError("postgresql://secret:credential@private/db")

    def fail(*_args, **_kwargs):
        raise original

    monkeypatch.setattr(store, "reconciliation_claims", lambda _limit: (replace(Claim(), graph_lease_fencing_epoch=1),))
    if site == "reader":
        monkeypatch.setattr(coordinator, "_publication_reader", fail)
    else:
        monkeypatch.setattr(store, "reconcile_publication", fail)
    try:
        with caplog.at_level("WARNING"):
            if site == "reader":
                report = coordinator.recover_startup()
                assert report.unexpected == ("TypeError",)
                coordinator._record_startup_recovery_report(report)
            else:
                with pytest.raises(TypeError) as raised:
                    coordinator.recover_startup()
                assert raised.value is original
        service = CoordinatorService(coordinator, create_autospec(ServiceStore, instance=True), tmp_path)
        assert service.health()["recovery_diagnostics"] == [{
            "category": "unexpected_recovery_error", "summary": "TypeError", "sequence": 1,
        }]
        assert "secret" not in caplog.text and "private/db" not in caplog.text
    finally:
        coordinator.shutdown()


def test_structured_log_handlers_can_read_diagnostics_without_lock_reentrancy(monkeypatch):
    from repomap_kg.coordinator import startup_recovery as recovery

    coordinator = SyntheticCoordinator(FakeStore(), "coordinator-a", lambda *_: terminal())
    seen = []

    def observe(diagnostic):
        assert coordinator._recovery_diagnostics_lock.acquire(blocking=False)
        coordinator._recovery_diagnostics_lock.release()
        seen.append(coordinator.recovery_diagnostics[-1])
        assert seen[-1] == diagnostic

    monkeypatch.setattr(recovery, "_emit_structured_diagnostic_log", observe)
    coordinator.startup(lambda: recovery.StartupRecoveryReport(0, 0, 0, 0, 0, unexpected=("TypeError",)))
    try:
        assert len(seen) == 1
    finally:
        coordinator.shutdown()
