from __future__ import annotations

from threading import Event, RLock, Thread

import pytest

from actual_refresh_failure_causality import (
    FailureCausalityAuthority,
    FailureCausalityError,
)
from scale14_actual_refresh_supervisor import ActualRefreshSupervisor
from scale15_terminal_contracts import ControlFailure, ControlFailureCode
from scale25_terminal_settlement import ChildTerminalAuthority


class _LiveProcess:
    def __init__(self) -> None:
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return None

    def send_signal(self, value: int) -> None:
        self.signals.append(value)


def _supervisor(process: _LiveProcess) -> ActualRefreshSupervisor:
    supervisor = ActualRefreshSupervisor.__new__(ActualRefreshSupervisor)
    supervisor._failure_lock = RLock()
    supervisor._process = process
    supervisor._child_terminal = ChildTerminalAuthority(process)
    supervisor._clock_ns = lambda: 1
    supervisor._signal_count = 0
    supervisor._signal_ns = None
    supervisor._signal_reason = None
    supervisor._primary_failure = None
    supervisor._secondary_failures = []
    return supervisor


def test_created_event_failure_precedes_later_ambient_observation() -> None:
    process = _LiveProcess()
    supervisor = _supervisor(process)
    event_created = Event()
    allow_event_observation = Event()

    def report_event() -> None:
        error = ControlFailure(ControlFailureCode.EVENT_TRANSPORT_FAILED)
        supervisor._causality().record_exception(
            error,
            code=ControlFailureCode.EVENT_TRANSPORT_FAILED,
            authority_owner="event_transport",
            lifecycle_boundary="active_event_receive",
            existed_before_child_release=False,
            test_injected=True,
        )
        event_created.set()
        assert allow_event_observation.wait(1.0)
        supervisor._record_async_event_failure(error)

    reporter = Thread(target=report_event)
    reporter.start()
    assert event_created.wait(1.0)
    supervisor._record_and_signal(
        ControlFailure(ControlFailureCode.AMBIENT_CLIENT_DETECTED)
    )
    allow_event_observation.set()
    reporter.join(timeout=1.0)

    assert not reporter.is_alive()
    assert supervisor._primary_failure is ControlFailureCode.EVENT_TRANSPORT_FAILED
    assert supervisor._secondary_failures == [
        ControlFailureCode.AMBIENT_CLIENT_DETECTED
    ]
    assert len(process.signals) == 1


def test_created_threshold_precedes_later_resource_failure() -> None:
    process = _LiveProcess()
    supervisor = _supervisor(process)

    supervisor._signal_once(reason="threshold")
    supervisor._record_and_signal(
        ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
    )

    assert supervisor._primary_failure is None
    assert supervisor._secondary_failures == [
        ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    ]
    assert len(process.signals) == 1


def test_active_ambient_candidate_precedes_later_event_injection() -> None:
    authority = FailureCausalityAuthority(clock_ns=iter((3, 4)).__next__)
    authority.record_code(
        "ambient_client_detected",
        authority_owner="backend_ownership",
        lifecycle_boundary="active_backend_observation",
        existed_before_child_release=False,
    )
    authority.record_code(
        "event_transport_failed",
        authority_owner="event_transport",
        lifecycle_boundary="active_event_receive",
        existed_before_child_release=False,
        test_injected=True,
    )

    assert [item.code for item in authority.freeze().candidates] == [
        "ambient_client_detected",
        "event_transport_failed",
    ]


def test_genuine_resource_failure_precedes_later_threshold() -> None:
    authority = FailureCausalityAuthority(clock_ns=iter((5, 6)).__next__)
    authority.record_code(
        "resource_reader_unavailable",
        authority_owner="resource_sampling",
        lifecycle_boundary="active_resource_read",
        existed_before_child_release=False,
    )
    authority.record_code(
        "threshold_limit_crossed",
        authority_owner="threshold_monitor",
        lifecycle_boundary="staging.family_copy.files",
        existed_before_child_release=False,
        test_injected=True,
    )

    assert [item.code for item in authority.freeze().candidates] == [
        "resource_reader_unavailable",
        "threshold_limit_crossed",
    ]


def test_observation_order_cannot_reorder_causal_creation() -> None:
    authority = FailureCausalityAuthority(clock_ns=iter((11, 12)).__next__)
    event = authority.record_code(
        "event_transport_failed",
        authority_owner="event_transport",
        lifecycle_boundary="active_event_receive",
        existed_before_child_release=False,
        test_injected=True,
    )
    ambient = authority.record_code(
        "ambient_client_detected",
        authority_owner="backend_ownership",
        lifecycle_boundary="active_backend_observation",
        existed_before_child_release=False,
    )

    observed_ambient = authority.observe(ambient)
    observed_event = authority.observe(event)
    snapshot = authority.freeze()

    assert observed_event.causal_sequence < observed_ambient.causal_sequence
    assert observed_event.observation_sequence is not None
    assert observed_ambient.observation_sequence is not None
    assert observed_event.observation_sequence > observed_ambient.observation_sequence
    assert [candidate.code for candidate in snapshot.candidates] == [
        "event_transport_failed",
        "ambient_client_detected",
    ]


