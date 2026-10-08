"""Worker-side configured generation checks and forced-full delegation."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Protocol

from repomap_kg.runtime import system_test_pause as pause_window
from repomap_kg.coordinator._refresh_contracts import (
    RefreshConfigurationError,
    RefreshGenerationChangedError,
    RefreshSourceError,
)
from repomap_kg.coordinator._refresh_generation import (
    ConfiguredGenerationChanged,
    validate_configured_generations,
)
from repomap_kg.runtime.postgres_route import (
    CONTAINER_INTERNAL_MARKER,
    effective_postgres_route,
)
from repomap_kg.runtime.system_test_pause import (
    SYSTEM_TEST_PRODUCER_PAUSE_SECONDS as SYSTEM_TEST_PRODUCER_PAUSE_SECONDS,
    SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS as SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS,
    SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS as SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS,
    SYSTEM_TEST_STATUS_TIMEOUT_SECONDS as SYSTEM_TEST_STATUS_TIMEOUT_SECONDS,
    SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS as SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS,
    SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS as SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS,
    SYSTEM_TEST_INTERRUPTION_TIMEOUT_SECONDS as SYSTEM_TEST_INTERRUPTION_TIMEOUT_SECONDS,
    SYSTEM_TEST_PAUSE_SAFETY_MARGIN_SECONDS as SYSTEM_TEST_PAUSE_SAFETY_MARGIN_SECONDS,
    validate_pause_window_contract as validate_pause_window_contract,
)
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import RunPublicationReceipt

_SYSTEM_TEST_PAUSE_PATH: Path | None = Path("/tmp/system_pause_trigger")
_SYSTEM_TEST_READY_PATH: Path | None = Path("/tmp/system_pause_trigger.ready")



class ExecutionCapability(Protocol):
    @property
    def job_id(self) -> str: ...
    @property
    def attempt(self) -> int: ...
    @property
    def graph_id(self) -> str: ...
    @property
    def config_path(self) -> Path: ...
    @property
    def psql_path(self) -> Path: ...
    @property
    def postgres_host(self) -> str: ...
    @property
    def postgres_port(self) -> int: ...
    @property
    def postgres_route_kind(self) -> str: ...
    @property
    def postgres_user(self) -> str: ...
    @property
    def postgres_password(self) -> str: ...
    @property
    def source_generation(self) -> str: ...
    @property
    def config_generation(self) -> str: ...
    @property
    def extractor_generation(self) -> str: ...
    @property
    def canonicalizer_generation(self) -> str: ...
    @property
    def coordinator_instance_id(self) -> str | None: ...
    @property
    def singleton_fencing_epoch(self) -> int: ...
    @property
    def graph_lease_fencing_epoch(self) -> int: ...
    @property
    def process_deadline_seconds(self) -> int: ...

    def validate(self) -> object: ...
    def publication_receipt(self) -> RunPublicationReceipt: ...


def _is_safe_test_path(path: Path) -> bool:
    """Validate that path resides in a private directory owned by current user with mode 0700."""
    try:
        if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
            return False
        st = path.parent.stat()
        return st.st_uid == os.getuid() and (st.st_mode & 0o777) == 0o700
    except OSError:
        return False


def _run_system_test_pause(capability: ExecutionCapability) -> None:
    """Internal test instrumentation: pause before publication when configured.

    Disabled by default; only active when _REPOMAP_SYSTEM_TEST_PAUSE_PATH points
    to a valid private test directory or matches an explicit containerized test pause path.
    """
    pause_path_str = os.environ.get("_REPOMAP_SYSTEM_TEST_PAUSE_PATH")
    if not pause_path_str:
        return
    pause_path = Path(pause_path_str)
    is_legacy_hook = (
        _SYSTEM_TEST_PAUSE_PATH is not None
        and pause_path == _SYSTEM_TEST_PAUSE_PATH
        and CONTAINER_INTERNAL_MARKER.is_file()
    )
    if not is_legacy_hook and not _is_safe_test_path(pause_path):
        return
    validate_pause_window_contract()
    ready_path = (
        _SYSTEM_TEST_READY_PATH
        if is_legacy_hook and _SYSTEM_TEST_READY_PATH is not None
        else Path(f"{pause_path_str}.ready")
    )
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        marker_fd = os.open(str(ready_path), flags, 0o600)
        with os.fdopen(marker_fd, "w", encoding="utf-8") as marker:
            if is_legacy_hook:
                marker.write(
                    f"job_id={capability.job_id}\nattempt={capability.attempt}\n"
                )
            else:
                marker.write(
                    f"job_id={capability.job_id}\nattempt={capability.attempt}\npid={os.getpid()}\n"
                )
        deadline = time.monotonic() + pause_window.SYSTEM_TEST_PRODUCER_PAUSE_SECONDS
        while pause_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    except (AttributeError, OSError):
        pass
    finally:
        try:
            ready_path.unlink(missing_ok=True)
        except OSError:
            pass


def execute_refresh_attempt(
    capability: ExecutionCapability, *, before_publication: Callable[[], None] | None = None,
) -> object:
    from repomap_kg.ops.config import load_ops_config
    from repomap_kg.ops.refresh import (
        OpsRefreshError,
        OpsRefreshGenerationChangedError,
        refresh_graph,
    )
    from repomap_kg.runtime.database_role_contract import (
        project_database_role_config,
    )
    from repomap_kg.storage.staged_ingestion import IngestionAuthority

    capability.validate()
    try:
        config = load_ops_config(capability.config_path)
        execution_config = project_database_role_config(
            config,
            role=capability.postgres_user,
            password=capability.postgres_password,
        )
        validate_configured_generations(execution_config, capability)
        route = effective_postgres_route(execution_config)
        if (route.host, route.port, route.kind) != (
            capability.postgres_host, capability.postgres_port, capability.postgres_route_kind,
        ):
            raise ConfiguredGenerationChanged("refresh route changed")
        # Hash configured values; apply the recomputed, matching route only
        # to the role-projected PostgreSQL connection at the storage boundary.
    except ConfiguredGenerationChanged as error:
        raise RefreshGenerationChangedError("refresh generation changed") from error
    except RefreshSourceError:
        raise
    except RefreshConfigurationError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise RefreshConfigurationError("refresh configuration failed") from error
    _run_system_test_pause(capability)

    try:
        return refresh_graph(
            execution_config,
            capability.graph_id,
            psql_command=str(capability.psql_path),
            publication_receipt=capability.publication_receipt(),
            ingestion_mode="staged",
            _postgres_route=route,
            staged_authority=IngestionAuthority(
                operation_id=OperationId(capability.job_id),
                attempt=AttemptNumber(capability.attempt),
                execution_mode="coordinator",
                source_generation=capability.source_generation,
                config_generation=capability.config_generation,
                extractor_generation=capability.extractor_generation,
                canonicalizer_generation=capability.canonicalizer_generation,
                job_id=JobId(capability.job_id),
                coordinator_instance_id=capability.coordinator_instance_id,
                singleton_fencing_epoch=capability.singleton_fencing_epoch,
                graph_lease_fencing_epoch=capability.graph_lease_fencing_epoch,
                before_publication=before_publication,
                process_deadline_seconds=getattr(capability, "process_deadline_seconds", None),
            ),
        )
    except OpsRefreshGenerationChangedError as error:
        raise RefreshGenerationChangedError("refresh generation changed") from error
    except OpsRefreshError as error:
        # OpsRefreshError is raised strictly during refresh_graph preflight checks
        # (graph disabled, root path nonexistent, unsupported classification)
        # before any ingestion, subprocess execution, or publication begins.
        raise RefreshConfigurationError(str(error)) from error


__all__ = ["execute_refresh_attempt"]
