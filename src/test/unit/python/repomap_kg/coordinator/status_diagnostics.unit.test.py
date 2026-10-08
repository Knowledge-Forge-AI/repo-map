"""Untrusted persisted diagnostics never invalidate supported job readback."""
from dataclasses import replace
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast

import pytest

from repomap_kg.coordinator._control_types import JobStatus
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.transport import validate_public_result
from repomap_kg.coordinator.core import (
    CoordinatorStore, SyntheticCoordinator, _coordinator_exception_diagnostic,
)


class DiagnosticStore:
    """Observe the real executor catch without database or subprocess work."""

    def __init__(self):
        self.record: dict[str, str] = {}

    def maintenance_activity(self):
        return nullcontext()

    def claim_next(self, *args, **kwargs):
        return SimpleNamespace(job_id="job-1", attempt=1, instance_id="test", fencing_epoch=1)

    def compare_and_set_state(self, *args, **kwargs):
        return True

    def mark_reconciliation_required(self, claim, **kwargs):
        self.record = kwargs
        return True


@pytest.mark.parametrize(("message", "detail"), [
    pytest.param("invalid refresh capability", ":invalid refresh capability", id="safe"),
    pytest.param("missing /diagfix-7c92/private/source", ":missing [path]", id="posix"),
    pytest.param(r"missing C:\diagfix-7c92\private\source", ":missing [path]", id="windows"),
    pytest.param("password=diagfix-7c92-secret", ":password=[REDACTED]", id="secret"),
    pytest.param("postgresql://svc:diagfix-7c92-url@host/db", "", id="url"),
    pytest.param("svc:diagfix-7c92-userinfo@host", "", id="userinfo"),
    pytest.param("host=example password=diagfix-7c92-dsn", ":host=example password=[REDACTED]", id="dsn"),
    pytest.param("", "", id="empty"),
    pytest.param("one\ntwo", "", id="newline"),
    pytest.param("one\x00two", "", id="control"),
    pytest.param("Traceback (most recent call last):", "", id="trace"),
    pytest.param("bad\ud800", "", id="unicode"),
    pytest.param("x" * 300, ":" + "x" * 223, id="long"),
    pytest.param("é" * 200, ":" + "é" * 111, id="multibyte"),
])
def test_real_executor_catch_preserves_safe_class_provenance(tmp_path, message, detail):
    store = DiagnosticStore()

    def fail(_claim, _cancel):
        raise ValueError(message)

    coordinator = SyntheticCoordinator(cast(CoordinatorStore, store), "test", fail)
    coordinator._epoch = 1
    try:
        assert coordinator.run_once() == "reconciliation_required"
    finally:
        coordinator.shutdown()
    assert store.record == {
        "expected_state": "running", "category": "worker_crash",
        "diagnostic_summary": "coordinator_exception:ValueError" + detail,
    }
    diagnostic = store.record["diagnostic_summary"]
    assert len(diagnostic.encode("utf-8")) <= 256
    assert "diagfix-7c92" not in diagnostic
    assert coordinator._active_workers == 0 and not coordinator._active_cancellations
    service = _service(tmp_path, diagnostic)
    expected = "diagnostic_withheld" if "[" in detail else diagnostic
    for operation in ("status", "wait"):
        assert service._handlers()[operation]({"job_id": "job-1"})["diagnostic_summary"] == expected


@pytest.mark.parametrize(("name", "expected"), [
    ("CustomError", "CustomError"), ("E" * 64, "E" * 64),
    ("E" * 65, "Exception"), ("bad name", "Exception"),
    ("bad\nname", "Exception"), ("Érror", "Exception"),
])
def test_exception_class_identifier_is_bounded(name, expected):
    error = type(name, (Exception,), {})()
    assert _coordinator_exception_diagnostic(error) == "coordinator_exception:" + expected


def test_exception_formatting_and_structured_arguments_are_never_used():
    class CustomError(Exception):
        def __str__(self):
            raise AssertionError("exception formatting must not run")

    class StringSubclass(str):
        pass

    cases: tuple[tuple[object, ...], ...] = (({},), (StringSubclass("detail"),), ("one", "two"))
    for args in cases:
        assert _coordinator_exception_diagnostic(CustomError(*args)) == "coordinator_exception:CustomError"
    assert _coordinator_exception_diagnostic(CustomError("safe")) == "coordinator_exception:CustomError:safe"
    assert _coordinator_exception_diagnostic(KeyError("safe")) == "coordinator_exception:KeyError:safe"


