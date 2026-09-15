"""Schema upgrade and adoption workflow for coordinator control."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from repomap_kg.coordinator._lifecycle_authority import (
    CoordinatorControlError,
    LocalControlAuthority,
    _maintenance_window,
    _validate_reference_database,
)
from repomap_kg.runtime.backup import dump_database, inspect_backup
from repomap_kg.runtime.backup_commands import timestamp_utc


class _SchemaStatus(Protocol):
    @property
    def value(self) -> str: ...


class _SchemaReadiness(Protocol):
    @property
    def status(self) -> _SchemaStatus: ...


class _UpgradeStore(Protocol):
    def check_schema_version(self) -> int: ...

    def initialize_schema(self) -> None: ...

    def schema_readiness(self) -> _SchemaReadiness: ...

    def schema_manifest(self) -> tuple[str, ...]: ...

    def adopt_preledger_schema(
        self,
        *,
        expected_manifest: tuple[str, ...],
        backup_verified: bool,
    ) -> None: ...


class _UpgradeAuthority(Protocol):
    @property
    def database_name(self) -> str: ...

    @property
    def graph_databases(self) -> tuple[str, ...]: ...

    def database_exists(self) -> bool: ...

    def control_store(self) -> _UpgradeStore: ...

    def reference_database_exists(self, database: str) -> bool: ...

    def create_reference_database(self, database: str) -> None: ...

    def control_store_for(self, database: str) -> _UpgradeStore: ...

    def drop_reference_database(self, database: str) -> None: ...


class _BackupPlan(Protocol):
    @property
    def backup_path(self) -> Path: ...


class _DumpResult(Protocol):
    @property
    def plan(self) -> _BackupPlan: ...


class _InspectResult(Protocol):
    @property
    def checksum_verified(self) -> bool: ...

    @property
    def dump_summaries(self) -> Sequence[object]: ...

    @property
    def manifest(self) -> Mapping[str, object]: ...


class _DumpFunction(Protocol):
    def __call__(
        self,
        repo_map_home: str | Path | None,
        *,
        database: str,
        reason: str | None = None,
        timestamp: str | None = None,
    ) -> _DumpResult: ...


class _InspectFunction(Protocol):
    def __call__(
        self,
        repo_map_home: str | Path | None,
        backup_id_or_path: str | Path,
    ) -> _InspectResult: ...


def _reconcile_control_roles(authority: object) -> None:
    reconcile_roles = getattr(authority, "reconcile_control_roles", None)
    if reconcile_roles is not None:
        if not callable(reconcile_roles):
            raise TypeError("reconcile_control_roles is not callable")
        reconcile_roles()


def _reference_database_name(timestamp: str) -> str:
    value = f"repomap_control_ref_{timestamp.replace('T', '_').removesuffix('Z')}"
    _validate_reference_database(value)
    return value


def upgrade_coordinator_control(
    repo_map_home: str | Path,
    *,
    backup_first: bool = False,
    confirmed: bool = False,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    authority_factory: Callable[[str | Path], _UpgradeAuthority] = LocalControlAuthority,
    dump_function: _DumpFunction = dump_database,
    inspect_function: _InspectFunction = inspect_backup,
) -> dict[str, object]:
    """Adopt control schema while holding cross-plane maintenance ownership."""

    if not backup_first or dry_run or not confirmed:
        return _upgrade_coordinator_control_owned(
            repo_map_home,
            backup_first=backup_first,
            confirmed=confirmed,
            dry_run=dry_run,
            reason=reason,
            timestamp=timestamp,
            authority_factory=authority_factory,
            dump_function=dump_function,
            inspect_function=inspect_function,
        )
    try:
        authority = authority_factory(repo_map_home)
        with _maintenance_window(
            authority, graph_databases=authority.graph_databases
        ):
            return _upgrade_coordinator_control_owned(
                repo_map_home,
                backup_first=backup_first,
                confirmed=confirmed,
                dry_run=dry_run,
                reason=reason,
                timestamp=timestamp,
                authority_factory=lambda _home: authority,
                dump_function=dump_function,
                inspect_function=inspect_function,
            )
    except CoordinatorControlError:
        raise
    except Exception:
        raise CoordinatorControlError("coordinator_control_upgrade_failed") from None


def _upgrade_coordinator_control_owned(
    repo_map_home: str | Path,
    *,
    backup_first: bool = False,
    confirmed: bool = False,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    authority_factory: Callable[[str | Path], _UpgradeAuthority] = LocalControlAuthority,
    dump_function: _DumpFunction = dump_database,
    inspect_function: _InspectFunction = inspect_backup,
) -> dict[str, object]:
    """Adopt one exact supported pre-ledger coordinator control database."""

    if not backup_first:
        raise CoordinatorControlError("coordinator_control_backup_first_required")
    if not dry_run and not confirmed:
        raise CoordinatorControlError("coordinator_control_upgrade_confirmation_required")
    actions = (
        "inspect-control-schema",
        "create-and-inspect-backup",
        "create-reference-database",
        "compare-schema-manifest",
        "bootstrap-control-ledger",
        "drop-reference-database",
    )
    if dry_run:
        return {
            "command": "coordinator-control-upgrade",
            "result": "planned",
            "planned_actions": list(actions),
            "backup_verified": False,
            "rollback_available": False,
            "reference_cleaned": False,
        }

    try:
        authority = authority_factory(repo_map_home)
        if not authority.database_exists():
            raise RuntimeError("control database is absent")
        target_store = authority.control_store()
        if target_store.schema_readiness().status.value != "preledger":
            raise RuntimeError("control schema is not pre-ledger")

        upgrade_timestamp = timestamp or timestamp_utc()
        reference_database = _reference_database_name(upgrade_timestamp)
        if authority.reference_database_exists(reference_database):
            raise RuntimeError("control schema reference already exists")

        backup = dump_function(
            repo_map_home,
            database=authority.database_name,
            reason=reason or "pre-control-schema-upgrade",
            timestamp=upgrade_timestamp,
        )
        inspection = inspect_function(repo_map_home, backup.plan.backup_path)
        if not (
            inspection.checksum_verified
            and inspection.dump_summaries
            and inspection.manifest.get("restore_supported") is True
        ):
            raise RuntimeError("control backup is not restorable")

        reference_created = False
        reference_cleaned = False
        try:
            authority.create_reference_database(reference_database)
            reference_created = True
            reference_store = authority.control_store_for(reference_database)
            reference_store.initialize_schema()
            target_store.adopt_preledger_schema(
                expected_manifest=reference_store.schema_manifest(),
                backup_verified=True,
            )
            version = target_store.check_schema_version()
        finally:
            if reference_created:
                authority.drop_reference_database(reference_database)
                reference_cleaned = True

        _reconcile_control_roles(authority)

        return {
            "command": "coordinator-control-upgrade",
            "result": "ready",
            "schema_before": "supported-preledger",
            "schema_version": version,
            "backup_verified": True,
            "rollback_available": True,
            "reference_cleaned": reference_cleaned,
            "planned_actions": list(actions),
        }
    except Exception:
        raise CoordinatorControlError("coordinator_control_upgrade_failed") from None
