"""Public-safe local PostgreSQL startup fault harness."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import get_context
from queue import Empty
import socket
from typing import TYPE_CHECKING, Literal

import psycopg
import psycopg.conninfo

if TYPE_CHECKING:
    from multiprocessing.queues import Queue
    from scale28_observer_deadlines import ObserverConnectionSettings


_RESULT_GRACE_SECONDS = 0.5
_CLEANUP_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class BootstrapProbeResult:
    """Bounded result and cleanup facts for one startup fault."""

    outcome: str
    boundary: str | None
    process_alive_after_deadline: bool
    process_clean: bool
    accepted_socket_clean: bool
    listener_clean: bool


class _RegistrationObserver:
    def register_connection(self, _connection: object) -> None:
        raise AssertionError("startup fault unexpectedly reached registration")


def _open_connection(port: int, result: Queue[tuple[str, str | None]]) -> None:
    from scale28_backend_observer_session import (
        BackendMonitorError,
        BackendObserverSession,
    )

    base_parameters = {
        "host": "127.0.0.1",
        "port": port,
        "dbname": "observer",
        "user": "observer",
        "sslmode": "disable",
    }

    def connect(settings: ObserverConnectionSettings | None = None) -> object:
        parameters = (
            base_parameters
            if settings is None
            else settings.apply(base_parameters)
        )
        connection_parameters: dict[str, str | int | None] = {}
        for name, value in parameters.items():
            if value is not None and not isinstance(value, (str, int)):
                raise TypeError("connection parameter has an unsupported value type")
            connection_parameters[name] = value
        conninfo = psycopg.conninfo.make_conninfo("", **connection_parameters)
        return psycopg.connect(conninfo, autocommit=True)

    session = BackendObserverSession(
        observer_factory=_RegistrationObserver,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: False,
    )
    try:
        session.open(1)
    except BackendMonitorError as error:
        boundary = getattr(error.observer_boundary, "value", None)
        result.put(("error", boundary))
    except BaseException as error:
        result.put(("unexpected", type(error).__name__))
    else:
        result.put(("opened", None))


def run_startup_fault_probe(
    mode: Literal["stall", "close"],
    *,
    deadline_seconds: float = 3.0,
) -> BootstrapProbeResult:
    """Run one actual-Psycopg loopback startup fault in a cleanup process."""

    if mode not in {"stall", "close"}:
        raise ValueError("unsupported PostgreSQL startup fault")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(deadline_seconds)
    context = get_context("spawn")
    result: Queue[tuple[str, str | None]] = context.Queue()
    process = context.Process(
        target=_open_connection,
        args=(listener.getsockname()[1], result),
        name=f"postgres-startup-{mode}",
    )
    accepted = None
    outcome = "no_result"
    boundary = None
    alive_after_deadline = False
    try:
        process.start()
        accepted, _address = listener.accept()
        if mode == "close":
            accepted.close()
            accepted = None
        process.join(timeout=deadline_seconds)
        alive_after_deadline = process.is_alive()
        if alive_after_deadline:
            outcome = "deadline_exceeded"
        else:
            try:
                outcome, boundary = result.get(timeout=_RESULT_GRACE_SECONDS)
            except Empty:
                outcome = "no_result"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=_CLEANUP_GRACE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=_CLEANUP_GRACE_SECONDS)
        if accepted is not None:
            accepted.close()
        accepted_socket_clean = accepted is None or accepted.fileno() == -1
        listener.close()
        listener_clean = listener.fileno() == -1
        result.close()
        result.join_thread()
    return BootstrapProbeResult(
        outcome=outcome,
        boundary=boundary,
        process_alive_after_deadline=alive_after_deadline,
        process_clean=not process.is_alive(),
        accepted_socket_clean=accepted_socket_clean,
        listener_clean=listener_clean,
    )


__all__ = ["BootstrapProbeResult", "run_startup_fault_probe"]
