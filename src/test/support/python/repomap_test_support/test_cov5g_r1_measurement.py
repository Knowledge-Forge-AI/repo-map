"""Exact-connection TEST-COV5G-R1 measurement mechanics."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
import time

import psycopg
from psycopg.conninfo import make_conninfo

from repomap_test_support.test_cov5g_r1_characterization import (
    Condition,
    PROTOCOL,
    RequestObservation,
    RequestOutcome,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)


@dataclass(slots=True)
class _OperationResult:
    started_at: float = 0.0
    terminal_at: float = 0.0
    outcome: str = "not_started"
    error: BaseException | None = None


@dataclass(slots=True)
class _RequestResult:
    started_at: float = 0.0
    terminal_at: float = 0.0
    outcome: RequestOutcome | None = None
    error: BaseException | None = None


class _Observer:
    def register_connection(self, connection: object) -> None:
        assert getattr(connection, "closed", None) is False


class ObservedConnection:
    """A test-only observation seam around one exact connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self.request = _RequestResult()
        self.close_count = 0

    @property
    def broken(self) -> bool:
        return self._connection.broken

    @property
    def closed(self) -> bool:
        return self._connection.closed

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def cancel_safe(self, *, timeout: float) -> None:
        if timeout != ADR_0046_EXPECTATIONS.request_bound_ms / 1_000:
            raise AssertionError("product cancellation trigger policy changed")
        self.request.started_at = time.monotonic()
        try:
            self._connection.cancel_safe(
                timeout=PROTOCOL.observation_ceiling_ms / 1_000
            )
        except psycopg.errors.CancellationTimeout as error:
            self.request.outcome = RequestOutcome.TIMEOUT
            self.request.error = error
            raise
        except Exception as error:
            self.request.outcome = RequestOutcome.TRANSPORT_FAILURE
            self.request.error = error
            raise
        else:
            self.request.outcome = RequestOutcome.SUCCESS
        finally:
            self.request.terminal_at = time.monotonic()

    def close(self) -> None:
        self.close_count += 1
        self._connection.close()


def _request_exact_connection(
    connection: psycopg.Connection,
    result: _RequestResult,
) -> None:
    result.started_at = time.monotonic()
    try:
        connection.cancel_safe(timeout=PROTOCOL.observation_ceiling_ms / 1_000)
    except psycopg.errors.CancellationTimeout as error:
        result.outcome = RequestOutcome.TIMEOUT
        result.error = error
    except Exception as error:
        result.outcome = RequestOutcome.TRANSPORT_FAILURE
        result.error = error
    else:
        result.outcome = RequestOutcome.SUCCESS
    finally:
        result.terminal_at = time.monotonic()


def _run_sql_operation(
    connection: psycopg.Connection,
    started: Event,
    result: _OperationResult,
) -> None:
    result.started_at = time.monotonic()
    started.set()
    try:
        connection.execute(PROTOCOL.operation_sql).fetchone()
    except psycopg.errors.QueryCanceled:
        result.outcome = "query_canceled"
    except BaseException as error:
        result.outcome = "operation_failure"
        result.error = error
    else:
        result.outcome = "ordinary_completion"
    finally:
        result.terminal_at = time.monotonic()


def _wait_for_trigger(operation_started_at: float) -> None:
    trigger_at = operation_started_at + PROTOCOL.product_trigger_ms / 1_000
    remaining = trigger_at - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def _backend_disappeared(
    admin: psycopg.Connection,
    application_name: str,
    *,
    timeout_seconds: float = ADR_0046_EXPECTATIONS.cleanup_attempt_ms / 1_000,
) -> bool:
    """Prove bounded backend cleanup after the exact connection has closed.

    Bounded by the ADR-0046 cleanup-attempt budget, not by the cancellation
    request observation ceiling: backend exit is asynchronous to client close.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        row = admin.execute(
            """
