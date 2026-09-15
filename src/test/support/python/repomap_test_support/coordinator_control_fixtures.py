"""Typed doubles for coordinator control and lifecycle unit tests."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from psycopg import sql
from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.coordinator.local_lifecycle import LocalControlAuthority
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.runtime.database_role_contract import RoleSecrets
from repomap_test_support.coordinator_client_fixtures import (
    CustomPageClient, FakeCoordinatorClient, ItemClient, fixed_client_factory,
)


WindowEvent: TypeAlias = str | tuple[str, tuple[str, ...]]


class CaptureConnection:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.statements: list[str | sql.Composable] = []
        self.row = row

    def __enter__(self) -> CaptureConnection:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False

    def execute(
        self,
        statement: str | sql.Composable,
        _parameters: tuple[object, ...] | None = None,
    ) -> CaptureConnection:
        self.statements.append(statement)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class BareAuthority(LocalControlAuthority):
    def __init__(
        self,
        connection: CaptureConnection,
        *,
        capability: str = "lifecycle",
    ) -> None:
        self._home = Path("/placeholder/home")
        self._capability = capability
        self._database = "repomap_control"
        self._maintenance_database = "postgres"
        self._owner_user = "repomap_owner"
        self._admin_password = "admin-secret"
        self._role_secrets = RoleSecrets(
            read_status="status-secret",
            coordinator_control="control-secret",
            refresh_publication="refresh-secret",
        )
        self._host = "127.0.0.1"
        self._port = 5432
        self._graph_databases = ("graph-a", "graph-b")
        self._connection = connection

    def _connect(
        self,
        _database: str,
        *,
        autocommit: bool = False,
    ) -> CaptureConnection:
        del autocommit
        return self._connection


class FakeStore:
    def __init__(self, authority: FakeAuthority) -> None:
        self.authority = authority

    def check_schema_version(self) -> int:
        self.authority.checked += 1
        if self.authority.schema_error:
            raise ControlSchemaError("private schema detail")
        return 1

    def initialize_schema(self) -> None:
        self.authority.initialized += 1
        if self.authority.initialize_error:
            raise ValueError("private initialize detail")


class FakeAuthority:
    def __init__(
        self,
        *,
        exists: bool = False,
        schema_error: bool = False,
        initialize_error: bool = False,
        create_result: bool = True,
        drop_error: bool = False,
    ) -> None:
        self.exists = exists
        self.schema_error = schema_error
        self.initialize_error = initialize_error
        self.create_result = create_result
        self.drop_error = drop_error
        self.created = 0
        self.checked = 0
        self.initialized = 0
        self.dropped = 0
        self.reconciled = 0

    def database_exists(self) -> bool:
        return self.exists

    def create_database(self) -> bool:
        self.created += 1
        self.exists = self.create_result
        return self.create_result

    def drop_created_database(self) -> None:
        self.dropped += 1
        if self.drop_error:
            raise RuntimeError("private drop detail")
        self.exists = False

    def control_store(self) -> FakeStore:
        return FakeStore(self)

    def reconcile_control_roles(self) -> None:
        self.reconciled += 1


class WindowAuthority:
    database_name = "repomap_control"
    graph_databases = ("graph-a", "graph-b")

    def __init__(
        self,
        events: list[WindowEvent],
        *,
        failure: BaseException | None = None,
    ) -> None:
        self.events = events
        self.failure = failure

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        self.events.append("activity-enter")
        try:
            yield
        finally:
            self.events.append("activity-exit")

    @contextmanager
    def maintenance_window(
        self,
        *,
        graph_databases: tuple[str, ...],
    ) -> Iterator[None]:
        if self.failure is not None:
            raise self.failure
        self.events.append(("window-enter", graph_databases))
        try:
            yield
        finally:
            self.events.append(("window-exit", graph_databases))


class StoreWindow(ControlStore):
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    @contextmanager
    def maintenance_window(self) -> Iterator[None]:
        self.events.append(f"enter:{self.name}")
        try:
            yield
        finally:
            self.events.append(f"exit:{self.name}")

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        self.events.append(f"activity:{self.name}")
        yield


class OwnedMaintenanceAuthority(LocalControlAuthority):
    def __init__(self, events: list[str]) -> None:
        self._database = "repomap_control"
        self._graph_databases = ("graph-a", "graph-b")
        self._events = events

    def control_store(self) -> StoreWindow:
        return StoreWindow("control", self._events)

    def control_store_for(self, database: str) -> StoreWindow:
        return StoreWindow(database, self._events)


@dataclass(frozen=True)
class SchemaStatus:
    value: str


@dataclass(frozen=True)
class SchemaReadiness:
    status: SchemaStatus


class UpgradeStore:
    def __init__(
        self,
        events: list[str],
        *,
        status: str = "preledger",
        fail_adoption: bool = False,
    ) -> None:
        self.events = events
        self.status = status
        self.fail_adoption = fail_adoption

    def schema_readiness(self) -> SchemaReadiness:
        return SchemaReadiness(SchemaStatus(self.status))

    def initialize_schema(self) -> None:
        self.events.append("initialize-reference")

    def schema_manifest(self) -> tuple[str, ...]:
        self.events.append("manifest-reference")
        return ("exact-control-schema",)

    def adopt_preledger_schema(
        self,
        *,
        expected_manifest: tuple[str, ...],
        backup_verified: bool,
    ) -> None:
        self.events.append("adopt-target")
        assert expected_manifest == ("exact-control-schema",)
        assert backup_verified is True
        if self.fail_adoption:
            raise RuntimeError("private adoption detail")

    def check_schema_version(self) -> int:
        return 1


class UpgradeAuthority:
    database_name = "repomap_control"
    graph_databases = ("graph-b", "graph-a")

    def __init__(
        self,
        events: list[str],
        *,
        status: str = "preledger",
        fail_adoption: bool = False,
    ) -> None:
        self.events = events
        self.target = UpgradeStore(
            events, status=status, fail_adoption=fail_adoption
        )
        self.reference = UpgradeStore(events)

    def database_exists(self) -> bool:
        return True

    def control_store(self) -> UpgradeStore:
        return self.target

    def reference_database_exists(self, _database: str) -> bool:
        return False

    def create_reference_database(self, _database: str) -> None:
        self.events.append("create-reference")

    def control_store_for(self, _database: str) -> UpgradeStore:
        return self.reference

    def drop_reference_database(self, _database: str) -> None:
        self.events.append("drop-reference")

    def reconcile_control_roles(self) -> None:
        self.events.append("reconcile-roles")

    @contextmanager
    def maintenance_window(
        self,
        *,
        graph_databases: tuple[str, ...],
    ) -> Iterator[None]:
        assert graph_databases == self.graph_databases
        self.events.append("maintenance-enter")
        try:
            yield
        finally:
            self.events.append("maintenance-exit")


@dataclass(frozen=True)
class BackupPlanStub:
    backup_path: Path


@dataclass(frozen=True)
class BackupResultStub:
    plan: BackupPlanStub


@dataclass(frozen=True)
class BackupInspectionStub:
    checksum_verified: bool
    dump_summaries: tuple[object, ...]
    manifest: Mapping[str, object]


def verified_backup(
    tmp_path: Path,
) -> tuple[BackupResultStub, BackupInspectionStub]:
    return (
        BackupResultStub(BackupPlanStub(tmp_path / "verified-backup")),
        BackupInspectionStub(
            checksum_verified=True,
            dump_summaries=(object(),),
            manifest={"restore_supported": True},
        ),
    )


def require_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"expected mapping, got {type(value).__name__}")
    return value


def require_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise AssertionError(f"expected list, got {type(value).__name__}")
    return value


def require_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected dict, got {type(value).__name__}")
    return value


def statement_text(statement: str | sql.Composable) -> str:
    return statement if isinstance(statement, str) else statement.as_string()


__all__ = [
    "BackupInspectionStub",
    "BackupResultStub",
    "BareAuthority",
    "CaptureConnection",
    "CustomPageClient",
    "FakeAuthority",
    "FakeCoordinatorClient",
    "ItemClient",
    "OwnedMaintenanceAuthority",
    "UpgradeAuthority",
    "WindowAuthority",
    "WindowEvent",
    "fixed_client_factory",
    "require_list",
    "require_dict",
    "require_mapping",
    "statement_text",
    "verified_backup",
]
