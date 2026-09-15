from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

import psycopg
import pytest

from repomap_test_support.test_cov5c_qualification import build_evidence
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverCancellationRequestOutcome,
    ObserverCancellationState,
    ObserverDeadlinePolicy,
    ObserverTimeoutMechanism,
)
from scale28_preparation_receipts import (
    ParentObservedTerminalFacts,
    validate_parent_terminal_facts,
)


_BOUNDARIES = (
    ObserverFailureBoundary.STARTUP_SUMMARY,
    ObserverFailureBoundary.ACTIVE_SUMMARY,
    ObserverFailureBoundary.EVENT_APPLY,
    ObserverFailureBoundary.RESOURCE_READ,
    ObserverFailureBoundary.TERMINAL_WAIT,
)
_SYNTHETIC_DEADLINE_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.05,
)


@dataclass(frozen=True, slots=True)
class _CancellationScenario:
    trigger: str
    cancellation: str
    completion: str

    @property
    def case_id(self) -> str:
        return f"{self.trigger}-{self.cancellation}-{self.completion}"


_SCENARIO_MODES = (
    _CancellationScenario("timer", "success", "natural_return"),
    _CancellationScenario("timer", "success", "connector_error"),
    _CancellationScenario("timer", "timeout", "natural_return"),
    _CancellationScenario("timer", "timeout", "connector_error"),
    _CancellationScenario("timer", "transport_failure", "natural_return"),
    _CancellationScenario("timer", "transport_failure", "connector_error"),
    _CancellationScenario("local_close", "success", "natural_return"),
    _CancellationScenario("local_close", "timeout", "natural_return"),
    _CancellationScenario("local_close", "transport_failure", "connector_error"),
    _CancellationScenario("server", "statement_timeout", "query_canceled"),
)

_CASES = tuple(
    pytest.param(
        boundary,
        scenario,
        id=f"{boundary.value}-{scenario.case_id}",
    )
    for boundary in _BOUNDARIES
    for scenario in _SCENARIO_MODES
)
_TERMINAL_CASES = (
    pytest.param({}, True, id="normal-zero-exit"),
    pytest.param({"exit_code": 1}, False, id="nonzero-exit"),
    pytest.param({"signal": "SIGTERM"}, False, id="signal-exit"),
    pytest.param(
        {"process_tree_settled": False},
        False,
        id="live-descendant-process-tree",
    ),
    pytest.param({"active_observers": 0}, False, id="missing-parent-observer"),
    pytest.param({"active_observers": 2}, False, id="extra-parent-observer"),
    pytest.param({"descendants": 1}, False, id="live-descendant"),
    pytest.param({"worker_connections": 1}, False, id="connection-leak"),
    pytest.param({"readers": 1}, False, id="reader-leak"),
    pytest.param({"threads": 1}, False, id="thread-leak"),
    pytest.param(
        {"descriptors_and_channels": 1},
        False,
        id="result-channel-leak",
    ),
    pytest.param(
        {"exit_code": 2, "process_tree_settled": False},
        False,
        id="nonzero-unsettled-tree",
    ),
)


class _StatementTimeoutCanceled(psycopg.errors.QueryCanceled):
    @property
    def diag(self):
        return type(
            "_Diagnostic",
            (),
            {"message_primary": "canceling statement due to statement timeout"},
        )()


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _Connection:
    def __init__(
        self,
        scenario: _CancellationScenario,
        release: Event,
    ) -> None:
        self.broken = False
        self.closed = False
        self.close_count = 0
        self.close_while_active = False
        self.cancel_attempted = Event()
        self._scenario = scenario
        self._release = release
        self.session: BackendObserverSession | None = None

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_attempted.set()
        if self._scenario.cancellation == "success":
            self._release.set()
            return
        if self._scenario.cancellation == "timeout":
            raise psycopg.errors.CancellationTimeout("bounded cancellation timeout")
        raise OSError("bounded cancellation transport failure")

    def close(self) -> None:
        if self.session is not None:
            self.close_while_active |= self.session.snapshot().operation_in_flight
        self.close_count += 1
        self.closed = True


def _active_session(connection: _Connection) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_SYNTHETIC_DEADLINE_POLICY,
    )
    connection.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def _operation(
    scenario: _CancellationScenario,
    started: Event,
    release: Event,
):
    def run(_observer: object, _connection: object) -> object:
        started.set()
        if scenario.trigger == "server":
            raise _StatementTimeoutCanceled()
        release.wait()
        if scenario.completion == "connector_error":
            raise OSError("observer connector operation failed")
        return "settled"

    return run


