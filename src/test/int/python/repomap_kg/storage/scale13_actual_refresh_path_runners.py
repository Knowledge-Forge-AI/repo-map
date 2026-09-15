from __future__ import annotations
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event, Lock, Thread
import time
import psycopg
from psycopg.conninfo import make_conninfo
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_telemetry import (
    TelemetryEventKind,
    read_telemetry_event,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
)
from scale13_actual_refresh_supervisor import (
    send_direct_sigint_once,
    start_actual_refresh_child,
)
from scale12_resource_sampling import (
    Scale12ResourceSampler,
    host_free_bytes,
    read_cluster_wal_bytes,
    read_container_growth_bytes,
    read_container_rss_upper_bound,
    read_database_size_bytes,
    read_database_temporary_bytes,
    read_process_rss_bytes,
)

from src.test.int.python.repomap_kg.storage.scale13_actual_refresh_path_fixtures import (
    _actual_refresh_argv,
)

def _run_uninstrumented_refresh(home: Path, postgres) -> int:
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[5]
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(source_root / "main" / "python"), str(source_root / "test" / "support" / "python"))
    )
    completed = subprocess.run(
        _actual_refresh_argv(home, postgres, None),
        cwd=Path(__file__).resolve().parents[6],
        env=environment,
        check=False,
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30.0,
    )
    return completed.returncode


def _run_instrumented_refresh(
    home: Path,
    postgres,
    *,
    cancel_code: str | None = None,
):
    supervisor_socket, child_socket = socket.socketpair()
    control_supervisor_socket = None
    control_child_socket = None
    if cancel_code is not None:
        control_supervisor_socket, control_child_socket = socket.socketpair()
    channel = StagingEventChannel(supervisor_socket)
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[5]
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(source_root / "main" / "python"), str(source_root / "test" / "support" / "python"))
    )
    process = start_actual_refresh_child(
        _actual_refresh_argv(
            home,
            postgres,
            child_socket.fileno(),
            test_control_code=cancel_code,
            control_ready_fd=(
                control_child_socket.fileno()
                if control_child_socket is not None
                else None
            ),
        ),
        inherited_fds=(
            child_socket.fileno(),
            *(
                (control_child_socket.fileno(),)
                if control_child_socket is not None
                else ()
            ),
        ),
        cwd=Path(__file__).resolve().parents[6],
        environment=environment,
        stderr=subprocess.PIPE,
    )
    child_socket.close()
    if control_child_socket is not None:
        control_child_socket.close()
    stderr_chunks: list[bytes] = []
    _max_stderr_bytes = 65536

    def _drain_child_stderr() -> None:
        err = process.stderr
        if err is not None:
            total_read = 0
            try:
                while True:
                    chunk = err.read(4096)
                    if not chunk:
                        break
                    if total_read < _max_stderr_bytes:
                        stderr_chunks.append(chunk[: _max_stderr_bytes - total_read])
                        total_read += len(chunk)
            except (OSError, ValueError):
                pass

    stderr_drain_thread = Thread(target=_drain_child_stderr, daemon=True)
    stderr_drain_thread.start()
    frames = []
    signal_count = 0
    deadline = time.monotonic() + 30.0
    exited_at: float | None = None
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None and exited_at is None:
                exited_at = time.monotonic()
            try:
                frame = channel.receive(timeout_seconds=0.1)
                frames.append(frame)
                code = frame.payload.get("phase_code") or frame.payload.get(
                    "operation_code"
                )
                if (
                    cancel_code is not None
                    and signal_count == 0
                    and frame.payload.get("event_category") == "started"
                    and code == cancel_code
                ):
                    if control_supervisor_socket is None:
                        raise AssertionError("test control readiness channel is missing")
                    control_supervisor_socket.settimeout(5.0)
                    try:
                        readiness = control_supervisor_socket.recv(1)
                    except socket.timeout as error:
                        raise AssertionError(
                            "test child did not enter the post-ack blocker"
                        ) from error
                    assert readiness == b"\x01"
                    signal_count = send_direct_sigint_once(process, signal_count)
            except TimeoutError:
                if exited_at is not None and time.monotonic() - exited_at >= 1.0:
                    break
                continue
            except EOFError:
                break
            except StagingEventTransportError:
                if process.poll() is not None:
                    break
                raise
        return_code = process.wait(timeout=5.0)
        stderr_drain_thread.join(timeout=5.0)
        child_stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if return_code != 0 and child_stderr:
            sys.stderr.write(f"[scale13_actual_refresh_child stderr]:\n{child_stderr}\n")
    finally:
        channel.close()
        if control_supervisor_socket is not None:
            control_supervisor_socket.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        if stderr_drain_thread.is_alive():
            stderr_drain_thread.join(timeout=1.0)
        if process.stderr and not process.stderr.closed:
            process.stderr.close()
    return return_code, frames, signal_count


