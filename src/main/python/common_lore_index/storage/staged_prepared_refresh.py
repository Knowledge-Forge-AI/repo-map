"""Direct PostgreSQL publication of already witnessed staged rows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from common_lore_index.canonicalization.rust_pilot_family import WitnessedCanonicalization
from common_lore_index.storage.backend_telemetry import BackendTelemetry
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.main import LoadSummary
from common_lore_index.storage.staged_rows import PreparedStageRows, build_staged_rows
from common_lore_index.storage.staging_observability import StagingMeasurements

if TYPE_CHECKING:
    from common_lore_index.storage.staged_ingestion import IngestionAuthority

_DEFAULT_STAGE_TTL = timedelta(hours=24)


def run_staged_prepared_refresh(
    psql_args: Sequence[str], witnessed: WitnessedCanonicalization, *,
    repository_name: str, root_path: str, authority: IngestionAuthority,
    repository_identity: str | None = None, git_commit: str | None = None,
    stage_id: str | None = None, stage_ttl: timedelta = _DEFAULT_STAGE_TTL,
    connect: Callable[..., Any] | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> LoadSummary:
    from common_lore_index.storage.staged_ingestion import (
        _admit_and_run, _run_staged_full_refresh_admitted, stage_id_for_authority,
    )
    if type(witnessed) is not WitnessedCanonicalization:
        raise StorageSchemaError("invalid Rust pilot witness")
    if authority.execution_mode != "direct" or not witnessed.verify_live():
        raise StorageSchemaError("Rust pilot witness is not live or direct")
    if stage_ttl <= timedelta(0):
        raise ValueError("staged ingestion expiry must be positive")
    resolved_stage_id = stage_id or stage_id_for_authority(authority)
    prepared: PreparedStageRows = build_staged_rows(
        witnessed.observations, repository_name=repository_name, stage_id=resolved_stage_id,
        staging_measurements=staging_measurements, witnessed=witnessed,
    )
    original = authority.before_publication

    def before_publication() -> None:
        if not witnessed.verify_live():
            raise StorageSchemaError("Rust pilot witness changed before publication")
        if original is not None:
            original()
        if not witnessed.verify_live():
            raise StorageSchemaError("Rust pilot witness changed during publication callback")

    try:
        fenced = replace(authority, before_publication=before_publication).validate()
    except BaseException:
        prepared.close()
        raise
    try:
        if not witnessed.verify_live():
            raise StorageSchemaError("Rust pilot witness changed before admission")
        return _admit_and_run(
            psql_args, fenced, backend_telemetry,
            lambda: _run_staged_full_refresh_admitted(
                psql_args, witnessed.observations, repository_name=repository_name,
                root_path=root_path, authority=fenced, repository_identity=repository_identity,
                git_commit=git_commit, stage_id=resolved_stage_id, stage_ttl=stage_ttl, connect=connect,
                backend_telemetry=backend_telemetry, staging_measurements=staging_measurements,
                prepared_override=prepared,
            ),
        )
    finally:
        prepared.close()


__all__ = ("run_staged_prepared_refresh",)