def test_same_source_event_is_idempotent_and_conflict_is_rejected() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 17)
    first = authority.record_code(
        "resource_reader_unavailable",
        authority_owner="resource_sampling",
        lifecycle_boundary="active_resource_read",
        existed_before_child_release=False,
        source_event_key="reader-1",
    )
    duplicate = authority.record_code(
        "resource_reader_unavailable",
        authority_owner="resource_sampling",
        lifecycle_boundary="active_resource_read",
        existed_before_child_release=False,
        source_event_key="reader-1",
    )

    assert duplicate is first
    with pytest.raises(FailureCausalityError, match="conflicts"):
        authority.record_code(
            "threshold_limit_crossed",
            authority_owner="threshold_monitor",
            lifecycle_boundary="active_resource_read",
            existed_before_child_release=False,
            source_event_key="reader-1",
        )


def test_same_exception_binding_is_idempotent_and_conflict_is_rejected() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 19)
    error = OSError("bounded")
    first = authority.record_exception(
        error,
        code="event_transport_failed",
        authority_owner="event_transport",
        lifecycle_boundary="active_event_receive",
        existed_before_child_release=False,
    )
    duplicate = authority.record_exception(
        error,
        code="event_transport_failed",
        authority_owner="event_transport",
        lifecycle_boundary="active_event_receive",
        existed_before_child_release=False,
    )

    assert duplicate is first
    with pytest.raises(FailureCausalityError, match="conflicts"):
        authority.record_exception(
            error,
            code="ambient_client_detected",
            authority_owner="backend_ownership",
            lifecycle_boundary="active_backend_observation",
            existed_before_child_release=False,
        )


def test_freeze_is_idempotent_and_rejects_later_mutation() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 23)
    authority.record_code(
        "threshold_limit_crossed",
        authority_owner="threshold_monitor",
        lifecycle_boundary="staging.family_copy.files",
        existed_before_child_release=False,
    )

    first = authority.freeze()
    assert authority.freeze() is first
    with pytest.raises(FailureCausalityError, match="frozen"):
        authority.record_code(
            "terminal_resource_unavailable",
            authority_owner="resource_sampling",
            lifecycle_boundary="terminal_settlement",
            existed_before_child_release=False,
            terminal_secondary=True,
        )


def test_public_projection_exposes_only_closed_order_categories() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 29)
    authority.record_code(
        "ambient_client_detected",
        authority_owner="backend_ownership",
        lifecycle_boundary="startup",
        existed_before_child_release=True,
        source_event_key="private-source-key",
    )

    projection = authority.freeze().public_projection()

    assert projection == {
        "order_status": "causally_ordered",
        "categories": ["ambient_client_detected"],
    }
    assert "private-source-key" not in repr(projection)
    assert "monotonic" not in repr(projection)


def test_unknown_public_category_is_rejected() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 30)

    with pytest.raises(FailureCausalityError, match="category"):
        authority.record_code(
            "private-runtime-detail",
            authority_owner="resource_sampling",
            lifecycle_boundary="startup",
            existed_before_child_release=True,
        )


def test_startup_failure_record_retains_pre_release_authority() -> None:
    authority = FailureCausalityAuthority(clock_ns=lambda: 31)
    candidate = authority.record_code(
        "resource_reader_unavailable",
        authority_owner="resource_sampling",
        lifecycle_boundary="startup",
        existed_before_child_release=True,
    )

    assert candidate.existed_before_child_release is True
    assert candidate.lifecycle_boundary == "startup"


@pytest.mark.parametrize(
    "later_code",
    (
        "backend_telemetry_failed",
        "event_transport_eof",
        "child_exit_unavailable",
        "terminal_resource_unavailable",
        "backend_quiescence_timeout",
    ),
)
def test_later_terminal_candidate_cannot_replace_prior_primary(later_code) -> None:
    authority = FailureCausalityAuthority(clock_ns=iter((37, 38)).__next__)
    primary = authority.record_code(
        "event_transport_failed",
        authority_owner="event_transport",
        lifecycle_boundary="active_event_receive",
        existed_before_child_release=False,
    )
    later = authority.record_code(
        later_code,
        authority_owner="refresh_supervisor",
        lifecycle_boundary="terminal_settlement",
        existed_before_child_release=False,
        terminal_secondary=True,
    )

    assert primary.causal_sequence < later.causal_sequence
    assert authority.freeze().candidates[0].code == "event_transport_failed"


def test_one_hundred_barrier_permutations_use_source_sequence() -> None:
    pairs = (
        ("event_transport_failed", "ambient_client_detected"),
        ("threshold_limit_crossed", "resource_reader_unavailable"),
    )
    for iteration in range(100):
        authority = FailureCausalityAuthority(clock_ns=lambda: 41)
        left, right = pairs[iteration % len(pairs)]
        first, second = (left, right) if iteration % 4 < 2 else (right, left)
        release = {left: Event(), right: Event()}
        recorded = {left: Event(), right: Event()}

        def create(code: str) -> None:
            assert release[code].wait(1.0)
            authority.record_code(
                code,
                authority_owner="barrier_source",
                lifecycle_boundary="active_barrier",
                existed_before_child_release=False,
            )
            recorded[code].set()

        threads = [Thread(target=create, args=(code,)) for code in (left, right)]
        for thread in threads:
            thread.start()
        release[first].set()
        assert recorded[first].wait(1.0)
        release[second].set()
        assert recorded[second].wait(1.0)
        for thread in threads:
            thread.join(timeout=1.0)
            assert not thread.is_alive()

        candidates = authority.freeze().candidates
        assert [candidate.code for candidate in candidates] == [first, second]
        assert [candidate.causal_sequence for candidate in candidates] == [1, 2]
