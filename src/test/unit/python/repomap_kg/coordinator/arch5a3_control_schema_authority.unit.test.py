from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_kg.coordinator._control_schema import (
    control_schema_initialization_sql,
    control_schema_ledger_bootstrap_sql,
    discover_control_migrations,
)
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    upgrade_coordinator_control,
)
from repomap_kg.runtime.backup_commands import validate_database_name
from repomap_kg.runtime.schema_manifest import schema_manifest_sql


def _migration_root(tmp_path: Path) -> Path:
    root = tmp_path / "coordinator-rdbms"
    migrations = root / "2026"
    migrations.mkdir(parents=True)
    (root / "changelog.yaml").write_text(
        "databaseChangeLog:\n"
        "  - includeAll:\n"
        "      path: 2026\n"
        "      relativeToChangelogFile: true\n",
        encoding="utf-8",
    )
    (migrations / "01-control.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:control-001\n"
        "CREATE TABLE jobs(job_id TEXT PRIMARY KEY);\n",
        encoding="utf-8",
    )
    return root


def test_arch5a3_control_catalog_and_fresh_transaction_are_exact(
    tmp_path: Path,
) -> None:
    root = _migration_root(tmp_path)
    migrations = discover_control_migrations(root)
    script = control_schema_initialization_sql(root)

    assert len(migrations) == 1
    assert migrations[0].ordinal == 1
    assert migrations[0].changeset_id == "test:control-001"
    assert migrations[0].relative_path == "2026/01-control.sql"
    assert len(migrations[0].checksum) == 64
    assert script.startswith("CREATE TABLE repomap_control_schema_migrations")
    assert "CREATE TABLE jobs" in script
    assert script.count("INSERT INTO repomap_control_schema_migrations") == 1


def test_arch5a3_control_ledger_bootstrap_does_not_replay_historical_ddl(
    tmp_path: Path,
) -> None:
    script = control_schema_ledger_bootstrap_sql(_migration_root(tmp_path))

    assert script.startswith("CREATE TABLE repomap_control_schema_migrations")
    assert "INSERT INTO repomap_control_schema_migrations" in script
    assert "CREATE TABLE jobs" not in script


class _TargetStore:
    def __init__(self, events: list[str], *, status: str = "preledger") -> None:
        self.events = events
        self.status = status

    def schema_readiness(self):
        return SimpleNamespace(status=SimpleNamespace(value=self.status))

    def adopt_preledger_schema(self, **kwargs) -> None:
        self.events.append("adopt-target")
        assert kwargs == {
            "expected_manifest": ("exact-control-schema",),
            "backup_verified": True,
        }

    def check_schema_version(self) -> int:
        return 1


class _ReferenceStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def initialize_schema(self) -> None:
        self.events.append("initialize-reference")

    def schema_manifest(self) -> tuple[str, ...]:
        self.events.append("manifest-reference")
        return ("exact-control-schema",)


class _Authority:
    database_name = "repomap_control"
    graph_databases = ("graph-b", "graph-a")

    def __init__(self, events: list[str], *, status: str = "preledger") -> None:
        self.events = events
        self.target = _TargetStore(events, status=status)
        self.reference = _ReferenceStore(events)

    def database_exists(self) -> bool:
        return True

    def control_store(self):
        return self.target

    def reference_database_exists(self, database: str) -> bool:
        return False

    def create_reference_database(self, database: str) -> None:
        self.events.append("create-reference")

    def control_store_for(self, database: str):
        return self.reference

    def drop_reference_database(self, database: str) -> None:
        self.events.append("drop-reference")

    @contextmanager
    def maintenance_window(self, *, graph_databases):
        assert graph_databases == self.graph_databases
        self.events.append("maintenance-enter")
        try:
            yield
        finally:
            self.events.append("maintenance-exit")


