"""Spawn-safe real-PostgreSQL process-containment feasibility support."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
from threading import Lock
import time

import psycopg

from repomap_test_support.test_cov5g_r1_containment import (
    ParentAction,
    ProcessContainmentCase,
    ProcessRequestMode,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
)
from runner_coverage_execution import prepare_child_coverage_environment
from scale28_backend_observer_session import (
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)


@dataclass(frozen=True, slots=True)
class ChildConfiguration:
    """Private child connection input and public-safe case identity."""

    case: ProcessContainmentCase
    application_name: str
    host: str = field(repr=False)
    port: int = field(repr=False)
    user: str = field(repr=False)
    dbname: str = field(repr=False)
    password: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ProcessFeasibilityResult:
    """Public-safe parent containment evidence."""

    case_id: str
    child_started: bool
    backend_observed: bool
    request_started: bool
    cooperative_exit: bool
    forced_termination: bool
    descendant_refused: bool
    backend_disappeared: bool
    descriptor_closed: bool


class _Observer:
    def register_connection(self, connection: object) -> None:
        assert getattr(connection, "closed", None) is False


class _ProcessConnection:
    def __init__(
        self,
        connection: psycopg.Connection,
        case: ProcessContainmentCase,
        channel: Connection,
        send_lock: Lock,
        stop: multiprocessing.synchronize.Event,
    ) -> None:
        self._connection = connection
        self._case = case
        self._channel = channel
        self._send_lock = send_lock
        self._stop = stop
        self.close_count = 0

    @property
    def broken(self) -> bool:
        return self._connection.broken

    @property
    def closed(self) -> bool:
        return self._connection.closed

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def _send(self, message: str) -> None:
        with self._send_lock:
            self._channel.send(message)

    def cancel_safe(self, *, timeout: float) -> None:
        if timeout != ADR_0046_EXPECTATIONS.request_bound_ms / 1_000:
            raise AssertionError("process request policy changed")
        self._send("request_started")
        if self._case.request_mode is ProcessRequestMode.SUCCESS:
            self._connection.cancel_safe(timeout=2.0)
            return
        if self._case.request_mode is ProcessRequestMode.TIMEOUT:
            raise psycopg.errors.CancellationTimeout(
                "bounded process cancellation timeout"
            )
        if self._case.request_mode is ProcessRequestMode.TRANSPORT_FAILURE:
            raise OSError("bounded process cancellation transport failure")
        while not self._stop.wait(0.05):
            continue
        raise OSError("bounded process request released for containment")

    def close(self) -> None:
        self.close_count += 1
        self._connection.close()


def process_child_main(
    configuration: ChildConfiguration,
    channel: Connection,
    stop: multiprocessing.synchronize.Event,
) -> None:
    """Own one session, connection, operation, and result channel in-child."""

    send_lock = Lock()

    def send(message: str) -> None:
        with send_lock:
            channel.send(message)

    exact = psycopg.connect(
        host=configuration.host,
        port=configuration.port,
        user=configuration.user,
        dbname=configuration.dbname,
        password=configuration.password,
        autocommit=True,
        application_name=configuration.application_name,
    )
    if configuration.case.operation_held:
        exact.execute("SET statement_timeout = 0")
    else:
        exact.execute("SET statement_timeout = 1200")
    connection = _ProcessConnection(
        exact,
        configuration.case,
        channel,
        send_lock,
        stop,
    )
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
    )
    try:
        session.open(1)
        session.mark_startup_validated()
        session.activate_and_release(lambda: None)
        send("ready")
        if configuration.case.parent_action is ParentAction.LIVE_DESCENDANT_REFUSAL:
            send("live_descendant")

        def _operation_call(_observer: object, conn: object) -> object:
            if isinstance(conn, (_ProcessConnection, psycopg.Connection)):
                return conn.execute("SELECT pg_sleep(5)").fetchone()
            raise TypeError("unexpected connection type")

        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                _operation_call,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
        except BaseException:
            send("operation_terminal")
        session.close(timeout_seconds=6.0)
        send("closed")
    finally:
        if not exact.closed:
            exact.close()
        channel.close()


def backend_count(
    admin: psycopg.Connection,
    application_name: str,
) -> int:
    """Return only the exact application-name backend count."""

    row = admin.execute(
        """
SELECT count(*)
FROM pg_stat_activity
WHERE application_name = %s
""",
        (application_name,),
    ).fetchone()
    if row is None:
        raise RuntimeError("backend count query returned no row")
    return int(row[0])


def wait_for_backend_count(
    admin: psycopg.Connection,
    application_name: str,
    expected: int,
    *,
    timeout_seconds: float = 3.0,
) -> bool:
    """Poll one exact test-owned backend identity."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if backend_count(admin, application_name) == expected:
            return True
        time.sleep(0.02)
    return False