def _run_owned_resource_refresh(
    home: Path,
    postgres,
    *,
    runtime: str,
    container_name: str,
):
    supervisor_socket, child_socket = socket.socketpair()
    backend_read_fd, backend_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    channel = StagingEventChannel(supervisor_socket)
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    lock = Lock()
    backend_summaries: list[dict[str, int]] = []
    backend_errors: list[BaseException] = []
    backend_done = Event()
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[5]
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(source_root / "main" / "python"), str(source_root / "test" / "support" / "python"))
    )
    with psycopg.connect(make_conninfo(**params), autocommit=True) as observer_connection:
        observer = BackendOwnershipObserver()
        observer.register_connection(observer_connection)
        backend_summaries.append(observer.public_summary(observer_connection))

        def consume_backend_events() -> None:
            try:
                with os.fdopen(backend_read_fd, "rb", closefd=False) as events:
                    while (event := read_telemetry_event(events)) is not None:
                        with lock:
                            observer.consume_pipe_event(
                                event,
                                observer_connection,
                                ack_write_fd,
                            )
                            if event.event in {
                                TelemetryEventKind.CONNECTION_READY,
                                TelemetryEventKind.CONNECTION_CLOSED,
                            }:
                                backend_summaries.append(
                                    observer.public_summary(observer_connection)
                                )
            except BaseException as error:
                backend_errors.append(error)
            finally:
                backend_done.set()

        backend_thread = Thread(target=consume_backend_events)
        backend_thread.start()
        process = start_actual_refresh_child(
            _actual_refresh_argv(
                home,
                postgres,
                child_socket.fileno(),
                test_control_code="refresh.source_discovery",
                backend_event_fd=backend_write_fd,
                backend_ack_fd=ack_read_fd,
            ),
            inherited_fds=(child_socket.fileno(), backend_write_fd, ack_read_fd),
            cwd=Path(__file__).resolve().parents[6],
            environment=environment,
            stderr=subprocess.PIPE,
        )
        child_socket.close()
        os.close(backend_write_fd)
        os.close(ack_read_fd)
        stderr_chunks: list[bytes] = []
        _max_stderr_bytes = 65536

        def _drain_child_stderr() -> None:
            err = process.stderr
            if err is not None:
                total_read = 0
                try:
                    while True:
                        chunk = err.read(4096)
                        if not chunk:
                            break
                        if total_read < _max_stderr_bytes:
                            stderr_chunks.append(chunk[: _max_stderr_bytes - total_read])
                            total_read += len(chunk)
                except (OSError, ValueError):
                    pass

        stderr_drain_thread = Thread(target=_drain_child_stderr, daemon=True)
        stderr_drain_thread.start()

        def locked(reader):
            with lock:
                return reader(observer_connection)

        def runtime_growth() -> int | None:
            value = read_container_growth_bytes(runtime, container_name)
            return value if value is not None else locked(read_database_size_bytes)

        sampler = Scale12ResourceSampler(
            {
                "client_peak_rss_bytes": lambda: read_process_rss_bytes(
                    process.pid
                ),
                "postgresql_container_rss_upper_bound": lambda: (
                    read_container_rss_upper_bound(runtime, container_name)
                ),
                "temporary_byte_upper_bound_delta": lambda: locked(
                    read_database_temporary_bytes
                ),
                "wal_upper_bound_delta": lambda: locked(read_cluster_wal_bytes),
                "disposable_runtime_growth_bytes": runtime_growth,
                "host_free_bytes": lambda: host_free_bytes(Path.cwd()),
            },
            cadence_ns=250_000_000,
        )
        samples = []
        resource_errors: list[BaseException] = []

        def collect_resource_samples() -> None:
            try:
                while process.poll() is None:
                    sample = sampler.capture()
                    if sample is not None:
                        samples.append(sample)
                    time.sleep(0.05)
            except BaseException as error:
                resource_errors.append(error)

        sampling_thread = Thread(target=collect_resource_samples)
        sampling_thread.start()
        frames = []
        try:
            while process.poll() is None:
                try:
                    frames.append(channel.receive(timeout_seconds=0.1))
                except TimeoutError:
                    pass
                except EOFError:
                    break
            return_code = process.wait(timeout=5.0)
            stderr_drain_thread.join(timeout=5.0)
            child_stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            if return_code != 0 and child_stderr:
                sys.stderr.write(f"[scale13_owned_refresh_child stderr]:\n{child_stderr}\n")
            assert backend_done.wait(timeout=5.0)
            backend_thread.join(timeout=5.0)
            sampling_thread.join(timeout=10.0)
            assert not sampling_thread.is_alive()
        finally:
            channel.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5.0)
            if stderr_drain_thread.is_alive():
                stderr_drain_thread.join(timeout=1.0)
            if process.stderr and not process.stderr.closed:
                process.stderr.close()
            for fd in (backend_read_fd, ack_write_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
    return (
        return_code,
        frames,
        samples,
        backend_summaries,
        [*backend_errors, *resource_errors],
    )
