"""Lifecycle boundary waiting and terminal read verification tests."""

from __future__ import annotations
import socket
from threading import Event, Thread
from types import SimpleNamespace
import pytest
import repomap_test_support.scale15_runtime_campaign as runtime_campaign
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventFrame,
)
from repomap_test_support.scale15_runtime_campaign import (
    _InjectedChannel,
    _InjectedResources,
)
from scale15_terminal_contracts import ControlFailure, ControlFailureCode
from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_test_support.scale15_runtime_campaign import (
    _InjectedBackend,
)
from scale14_backend_monitor import BackendMonitorError


class _Channel:
    def __init__(self, frame):
        self.frame = frame

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        del timeout_seconds
        if readiness is not None:
            readiness()
        if validator is not None:
            validator(self.frame)
        return self.frame

    def close(self):
        pass


class _Backend:
    def __init__(self):
        self.startup_timeout_seconds = None

    def startup_summary(self, *, timeout_seconds=0.5):
        self.startup_timeout_seconds = timeout_seconds
        return {"observer": 1, "ambient_client": 0}

    def summary(self):
        return {"observer": 1}


class _Resources:
    def capture(self, *, force=False):
        return {"force": force}

    def close(self):
        pass


def _phase(sequence: int, code: str) -> StagingEventFrame:
    return StagingEventFrame(
        sequence,
        "phase",
        {"phase_code": code, "event_category": "started"},
    )


def test_resource_error_precedes_later_target_activation() -> None:
    target = "staging.family_copy.files"
    channel = _InjectedChannel(
        _Channel(_phase(1, "refresh.source_discovery")),
        "resource_reader_unavailable",
        target,
    )
    sample_entered = Event()
    allow_failure = Event()
    failures = []

    class _InFlightResources(_Resources):
        def capture(self, *, force=False):
            del force
            sample_entered.set()
            assert allow_failure.wait(1.0)
            raise ControlFailure(ControlFailureCode.STORAGE_COUNTER_DECREASED)

    resources = _InjectedResources(
        _InFlightResources(),
        "resource_reader_unavailable",
        channel,
    )

    def capture() -> None:
        try:
            resources.capture()
        except BaseException as error:
            failures.append(error)

    sampler = Thread(target=capture)
    sampler.start()
    assert sample_entered.wait(1.0)
    allow_failure.set()
    sampler.join(timeout=1.0)
    channel._channel.frame = _phase(2, target)
    channel.receive(timeout_seconds=0.1)

    assert not sampler.is_alive()
    assert len(failures) == 1
    failure = failures[0]
    assert isinstance(failure, ControlFailure)
    assert failure.code is ControlFailureCode.STORAGE_COUNTER_DECREASED
    assert channel.target_seen


def test_in_flight_resource_sample_does_not_delay_target_activation() -> None:
    target = "guard.source_index_stage"
    sender_socket, receiver_socket = socket.socketpair()
    sender = StagingEventChannel(
        sender_socket,
        acknowledgement_timeout_seconds=0.05,
    )
    channel = _InjectedChannel(
        StagingEventChannel(receiver_socket),
        "resource_reader_unavailable",
        target,
    )
    sample_entered = Event()
    allow_sample = Event()

    class _InFlightResources(_Resources):
        def capture(self, *, force=False):
            del force
            sample_entered.set()
            assert allow_sample.wait(1.0)
            raise ControlFailure(ControlFailureCode.STORAGE_COUNTER_DECREASED)

    resources = _InjectedResources(
        _InFlightResources(),
        "resource_reader_unavailable",
        channel,
    )
    sample_failures = []
    send_failures = []

    def capture() -> None:
        try:
            resources.capture()
        except BaseException as error:
            sample_failures.append(error)

    def send() -> None:
        try:
            sender.send(
                "phase",
                {"phase_code": target, "event_category": "started"},
            )
        except BaseException as error:
            send_failures.append(error)

    sampler = Thread(target=capture)
    sending = Thread(target=send)
    sampler_started = False
    sending_started = False
    try:
        sampler.start()
        sampler_started = True
        assert sample_entered.wait(1.0)
        sending.start()
        sending_started = True
        assert channel.receive(timeout_seconds=0.2).sequence == 1
        sending.join(timeout=0.2)
        assert not sending.is_alive()
        assert send_failures == []
        assert channel.target_seen
        allow_sample.set()
        sampler.join(timeout=1.0)

        assert len(sample_failures) == 1
        sample_failure = sample_failures[0]
        assert isinstance(sample_failure, ControlFailure)
        assert sample_failure.code is (
            ControlFailureCode.STORAGE_COUNTER_DECREASED
        )
        with pytest.raises(ControlFailure) as captured:
            resources.capture()
        assert captured.value.code is (
            ControlFailureCode.RESOURCE_READER_UNAVAILABLE
        )
    finally:
        allow_sample.set()
        sender.close()
        channel.close()
        if sending_started:
            sending.join(timeout=1.0)
        if sampler_started:
            sampler.join(timeout=1.0)