@pytest.mark.parametrize(("boundary", "scenario"), _CASES)
def test_fifty_distinct_cancellation_close_and_settlement_cases(
    boundary: ObserverFailureBoundary,
    scenario: _CancellationScenario,
) -> None:
    release = Event()
    started = Event()
    connection = _Connection(scenario, release)
    session = _active_session(connection)
    operation_failures: list[BaseException] = []
    close_failures: list[BaseException] = []

    def run_operation() -> None:
        try:
            session.run(
                boundary,
                _operation(scenario, started, release),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.2,
            )
        except BaseException as error:
            operation_failures.append(error)

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    close_thread = None
    try:
        assert started.wait(1.0)
        if scenario.trigger == "local_close":

            def close_session() -> None:
                try:
                    session.close(timeout_seconds=0.5)
                except BaseException as error:
                    close_failures.append(error)

            close_thread = Thread(target=close_session)
            close_thread.start()
        if scenario.trigger != "server":
            assert connection.cancel_attempted.wait(1.0)
            if scenario.cancellation != "success":
                assert session.snapshot().operation_in_flight is True
                assert connection.closed is False
                release.set()
        operation_thread.join(1.0)
        assert operation_thread.is_alive() is False
        if close_thread is not None:
            close_thread.join(1.0)
            assert close_thread.is_alive() is False
        else:
            session.close()

        assert close_failures == []
        assert len(operation_failures) == 1
        failure = operation_failures[0]
        assert isinstance(failure, BackendMonitorError)
        snapshot = session.snapshot()
        assert failure.observer_timeout_mechanism is not None
        if scenario.trigger == "server":
            assert failure.observer_timeout_mechanism.value == (
                "server_statement_timeout"
            )
            assert snapshot.cancellation.cancellation_requested is False
        else:
            assert failure.observer_timeout_mechanism.value == (
                "client_cancel_fallback"
            )
            assert snapshot.cancellation.operation_timeout_created is True
            assert snapshot.cancellation.cancellation_requested is True
            expected_outcome = {
                "success": "request_succeeded",
                "timeout": "request_timed_out",
                "transport_failure": "request_failed",
            }[scenario.cancellation]
            assert snapshot.cancellation.request_outcome.value == expected_outcome
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.close_eligible is True
        assert connection.close_while_active is False
        assert connection.close_count == 1
        assert connection.closed is True
    finally:
        release.set()
        operation_thread.join(1.0)
        if close_thread is not None:
            close_thread.join(1.0)
        if not connection.closed:
            session.close()


def test_settlement_timeout_never_closes_and_later_close_is_idempotent() -> None:
    scenario = _CancellationScenario(
        "local_close",
        "timeout",
        "natural_return",
    )
    release = Event()
    started = Event()
    connection = _Connection(scenario, release)
    session = _active_session(connection)
    operation_failures: list[BaseException] = []

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                _operation(scenario, started, release),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=1.0,
            )
        except BaseException as error:
            operation_failures.append(error)

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    try:
        assert started.wait(1.0)
        with pytest.raises(BackendMonitorError) as caught:
            session.close(timeout_seconds=0.1)
        assert caught.value.observer_boundary is (
            ObserverFailureBoundary.SETTLEMENT_TIMEOUT
        )
        snapshot = session.snapshot()
        assert snapshot.operation_in_flight is True
        assert snapshot.cancellation.operation_settled is False
        assert snapshot.cancellation.settlement_limitation is True
        assert snapshot.cancellation.close_eligible is False
        assert connection.close_count == 0

        release.set()
        operation_thread.join(1.0)
        assert operation_thread.is_alive() is False
        assert len(operation_failures) == 1
        session.close()
        session.close()
        assert connection.close_count == 1
        assert connection.close_while_active is False
    finally:
        release.set()
        operation_thread.join(1.0)
        if not connection.closed:
            session.close()


def test_cancellation_state_accepts_exact_duplicate_and_rejects_conflict() -> None:
    state = ObserverCancellationState().begin_operation().request(
        ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK
    )
    state = state.record_request_outcome(
        ObserverCancellationRequestOutcome.REQUEST_TIMED_OUT
    )

    assert (
        state.record_request_outcome(
            ObserverCancellationRequestOutcome.REQUEST_TIMED_OUT
        )
        is state
    )
    with pytest.raises(ValueError, match="conflicts"):
        state.record_request_outcome(
            ObserverCancellationRequestOutcome.REQUEST_FAILED
        )


@pytest.mark.parametrize(("changes", "accepted"), _TERMINAL_CASES)
def test_twelve_distinct_parent_observed_terminal_variants(
    changes: dict[str, object],
    accepted: bool,
) -> None:
    def _int(key: str, default: int) -> int:
        val = changes.get(key, default)
        assert isinstance(val, int)
        return val

    signal = changes.get("signal", None)
    assert signal is None or isinstance(signal, str)
    settled = changes.get("process_tree_settled", True)
    assert isinstance(settled, bool)
    facts = ParentObservedTerminalFacts(
        exit_code=_int("exit_code", 0),
        signal=signal,
        process_tree_settled=settled,
        active_observers=_int("active_observers", 1),
        descendants=_int("descendants", 0),
        worker_connections=_int("worker_connections", 0),
        readers=_int("readers", 0),
        threads=_int("threads", 0),
        descriptors_and_channels=_int("descriptors_and_channels", 0),
    )
    receipt = build_evidence().receipt

    if accepted:
        validate_parent_terminal_facts(receipt, facts)
    else:
        with pytest.raises(ValueError, match="terminal facts are invalid"):
            validate_parent_terminal_facts(receipt, facts)