def test_arch5a3_control_upgrade_is_backup_first_and_cleans_reference(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    authority = _Authority(events)
    backup = SimpleNamespace(
        plan=SimpleNamespace(backup_path=tmp_path / "verified-backup")
    )
    inspection = SimpleNamespace(
        checksum_verified=True,
        dump_summaries=(object(),),
        manifest={"restore_supported": True},
    )

    def dump(*args, **kwargs):
        events.append("backup")
        return backup

    def inspect(*args, **kwargs):
        events.append("verify-backup")
        return inspection

    result = upgrade_coordinator_control(
        tmp_path,
        backup_first=True,
        confirmed=True,
        timestamp="20260716T130000Z",
        authority_factory=lambda home: authority,
        dump_function=dump,
        inspect_function=inspect,
    )

    assert result["result"] == "ready"
    assert result["backup_verified"] is True
    assert result["rollback_available"] is True
    assert events.index("maintenance-enter") < events.index("backup")
    assert events.index("verify-backup") < events.index("adopt-target")
    assert events[-2:] == ["drop-reference", "maintenance-exit"]


def test_arch5a3_control_upgrade_rejects_invalid_backup_before_reference(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    authority = _Authority(events)
    backup = SimpleNamespace(
        plan=SimpleNamespace(backup_path=tmp_path / "invalid-backup")
    )
    inspection = SimpleNamespace(
        checksum_verified=False,
        dump_summaries=(),
        manifest={"restore_supported": False},
    )

    with pytest.raises(CoordinatorControlError, match="upgrade_failed"):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=True,
            confirmed=True,
            timestamp="20260716T130000Z",
            authority_factory=lambda home: authority,
            dump_function=lambda *args, **kwargs: backup,
            inspect_function=lambda *args, **kwargs: inspection,
        )

    assert events == ["maintenance-enter", "maintenance-exit"]


def test_arch5a3_control_upgrade_cleans_reference_after_adoption_failure(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    authority = _Authority(events)
    backup = SimpleNamespace(
        plan=SimpleNamespace(backup_path=tmp_path / "verified-backup")
    )
    inspection = SimpleNamespace(
        checksum_verified=True,
        dump_summaries=(object(),),
        manifest={"restore_supported": True},
    )

    def fail_adoption(**kwargs) -> None:
        events.append("adopt-target")
        raise RuntimeError("synthetic adoption failure")

    setattr(authority.target, "adopt_preledger_schema", fail_adoption)
    with pytest.raises(CoordinatorControlError, match="upgrade_failed"):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=True,
            confirmed=True,
            timestamp="20260716T130000Z",
            authority_factory=lambda home: authority,
            dump_function=lambda *args, **kwargs: backup,
            inspect_function=lambda *args, **kwargs: inspection,
        )

    assert events[-3:] == [
        "adopt-target",
        "drop-reference",
        "maintenance-exit",
    ]


def test_arch5a3_control_upgrade_rejects_managed_target_before_backup(
    tmp_path: Path,
) -> None:
    authority = _Authority([], status="current")

    with pytest.raises(CoordinatorControlError, match="upgrade_failed"):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=True,
            confirmed=True,
            authority_factory=lambda home: authority,
            dump_function=lambda *args, **kwargs: pytest.fail("backup created"),
        )


def test_schema_manifest_builder_requires_explicit_safe_exclusions() -> None:
    sql = schema_manifest_sql(excluded_relations=("control_ledger",))

    assert sql.count("NOT IN ('control_ledger')") == 6
    with pytest.raises(ValueError, match="safe relation names"):
        schema_manifest_sql(excluded_relations=())
    with pytest.raises(ValueError, match="safe relation names"):
        schema_manifest_sql(excluded_relations=("unsafe-name",))


def test_control_backup_validation_accepts_resolved_database_syntax() -> None:
    validate_database_name("synthetic-graph_control")


@pytest.mark.parametrize(
    ("backup_first", "confirmed", "dry_run", "result"),
    [
        (False, True, False, "backup_first_required"),
        (True, False, False, "confirmation_required"),
        (True, False, True, "planned"),
    ],
)
def test_arch5a3_control_upgrade_guards_precede_authority_access(
    tmp_path: Path,
    backup_first: bool,
    confirmed: bool,
    dry_run: bool,
    result: str,
) -> None:
    if dry_run:
        payload = upgrade_coordinator_control(
            tmp_path,
            backup_first=backup_first,
            confirmed=confirmed,
            dry_run=True,
            authority_factory=lambda home: pytest.fail("authority accessed"),
        )
        assert payload["result"] == result
        return
    with pytest.raises(CoordinatorControlError, match=result):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=backup_first,
            confirmed=confirmed,
            authority_factory=lambda home: pytest.fail("authority accessed"),
        )
