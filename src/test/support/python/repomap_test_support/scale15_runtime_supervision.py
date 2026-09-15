"""Public-safe SCALE15 supervised-refresh orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
from typing import BinaryIO, Protocol, TypeAlias, TypedDict

import psycopg
import psycopg.conninfo

from actual_refresh_failure_causality import FailureCausalityAuthority
from actual_refresh_startup import ActualRefreshStartup
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_telemetry import read_telemetry_event
from repomap_kg.storage.staging_event_transport import StagingEventChannel
from scale12_resource_sampling import (
    Scale12ResourceSampler,
    read_cluster_wal_bytes,
    read_container_rss_upper_bound,
    read_database_temporary_bytes,
    read_process_rss_bytes,
)
from scale14_actual_refresh_supervisor import ActualRefreshSupervisor, ProtectedLaunchLimits
from scale14_backend_monitor import BackendOwnershipMonitor
from scale14_backend_monitor_events import EventReaderProtocol
from scale14_postgres_storage import PostgresStorageAuthority
from scale14_resource_sampling import PeakRetainingReader, Scale14ResourceSampler
from scale15_async_storage import AsyncPostgresStorageAuthority, AsyncStorageStatistics
from scale15_actual_path_readback import read_terminal_backend_summary
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
    TerminalControlResult,
    TerminalReadback,
)
from scale16_actual_path_readback import read_scale16_terminal_state
from scale25_terminal_settlement import ChildTerminalAuthority
from scale28_observer_deadlines import ObserverConnectionSettings
from scale28_preparation_authority import HybridPreparationAuthority
from scale28_preparation_policy import DEFAULT_PREPARATION_DEADLINE_POLICY
from scale28_preparation_resources import PreparationResourceSpecification
from scale28_preparation_values import PreparationDeadlinePolicy
from repomap_kg.runtime.plan import LocalRuntimePlan

from .scale15_runtime_environment import Scale15RuntimeFixture
from .scale15_runtime_injection import (
    _InjectedBackend,
    _InjectedChannel,
    _InjectedObserver,
    _InjectedResources,
)


SupervisedRefreshResult: TypeAlias = (
    tuple[TerminalControlResult, AsyncStorageStatistics]
    | tuple[TerminalControlResult, AsyncStorageStatistics, dict[str, object]]
)


class _ControlOptions(TypedDict, total=False):
    control_wait_seconds: float
    fail_after_control: bool
    close_telemetry_after_control: bool
    close_ack_after_control: bool


class _RefreshArgv(Protocol):
    def __call__(
        self,
        fixture: Scale15RuntimeFixture,
        graph_id: str,
        cancel_code: str | None,
        inherited_fds: tuple[int, ...],
        *,
        control_wait_seconds: float = 5.0,
        fail_after_control: bool = False,
        close_telemetry_after_control: bool = False,
        close_ack_after_control: bool = False,
    ) -> tuple[str, ...]: ...


class _StartChild(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        *,
        inherited_fds: Sequence[int],
        cwd: Path,
        environment: Mapping[str, str],
        startup: ActualRefreshStartup | None = None,
    ) -> subprocess.Popen[bytes]: ...


class _AsyncStorageFactory(Protocol):
    def __call__(
        self,
        authority: PostgresStorageAuthority,
        *,
        cadence_seconds: float,
        freshness_seconds: float,
        failure_causality: FailureCausalityAuthority,
        child_released: Callable[[], bool],
    ) -> AsyncPostgresStorageAuthority: ...


@dataclass(frozen=True)
class Scale15RuntimeSupervisionCallbacks:
    """Typed dependencies captured from the campaign facade at call time."""

    refresh_argv: _RefreshArgv
    start_child: _StartChild
    startup_factory: Callable[[], ActualRefreshStartup]
    base_storage_factory: Callable[[LocalRuntimePlan], PostgresStorageAuthority]
    async_storage_factory: _AsyncStorageFactory
    connection_params: Callable[[Sequence[str]], dict[str, str]]
    backend_monitor_factory: Callable[..., BackendOwnershipMonitor[BinaryIO]]
    preparation_bindings: Callable[
        [Scale15RuntimeFixture, str, ExpectedRefreshAuthority, Mapping[str, object]],
        dict[str, str],
    ]
    environment: Callable[[Scale15RuntimeFixture], dict[str, str]]
    repository_root: Callable[[], Path]
    event_reader: EventReaderProtocol[BinaryIO] = read_telemetry_event
    event_channel_factory: Callable[[socket.socket], StagingEventChannel] = StagingEventChannel
    observer_factory: Callable[[], BackendOwnershipObserver] = BackendOwnershipObserver
    injected_channel_factory: Callable[..., _InjectedChannel] = _InjectedChannel
    injected_backend_factory: Callable[..., _InjectedBackend] = _InjectedBackend
    injected_observer_factory: Callable[..., _InjectedObserver] = _InjectedObserver
    injected_resources_factory: Callable[..., _InjectedResources] = _InjectedResources
    child_terminal_factory: Callable[[subprocess.Popen[bytes]], ChildTerminalAuthority] = (
        ChildTerminalAuthority
    )
    scale12_sampler_factory: Callable[..., Scale12ResourceSampler] = Scale12ResourceSampler
    scale14_sampler_factory: Callable[..., Scale14ResourceSampler] = Scale14ResourceSampler
    peak_reader_factory: Callable[[Callable[[], int | None]], PeakRetainingReader] = (
        PeakRetainingReader
    )
    process_rss_reader: Callable[[int], int | None] = read_process_rss_bytes
    container_rss_reader: Callable[[str, str], int | None] = read_container_rss_upper_bound
    temporary_bytes_reader: Callable[..., int | None] = read_database_temporary_bytes
    wal_bytes_reader: Callable[..., int | None] = read_cluster_wal_bytes
    terminal_reader: Callable[..., TerminalReadback] = read_scale16_terminal_state
    backend_summary_reader: Callable[[tuple[str, ...] | list[str]], dict[str, int]] = (
        read_terminal_backend_summary
    )
    supervisor_factory: Callable[..., ActualRefreshSupervisor] = ActualRefreshSupervisor
    preparation_spec_factory: Callable[..., PreparationResourceSpecification] = (
        PreparationResourceSpecification.create
    )
    preparation_authority_factory: Callable[..., HybridPreparationAuthority] = (
        HybridPreparationAuthority
    )
    default_preparation_policy: PreparationDeadlinePolicy = (
        DEFAULT_PREPARATION_DEADLINE_POLICY
    )


def run_supervised_refresh(
    fixture: Scale15RuntimeFixture,
    graph_id: str,
    expected: ExpectedRefreshAuthority,
    *,
    cancel_code: str | None,
    limits: ProtectedLaunchLimits,
    injection: str | None = None,
    control_wait_seconds: float = 5.0,
    fail_after_control: bool = False,
    close_telemetry_after_control: bool = False,
    close_ack_after_control: bool = False,
    private_observer_evidence: bool = False,
    preparation_policy: PreparationDeadlinePolicy | None = None,
    callbacks: Scale15RuntimeSupervisionCallbacks,
) -> SupervisedRefreshResult:
    """Run one real-storage actual child through the terminal controller."""

    psql_args = fixture.psql_args(graph_id)
    startup: ActualRefreshStartup | None = None
    failure_causality = FailureCausalityAuthority()
    storage = callbacks.async_storage_factory(
        callbacks.base_storage_factory(fixture.plan),
        cadence_seconds=1,
        freshness_seconds=5,
        failure_causality=failure_causality,
        child_released=lambda: startup is not None and startup.released,
    )
    baseline = storage.capture_baseline()
    supervisor_socket: socket.socket | None = None
    child_socket: socket.socket | None = None
    event_stream: BinaryIO | None = None
    channel: _InjectedChannel | None = None
    backend: BackendOwnershipMonitor[BinaryIO] | None = None
    startup_ambient_connection: psycopg.Connection[tuple[object, ...]] | None = None
    monitored_resources: _InjectedResources | None = None
    process: subprocess.Popen[bytes] | None = None
    owned_descriptors: set[int] = set()
    try:
        supervisor_socket, child_socket = socket.socketpair()
        backend_read_fd, backend_write_fd = os.pipe()
        owned_descriptors.update((backend_read_fd, backend_write_fd))
        ack_read_fd, ack_write_fd = os.pipe()
        owned_descriptors.update((ack_read_fd, ack_write_fd))
        event_stream = os.fdopen(backend_read_fd, "rb", closefd=True)
        owned_descriptors.remove(backend_read_fd)
        channel = callbacks.injected_channel_factory(
            callbacks.event_channel_factory(supervisor_socket),
            injection,
            cancel_code,
        )
        supervisor_socket = None
        startup = callbacks.startup_factory()
        control_options: _ControlOptions = {}
        if control_wait_seconds != 5.0:
            control_options["control_wait_seconds"] = control_wait_seconds
        if fail_after_control:
            control_options["fail_after_control"] = True
        if close_telemetry_after_control:
            control_options["close_telemetry_after_control"] = True
        if close_ack_after_control:
            control_options["close_ack_after_control"] = True
        process = callbacks.start_child(
            callbacks.refresh_argv(
                fixture,
                graph_id,
                cancel_code,
                (child_socket.fileno(), backend_write_fd, ack_read_fd),
                **control_options,
            ),
            inherited_fds=(child_socket.fileno(), backend_write_fd, ack_read_fd),
            cwd=callbacks.repository_root(),
            environment=callbacks.environment(fixture),
            startup=startup,
        )
        child_socket.close()
        child_socket = None
        os.close(backend_write_fd)
        owned_descriptors.remove(backend_write_fd)
        os.close(ack_read_fd)
        owned_descriptors.remove(ack_read_fd)
        params = callbacks.connection_params(psql_args)
        if injection == "startup_ambient_client":
            startup_ambient_connection = psycopg.connect(
                psycopg.conninfo.make_conninfo(**params), autocommit=True
            )
        child_terminal = callbacks.child_terminal_factory(process)

        def _connect(
            settings: ObserverConnectionSettings | None = None,
        ) -> psycopg.Connection[tuple[object, ...]]:
            conn_params = settings.apply(params) if settings is not None else params
            return psycopg.connect(
                psycopg.conninfo.make_conninfo(**conn_params), autocommit=True
            )

        backend = callbacks.backend_monitor_factory(
            connection_factory=_connect,
            event_reader=callbacks.event_reader,
            event_stream=event_stream,
            acknowledgement_fd=ack_write_fd,
            child_is_live=child_terminal.is_live,
            failure_causality=failure_causality,
            child_released=lambda: startup is not None and startup.released,
            observer_factory=lambda: callbacks.injected_observer_factory(
                callbacks.observer_factory(), injection, channel
            ),
        )
        event_stream = None
        owned_descriptors.remove(ack_write_fd)
        monitored_backend = callbacks.injected_backend_factory(
            backend,
            injection,
            channel,
            failure_causality=failure_causality,
            startup_ambient_connection=startup_ambient_connection,
        )
        resources = callbacks.scale14_sampler_factory(
            callbacks.scale12_sampler_factory(
                {
                    "client_peak_rss_bytes": callbacks.peak_reader_factory(
                        lambda: callbacks.process_rss_reader(process.pid)
                    ),
                    "postgresql_container_rss_upper_bound": callbacks.peak_reader_factory(
                        lambda: callbacks.container_rss_reader(
                            fixture.plan.container_runtime,
                            fixture.plan.identity.postgres_container,
                        )
                    ),
                    "temporary_byte_upper_bound_delta": lambda: monitored_backend.read(
                        callbacks.temporary_bytes_reader
                    ),
                    "wal_upper_bound_delta": lambda: monitored_backend.read(
                        callbacks.wal_bytes_reader
                    ),
                },
                cadence_ns=100_000_000,
            ),
            storage,
        )
        monitored_resources = callbacks.injected_resources_factory(
            resources,
            injection,
            channel,
            failure_causality=failure_causality,
        )
        resource_connection_parameters = dict(params)
        resource_connection_parameters["password"] = fixture.password
        if baseline.current_bytes is None:
            raise AssertionError("storage baseline current bytes unavailable")
        resource_specification = callbacks.preparation_spec_factory(
            pgdata_root=fixture.plan.postgres_data_dir,
            pgdata_baseline_bytes=baseline.current_bytes,
            client_pid=process.pid,
            container_runtime=fixture.plan.container_runtime,
            postgres_container=fixture.plan.identity.postgres_container,
            connection_parameters=resource_connection_parameters,
        )
        preparation_authority = callbacks.preparation_authority_factory(
            resource_specification,
            callbacks.preparation_bindings(fixture, graph_id, expected, params),
            preparation_policy or callbacks.default_preparation_policy,
        )
        supervisor = callbacks.supervisor_factory(
            process,
            channel,
            monitored_resources,
            monitored_backend,
            terminal_reader=lambda terminal_expectation: callbacks.terminal_reader(
                psql_args, terminal_expectation
            ),
            cleanup_verifier=lambda readback: readback.cleanup_state,
            terminal_backend_reader=lambda: callbacks.backend_summary_reader(psql_args),
            limits=limits,
            storage_baseline=baseline,
            prelaunch_expectation=expected,
            startup=startup,
            child_terminal=child_terminal,
            poll_interval_seconds=0.25,
            signal_grace_seconds=5,
            failure_causality=failure_causality,
            preparation_authority=preparation_authority,
        )
        result = supervisor.run()
        if private_observer_evidence:
            return result, storage.statistics(), {
                "causality": failure_causality.candidates(),
                "session": backend.session_snapshot(),
                "preparation": preparation_authority.snapshot(),
            }
        return result, storage.statistics()
    finally:
        if startup is not None:
            if not startup.released:
                startup.fail()
            startup.close()
        if monitored_resources is not None:
            monitored_resources.close()
        if backend is not None:
            backend.close()
        elif event_stream is not None:
            event_stream.close()
        if channel is not None:
            channel.close()
        elif supervisor_socket is not None:
            supervisor_socket.close()
        if child_socket is not None:
            child_socket.close()
        for descriptor in owned_descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if startup_ambient_connection is not None:
            startup_ambient_connection.close()


__all__ = [
    "Scale15RuntimeSupervisionCallbacks",
    "SupervisedRefreshResult",
    "run_supervised_refresh",
]
