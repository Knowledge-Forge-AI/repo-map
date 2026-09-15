"""Public-safe disposable SCALE15 real-runtime campaign support."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import socket as socket
import subprocess
import sys
import time

import psycopg as psycopg

from actual_refresh_startup import ActualRefreshStartup
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.config_loading import load_ops_config as load_ops_config
from repomap_kg.ops.generations import (
    canonicalizer_generation,
    config_generation,
    extractor_generation,
    source_generation,
)
from repomap_kg.runtime.backup_commands import (
    read_runtime_password as read_runtime_password,
)
from repomap_kg.runtime.local import (
    down_local_runtime as down_local_runtime,
    setup_local_runtime as setup_local_runtime,
    up_local_runtime as up_local_runtime,
)
from repomap_kg.runtime.plan import (
    LocalRuntimePlan as LocalRuntimePlan,
    build_local_runtime_plan as build_local_runtime_plan,
)
from repomap_kg.storage.authority import PublicationGenerations
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_telemetry import read_telemetry_event
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.structural_digest import digest_prepared_stage_rows
from repomap_kg.storage.staging_event_transport import StagingEventChannel
from scale12_resource_sampling import (
    Scale12ResourceSampler,
    read_cluster_wal_bytes,
    read_container_rss_upper_bound,
    read_database_temporary_bytes,
    read_process_rss_bytes,
)
from scale13_actual_refresh_supervisor import start_actual_refresh_child
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from scale14_backend_monitor import BackendOwnershipMonitor
from scale14_postgres_storage import PostgresStorageAuthority
from scale14_resource_sampling import PeakRetainingReader, Scale14ResourceSampler
from scale15_actual_path_readback import read_terminal_backend_summary
from scale16_actual_path_readback import read_scale16_terminal_state
from scale15_async_storage import AsyncPostgresStorageAuthority
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
)
from scale25_terminal_settlement import ChildTerminalAuthority
from scale28_preparation_authority import HybridPreparationAuthority
from scale28_preparation_resources import PreparationResourceSpecification
from scale28_preparation_policy import DEFAULT_PREPARATION_DEADLINE_POLICY
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationDeadlinePolicy,
    canonical_protocol_bytes,
)

from .scale15_runtime_environment import (
    Scale15RuntimeFixture as Scale15RuntimeFixture,
    Scale15RuntimeEnvironmentCallbacks as Scale15RuntimeEnvironmentCallbacks,
    _actual_config as _actual_config,
    _available_port as _available_port,
    _config_text as _config_text,
    _database as _database,
    _environment,
    _repository_root,
    _runtime_config as _runtime_config,
    _start_loopback_proxy as _start_loopback_proxy,
    _wait_for_databases as _wait_for_databases,
    start_scale15_runtime as _start_scale15_runtime,
    stop_scale15_runtime as _stop_scale15_runtime,
)
from .scale15_runtime_injection import (
    _InjectedBackend,
    _InjectedChannel,
    _InjectedObserver,
    _InjectedResources,
)
from . import scale15_runtime_supervision as _runtime_supervision
from .scale15_runtime_supervision import (
    Scale15RuntimeSupervisionCallbacks as Scale15RuntimeSupervisionCallbacks,
    SupervisedRefreshResult as SupervisedRefreshResult,
)


def _runtime_environment_callbacks() -> Scale15RuntimeEnvironmentCallbacks:
    return Scale15RuntimeEnvironmentCallbacks(
        setup_local_runtime,
        _available_port,
        _runtime_config,
        _actual_config,
        build_local_runtime_plan,
        read_runtime_password,
        up_local_runtime,
        down_local_runtime,
        _start_loopback_proxy,
        _wait_for_databases,
        load_ops_config,
        _environment,
    )


def start_scale15_runtime(
    root: Path,
    graph_ids: tuple[str, ...],
) -> Scale15RuntimeFixture:
    return _start_scale15_runtime(
        root,
        graph_ids,
        callbacks=_runtime_environment_callbacks(),
    )


def stop_scale15_runtime(fixture: Scale15RuntimeFixture) -> None:
    _stop_scale15_runtime(
        fixture,
        callbacks=_runtime_environment_callbacks(),
    )


def expected_authority(
    fixture: Scale15RuntimeFixture,
    graph_id: str,
    family_counts,
    structural_digest: str,
    **prior,
) -> ExpectedRefreshAuthority:
    """Derive the exact private launch generations through product functions."""

    config = fixture.config
    graph = next(item for item in config.graphs if item.id == graph_id)
    observations = tuple(
        discover_observations(
            fixture.repository,
            exclude_paths=graph.exclude_paths,
        )
    )
    generations = PublicationGenerations(
        source_generation(observations),
        config_generation(config, graph, fixture.repository.resolve()),
        extractor_generation(graph),
        canonicalizer_generation(),
    ).validate()
    prepared = build_staged_rows(
        observations,
        repository_name=graph.repository_name,
        stage_id="scale15-expected",
    )
    del observations
    try:
        assert dict(prepared.row_counts) == dict(family_counts)
        assert digest_prepared_stage_rows(prepared) == structural_digest
    finally:
        prepared.close()
    return ExpectedRefreshAuthority(
        repository_identity=f"repo1:{graph_id}",
        repository_name=graph.repository_name,
        generations=generations,
        execution_mode="direct",
        zero_state_first_publication=not prior,
        expected_family_counts=family_counts,
        expected_structural_digest=structural_digest,
        **prior,
    ).validate()


def run_ordinary_refresh(
    fixture: Scale15RuntimeFixture,
    graph_id: str,
) -> subprocess.CompletedProcess[str]:
    """Run the ordinary current-source direct command for reference evidence."""

    refresh_argv_fn = _refresh_argv
    return subprocess.run(
        refresh_argv_fn(fixture, graph_id, None, ()),
        cwd=_repository_root(),
        env=_environment(fixture),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )


def _private_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_protocol_bytes(value)).hexdigest()


def _preparation_bindings(
    fixture: Scale15RuntimeFixture,
    graph_id: str,
    expected: ExpectedRefreshAuthority,
    connection_parameters: Mapping[str, object],
) -> dict[str, str]:
    generations = expected.generations
    values: dict[str, dict[str, object]] = {
        "runtime_scope_digest": {
            "home_hash": fixture.plan.identity.home_hash,
            "graph_id": graph_id,
            "repository_identity": expected.repository_identity,
        },
        "topology_digest": {
            "container_runtime": fixture.plan.container_runtime,
            "postgres_container": fixture.plan.identity.postgres_container,
            "database": str(connection_parameters.get("dbname", "")),
        },
        "pgdata_generation_digest": {
            "postgres_data_dir": str(fixture.plan.postgres_data_dir),
            "postgres_container": fixture.plan.identity.postgres_container,
        },
        "configuration_generation_digest": {
            "publication_generations": list(generations.values()),
        },
        "observer_generation_digest": {
            "observer_contract": "one-live-session-v1",
            "parent_pid": os.getpid(),
            "created_ns": time.monotonic_ns(),
        },
    }
    assert set(values) == set(BINDING_FIELDS)
    return {name: _private_digest(values[name]) for name in BINDING_FIELDS}


def _runtime_supervision_callbacks() -> Scale15RuntimeSupervisionCallbacks:
    return Scale15RuntimeSupervisionCallbacks(
        refresh_argv=_refresh_argv,
        start_child=start_actual_refresh_child,
        startup_factory=ActualRefreshStartup.create,
        base_storage_factory=PostgresStorageAuthority,
        async_storage_factory=AsyncPostgresStorageAuthority,
        connection_params=_psycopg_connection_params_from_psql_args,
        backend_monitor_factory=BackendOwnershipMonitor,
        event_reader=read_telemetry_event,
        event_channel_factory=StagingEventChannel,
        observer_factory=BackendOwnershipObserver,
        injected_channel_factory=_InjectedChannel,
        injected_backend_factory=_InjectedBackend,
        injected_observer_factory=_InjectedObserver,
        injected_resources_factory=_InjectedResources,
        child_terminal_factory=ChildTerminalAuthority,
        scale12_sampler_factory=Scale12ResourceSampler,
        scale14_sampler_factory=Scale14ResourceSampler,
        peak_reader_factory=PeakRetainingReader,
        process_rss_reader=read_process_rss_bytes,
        container_rss_reader=read_container_rss_upper_bound,
        temporary_bytes_reader=read_database_temporary_bytes,
        wal_bytes_reader=read_cluster_wal_bytes,
        terminal_reader=read_scale16_terminal_state,
        backend_summary_reader=_wait_fresh_backend,
        supervisor_factory=ActualRefreshSupervisor,
        preparation_spec_factory=PreparationResourceSpecification.create,
        preparation_authority_factory=HybridPreparationAuthority,
        default_preparation_policy=DEFAULT_PREPARATION_DEADLINE_POLICY,
        preparation_bindings=_preparation_bindings,
        environment=_environment,
        repository_root=_repository_root,
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
) -> SupervisedRefreshResult:
    return _runtime_supervision.run_supervised_refresh(
        fixture,
        graph_id,
        expected,
        cancel_code=cancel_code,
        limits=limits,
        injection=injection,
        control_wait_seconds=control_wait_seconds,
        fail_after_control=fail_after_control,
        close_telemetry_after_control=close_telemetry_after_control,
        close_ack_after_control=close_ack_after_control,
        private_observer_evidence=private_observer_evidence,
        preparation_policy=preparation_policy,
        callbacks=_runtime_supervision_callbacks(),
    )


def _refresh_argv(
    fixture: Scale15RuntimeFixture,
    graph_id: str,
    cancel_code: str | None,
    inherited_fds: tuple[int, ...],
    *,
    control_wait_seconds: float = 5.0,
    fail_after_control: bool = False,
    close_telemetry_after_control: bool = False,
    close_ack_after_control: bool = False,
) -> tuple[str, ...]:
    product: tuple[str, ...] = (
        "ops",
        "refresh-graph",
        "--config",
        str(fixture.config_path),
        "--graph",
        graph_id,
        "--psql-command",
        "psql",
        "--json",
    )
    if inherited_fds:
        product = (
            *product[:-1],
            "--staging-event-fd",
            str(inherited_fds[0]),
            "--backend-telemetry-fd",
            str(inherited_fds[1]),
            "--backend-telemetry-ack-fd",
            str(inherited_fds[2]),
            "--json",
        )
    if cancel_code is None:
        return (sys.executable, "-m", "repomap_kg", *product)
    controls = [
        sys.executable,
        "-m",
        "repomap_test_support.scale14_actual_refresh_child",
        "--cancel-code",
        cancel_code,
        "--wait-seconds",
        str(control_wait_seconds),
    ]
    if fail_after_control:
        controls.append("--fail-after-control")
    if close_telemetry_after_control:
        controls.append("--close-telemetry-after-control")
    if close_ack_after_control:
        controls.append("--close-ack-after-control")
    return (
        *controls,
        "--",
        *product,
    )


def _wait_fresh_backend(psql_args: tuple[str, ...] | list[str]) -> dict[str, int]:
    return read_terminal_backend_summary(psql_args)


__all__ = [
    "Scale15RuntimeFixture",
    "expected_authority",
    "run_ordinary_refresh",
    "run_supervised_refresh",
    "start_scale15_runtime",
    "stop_scale15_runtime",
]