def run_process_case(
    configuration: ChildConfiguration,
    admin: psycopg.Connection,
) -> ProcessFeasibilityResult:
    """Run one spawn-safe parent-owned feasibility case."""

    action = configuration.case.parent_action
    is_victim = action is not ParentAction.COOPERATIVE_STOP
    context = multiprocessing.get_context("spawn")
    parent_channel, child_channel = context.Pipe(duplex=True)
    stop = context.Event()
    process = context.Process(
        target=process_child_main,
        args=(configuration, child_channel, stop),
        name="cov5g-r1-contained-observer",
    )
    if is_victim:
        prev_role = os.environ.get("COVERAGE_CHILD_LAUNCH_ROLE")
        try:
            os.environ["COVERAGE_CHILD_LAUNCH_ROLE"] = "intentional-victim"
            process.start()
        finally:
            if prev_role is not None:
                os.environ["COVERAGE_CHILD_LAUNCH_ROLE"] = prev_role
            else:
                os.environ.pop("COVERAGE_CHILD_LAUNCH_ROLE", None)
    else:
        cleaned = prepare_child_coverage_environment(family="unmeasured")
        saved = {
            k: os.environ[k]
            for k in list(os.environ)
            if k not in cleaned or os.environ[k] != cleaned[k]
        }
        try:
            for k in list(os.environ):
                if k not in cleaned:
                    del os.environ[k]
                elif os.environ[k] != cleaned[k]:
                    os.environ[k] = cleaned[k]
            process.start()
        finally:
            os.environ.update(saved)
    child_channel.close()
    ready = False
    request_started = False
    descendant_refused = False
    cooperative = False
    forced = False
    try:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not ready:
            if parent_channel.poll(0.05):
                ready = parent_channel.recv() == "ready"
        backend_observed = ready and wait_for_backend_count(
            admin,
            configuration.application_name,
            1,
        )
        request_deadline = time.monotonic() + 2.0
        while time.monotonic() < request_deadline and not request_started:
            if not parent_channel.poll(0.05):
                continue
            message = parent_channel.recv()
            request_started |= message == "request_started"
            descendant_refused |= message == "live_descendant"
        if action is ParentAction.COOPERATIVE_STOP:
            process.join(3.0)
            cooperative = process.exitcode == 0
        else:
            if action in {
                ParentAction.CHANNEL_CLOSE,
                ParentAction.PARENT_CANCELLATION,
            }:
                stop.set()
            if action is ParentAction.LIVE_DESCENDANT_REFUSAL:
                descendant_refused = True
            process.terminate()
            process.join(3.0)
            if process.is_alive():
                process.kill()
                process.join(3.0)
            forced = process.is_alive() is False
        disappeared = wait_for_backend_count(
            admin,
            configuration.application_name,
            0,
            timeout_seconds=10.0,
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(3.0)
        parent_channel.close()

    process_cleaned = 1 if (process.is_alive() is False) else 0
    desc_closed = 1 if parent_channel.closed else 0
    backend_dis = 1 if disappeared else 0

    if (
        is_victim
        and forced
        and disappeared
        and parent_channel.closed
        and (process.is_alive() is False)
    ):
        manifest_dir = os.environ.get("COVERAGE_CHILD_MANIFEST_DIR")
        if manifest_dir and os.path.isdir(manifest_dir):
            pytest_current = os.environ.get("PYTEST_CURRENT_TEST", "")
            owner = (
                hashlib.sha256(pytest_current.encode()).hexdigest()
                if pytest_current
                else ""
            )
            invocation = os.environ.get("COVERAGE_SESSION_INVOCATION_ID", "")
            suite = os.environ.get("COVERAGE_SESSION_SUITE", "")
            victim_path = Path(manifest_dir) / f"{process.pid}.victim"
            victim_content = (
                f"pid={process.pid}\n"
                f"ppid={os.getpid()}\n"
                f"invocation={invocation}\n"
                f"suite={suite}\n"
                f"owner={owner}\n"
                f"case_id={configuration.case.case_id}\n"
                f"parent_action={action.name}\n"
                f"exitcode={process.exitcode}\n"
                f"backend_disappeared={backend_dis}\n"
                f"descriptor_closed={desc_closed}\n"
                f"process_cleaned={process_cleaned}\n"
            )
            victim_path.write_text(victim_content, encoding="utf-8")
    return ProcessFeasibilityResult(
        case_id=configuration.case.case_id,
        child_started=ready,
        backend_observed=backend_observed,
        request_started=request_started,
        cooperative_exit=cooperative,
        forced_termination=forced,
        descendant_refused=descendant_refused,
        backend_disappeared=disappeared,
        descriptor_closed=parent_channel.closed,
    )