SELECT count(*)
FROM pg_stat_activity
WHERE application_name = %s
""",
            (application_name,),
        ).fetchone()
        if row is not None and row[0] == 0:
            return True
        time.sleep(0.01)
    return False


def run_direct_observation(
    parameters: dict[str, object],
    admin: psycopg.Connection,
    *,
    cohort: str,
    condition: Condition,
    case_number: int,
) -> RequestObservation:
    """Measure one direct exact-connection request and bounded settlement."""

    application_name = f"cov5g_r1_{cohort}_{condition.name.lower()}_{case_number:02d}"
    conn_params = {k: str(v) for k, v in parameters.items() if v is not None}
    conninfo = make_conninfo(**conn_params, application_name=application_name)
    connection = psycopg.connect(conninfo, autocommit=True)
    connection.execute("SET statement_timeout = 0")
    operation_started = Event()
    operation = _OperationResult()
    request = _RequestResult()
    operation_thread = Thread(
        target=_run_sql_operation,
        args=(connection, operation_started, operation),
        name="cov5g-r1-operation-owner",
    )
    request_thread = Thread(
        target=_request_exact_connection,
        args=(connection, request),
        name="cov5g-r1-request-owner",
    )
    operation_thread.start()
    close_count = 0
    try:
        if not operation_started.wait(1.0):
            raise AssertionError("operation owner did not start")
        _wait_for_trigger(operation.started_at)
        request_thread.start()
        request_thread.join(PROTOCOL.observation_ceiling_ms / 1_000)
        censored = request_thread.is_alive()
        if censored:
            request.outcome = RequestOutcome.CENSORED
        request_thread.join(3.5)
        if request_thread.is_alive():
            raise AssertionError("request owner was abandoned")
        operation_thread.join(6.0)
        if operation_thread.is_alive():
            raise AssertionError("operation owner was abandoned")
        request_outcome = RequestOutcome.CENSORED if censored else request.outcome
        if request_outcome is None:
            raise AssertionError("request outcome is unavailable")
        request_elapsed = (
            PROTOCOL.observation_ceiling_ms
            if censored
            else (request.terminal_at - request.started_at) * 1_000
        )
        projection_order = (
            "request_first"
            if request.terminal_at <= operation.terminal_at
            else "operation_first"
        )
    finally:
        request_thread.join(3.5) if request_thread.ident is not None else None
        operation_thread.join(6.0)
        if not connection.closed:
            connection.close()
            close_count += 1
    disappeared = _backend_disappeared(admin, application_name)
    return RequestObservation(
        cohort=cohort,
        condition=condition,
        case_number=case_number,
        request_elapsed_ms=request_elapsed,
        request_outcome=request_outcome,
        operation_elapsed_ms=(operation.terminal_at - operation.started_at) * 1_000,
        operation_outcome=operation.outcome,
        request_settled=request_thread.is_alive() is False,
        operation_settled=operation_thread.is_alive() is False,
        close_eligible=True,
        close_count=close_count,
        backend_disappeared=disappeared,
        cleanup_succeeded=disappeared and close_count == 1,
        projection_order=projection_order,
    )


def run_configured_observation(
    parameters: dict[str, object],
    admin: psycopg.Connection,
    *,
    cohort: str,
    case_number: int,
) -> RequestObservation:
    """Measure one configured session through a test-only request seam."""

    application_name = f"cov5g_r1_{cohort}_configured_{case_number:02d}"
    conn_params = {k: str(v) for k, v in parameters.items() if v is not None}
    conninfo = make_conninfo(**conn_params, application_name=application_name)
    exact = psycopg.connect(conninfo, autocommit=True)
    exact.execute("SET statement_timeout = 0")
    connection = ObservedConnection(exact)
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    operation = _OperationResult()
    construction_at: list[float] = []
    original_execution_timeout = session._execution_timeout

    def observe_execution_timeout(
        category: str,
        cause: Exception | None = None,
    ) -> BackendMonitorError:
        with session._condition:
            construction_at.append(time.monotonic())
            return original_execution_timeout(category, cause)

    setattr(session, "_execution_timeout", observe_execution_timeout)

    def operation_call(_observer, exact_connection):
        operation.started_at = time.monotonic()
        try:
            return exact_connection.execute(PROTOCOL.operation_sql).fetchone()
        finally:
            operation.terminal_at = time.monotonic()

    failure: BackendMonitorError | None = None
    try:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation_call,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
        except BackendMonitorError as error:
            failure = error
        if failure is None:
            raise AssertionError("configured operation did not time out")
        if connection.request.outcome is None:
            raise AssertionError("configured request was not observed")
        snapshot = session.snapshot()
        if failure.observer_boundary is None:
            raise AssertionError("configured failure boundary was not set")
        operation.outcome = failure.observer_boundary.value
        request_outcome = connection.request.outcome
        request_elapsed = (
            connection.request.terminal_at - connection.request.started_at
        ) * 1_000
        projection_order = (
            "request_first"
            if construction_at and connection.request.terminal_at <= construction_at[0]
            else "operation_first"
        )
        assert snapshot.cancellation.request_in_flight is False
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.close_eligible is True
    finally:
        session.close(timeout_seconds=6.0)
    disappeared = _backend_disappeared(admin, application_name)
    return RequestObservation(
        cohort=cohort,
        condition=Condition.CONFIGURED_SESSION,
        case_number=case_number,
        request_elapsed_ms=request_elapsed,
        request_outcome=request_outcome,
        operation_elapsed_ms=(operation.terminal_at - operation.started_at) * 1_000,
        operation_outcome=operation.outcome,
        request_settled=True,
        operation_settled=True,
        close_eligible=True,
        close_count=connection.close_count,
        backend_disappeared=disappeared,
        cleanup_succeeded=disappeared and connection.close_count == 1,
        projection_order=projection_order,
    )
