"""Worker-side configured generation checks and forced-full delegation."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Protocol

from repomap_kg.coordinator._refresh_contracts import (
    RefreshConfigurationError,
    RefreshGenerationChangedError,
    RefreshSourceError,
)
from repomap_kg.coordinator._refresh_generation import (
    ConfiguredGenerationChanged,
    validate_configured_generations,
)
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import RunPublicationReceipt

_SYSTEM_TEST_PAUSE_PATH = Path("/tmp/system_pause_trigger")
_SYSTEM_TEST_READY_PATH = Path("/tmp/system_pause_trigger.ready")


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

    def validate(self) -> object: ...
    def publication_receipt(self) -> RunPublicationReceipt: ...


def _run_system_test_pause(capability: ExecutionCapability) -> None:
    pause_path_str = os.environ.get("_REPOMAP_SYSTEM_TEST_PAUSE_PATH")
    if pause_path_str != str(_SYSTEM_TEST_PAUSE_PATH):
        return
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        marker_fd = os.open(_SYSTEM_TEST_READY_PATH, flags, 0o600)
        with os.fdopen(marker_fd, "w", encoding="utf-8") as marker:
            marker.write(
                f"job_id={capability.job_id}\nattempt={capability.attempt}\n"
            )
    except (AttributeError, OSError):
        pass
    deadline = time.monotonic() + 30.0
    while _SYSTEM_TEST_PAUSE_PATH.exists() and time.monotonic() < deadline:
        time.sleep(0.05)


def execute_refresh_attempt(capability: ExecutionCapability) -> object:
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