def test_sanitizer_failure_cannot_prevent_real_catch_reconciliation(monkeypatch):
    def broken(_message):
        raise ImportError("synthetic dependency failure")

    monkeypatch.setattr("repomap_kg.coordinator.core.sanitize_diagnostic_summary", broken)
    store = DiagnosticStore()

    def fail(_claim, _cancel):
        raise ValueError("safe")

    coordinator = SyntheticCoordinator(cast(CoordinatorStore, store), "test", fail)
    coordinator._epoch = 1
    try:
        assert coordinator.run_once() == "reconciliation_required"
    finally:
        coordinator.shutdown()
    assert store.record["diagnostic_summary"] == "coordinator_exception:ValueError"


@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
def test_diagnostic_construction_preserves_process_control(monkeypatch, signal):
    def interrupted(_message):
        raise signal()

    monkeypatch.setattr("repomap_kg.coordinator.core.sanitize_diagnostic_summary", interrupted)
    with pytest.raises(signal):
        _coordinator_exception_diagnostic(ValueError("safe"))


def _service(tmp_path, diagnostic, *, state="reconciliation_required", error="worker_crash"):
    status = JobStatus("job-1", "synthetic-diagnostic", state, 1, "commit_unknown",
                       "starting", 0, None, error)
    status = replace(status, diagnostic_summary=diagnostic)
    store = SimpleNamespace(status=lambda job_id: status)
    coordinator = SimpleNamespace(request_cancel=lambda job_id: "cancel_requested")
    return CoordinatorService(coordinator, store, tmp_path, wait_seconds=0.001)


@pytest.mark.parametrize(("diagnostic", "expected"), [
    (None, None), ("", None),
    ("worker_exit:17", "worker_exit:17"),
    ("refresh-failure:permission-denied", "refresh-failure:permission-denied"),
    ("worker_crash:unhandled_exception", "worker_crash:unhandled_exception"),
    ("refresh-failure:missing /synthetic/private/source", "diagnostic_withheld"),
    ("refresh-failure:password=synthetic-sensitive", "diagnostic_withheld"),
    ("refresh-failure:database unavailable", "diagnostic_withheld"),
    ("one;two", "diagnostic_withheld"), ("lone /", "diagnostic_withheld"),
    ("Traceback (most recent call last):\nprivate payload", "diagnostic_withheld"),
    ("Traceback (most recent call last):", "diagnostic_withheld"),
    ("one\u2028two", "diagnostic_withheld"),
    ({"stderr": "private"}, None), (123, None), ("bad\ud800", None),
    ("x" * 300, "x" * 256), ("é" * 200, "é" * 128),
])
@pytest.mark.parametrize("operation", ["status", "wait"])
def test_status_and_wait_sanitize_without_losing_status(tmp_path, diagnostic, expected, operation):
    service = _service(tmp_path, diagnostic)
    result = service._handlers()[operation]({"job_id": "job-1"})
    assert result["state"] == "reconciliation_required"
    assert result["error_category"] == "worker_crash"
    assert validate_public_result(result)
    if expected is None:
        assert "diagnostic_summary" not in result
    else:
        assert result["diagnostic_summary"] == expected
        assert len(expected.encode("utf-8")) <= 256


@pytest.mark.parametrize(("state", "error", "present"), [
    ("running", None, False), ("succeeded", None, False), ("queued", None, False),
    ("queued", "worker_crash", True), ("failed", None, True),
    ("quarantined", None, True), ("reconciliation_required", None, True),
])
def test_diagnostic_status_eligibility(tmp_path, state, error, present):
    service = _service(tmp_path, "worker_exit:17", state=state, error=error)
    result = service._status({"job_id": "job-1"})
    assert ("diagnostic_summary" in result) == present
    assert validate_public_result(result)


def test_quarantine_without_diagnostic_and_cancel_keep_existing_shape(tmp_path):
    service = _service(tmp_path, None, state="quarantined", error=None)
    assert "diagnostic_summary" not in service._status({"job_id": "job-1"})
    assert service._cancel({"job_id": "job-1"}) == {
        "job_id": "job-1", "state": "cancel_requested"}


@pytest.mark.parametrize("value", [None, 1, {}, [], "", "x" * 257, "é" * 129,
    "bad\ud800", "one\ntwo", "one\u2029two", "trace\rback", "a\x00b", "lone /", "one;two",
    "password=synthetic-sensitive", "refresh-failure:database unavailable"])
def test_transport_rejects_malformed_diagnostic(value):
    assert not validate_public_result({"diagnostic_summary": value})


@pytest.mark.parametrize("value", ["worker_exit:17", "refresh-failure:permission-denied",
                                  "diagnostic_withheld", "é" * 128])
def test_transport_accepts_only_bounded_optional_diagnostic(value):
    assert validate_public_result({"diagnostic_summary": value})
    assert validate_public_result({"state": "running"})