def test_event_transport_injection_fails_once_then_allows_terminal_read() -> None:
    target = "merge.files"
    channel = _InjectedChannel(
        _Channel(
            StagingEventFrame(
                1,
                "operation",
                {"operation_code": target, "event_category": "started"},
            )
        ),
        "event_transport_failed",
        target,
    )

    channel.receive(timeout_seconds=0.1)
    with pytest.raises(OSError, match="transport"):
        channel.receive(timeout_seconds=0.1)

    channel._channel.frame = _phase(2, "refresh.extraction")
    assert channel.receive(timeout_seconds=0.1).sequence == 2




def test_fresh_backend_authority_performs_exactly_one_terminal_read(
    monkeypatch,
) -> None:
    summaries = iter(
        (
            {"observer": 1, "ambient_client": 1, "unknown": 0},
            {"observer": 1, "ambient_client": 0, "unknown": 0},
            {"observer": 1, "ambient_client": 0, "unknown": 0},
        )
    )
    observed = []

    def read_summary(_psql_args):
        summary = next(summaries)
        observed.append(summary)
        return summary

    monkeypatch.setattr(
        runtime_campaign,
        "read_terminal_backend_summary",
        read_summary,
    )
    monkeypatch.setattr(runtime_campaign.time, "sleep", lambda _seconds: None)

    summary = runtime_campaign._wait_fresh_backend(("public-safe",))

    assert observed == [
        {"observer": 1, "ambient_client": 1, "unknown": 0}
    ]
    assert summary == {"observer": 1, "ambient_client": 1, "unknown": 0}


def test_backend_telemetry_failure_waits_for_selected_lifecycle_boundary() -> None:
    target = "staging.family_copy.files"
    channel = _InjectedChannel(
        _Channel(
            StagingEventFrame(
                1,
                "phase",
                {
                    "phase_code": "refresh.source_discovery",
                    "event_category": "started",
                },
            )
        ),
        "backend_telemetry_failed",
        target,
    )
    backend = _InjectedBackend(_Backend(), "backend_telemetry_failed", channel)

    assert backend.summary() == {"observer": 1}

    channel._channel.frame = StagingEventFrame(
        2,
        "phase",
        {"phase_code": target, "event_category": "started"},
    )
    channel.receive(timeout_seconds=0.1)

    with pytest.raises(BackendMonitorError, match="telemetry"):
        backend.summary()


def test_backend_startup_summary_forwards_selected_timeout() -> None:
    selected_backend = _Backend()
    backend = _InjectedBackend(selected_backend, None, SimpleNamespace())

    assert backend.startup_summary(timeout_seconds=1.8) == {
        "observer": 1,
        "ambient_client": 0,
    }
    assert selected_backend.startup_timeout_seconds == 1.8


def test_ambient_failure_waits_for_selected_lifecycle_boundary() -> None:
    target = "staging.family_copy.files"
    channel = _InjectedChannel(
        _Channel(_phase(1, "refresh.source_discovery")),
        "ambient_client_detected",
        target,
    )
    causality = FailureCausalityAuthority()
    backend = _InjectedBackend(
        _Backend(),
        "ambient_client_detected",
        channel,
        failure_causality=causality,
    )

    assert backend.summary() == {"observer": 1}

    channel._channel.frame = _phase(2, target)
    channel.receive(timeout_seconds=0.1)

    assert backend.summary() == {"observer": 1, "ambient_client": 1}
    assert causality.candidates() == ()


def test_resource_failure_waits_for_selected_lifecycle_boundary() -> None:
    target = "staging.family_copy.files"
    channel = _InjectedChannel(
        _Channel(_phase(1, "refresh.source_discovery")),
        "resource_reader_unavailable",
        target,
    )
    resources = _InjectedResources(
        _Resources(),
        "resource_reader_unavailable",
        channel,
    )

    assert resources.capture() == {"force": False}

    channel._channel.frame = _phase(2, target)
    channel.receive(timeout_seconds=0.1)

    with pytest.raises(ControlFailure) as captured:
        resources.capture()
    assert captured.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE
