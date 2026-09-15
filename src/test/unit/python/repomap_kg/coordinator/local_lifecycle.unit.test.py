from pathlib import Path

import pytest

from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    coordinator_control_status,
    derived_control_database,
    initialize_coordinator_control,
    upgrade_coordinator_control,
)
from repomap_test_support.coordinator_control_fixtures import (
    BackupInspectionStub,
    BackupResultStub,
    BareAuthority,
    CaptureConnection,
    FakeAuthority,
    UpgradeAuthority,
    statement_text,
    verified_backup,
)


def test_control_database_creation_declares_template_encoding_and_collation():
    connection = CaptureConnection()
    authority = BareAuthority(connection)

    assert authority.create_database() is True
    assert len(connection.statements) == 1
    assert statement_text(connection.statements[0]) == (
        'CREATE DATABASE "repomap_control" WITH TEMPLATE template0 '
        "ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
    )


def test_control_status_reports_absent_without_mutation():
    authority = FakeAuthority()
    result = coordinator_control_status(
        "/placeholder/home", authority_factory=lambda _home: authority
    )
    assert result == {
        "command": "coordinator-control-status",
        "result": "unavailable",
        "database_available": False,
        "schema_compatible": None,
        "schema_version": None,
    }
    assert authority.created == authority.initialized == authority.checked == 0


def test_control_status_reports_ready_or_incompatible_without_private_detail():
    ready = coordinator_control_status(
        "/placeholder/home", authority_factory=lambda _home: FakeAuthority(exists=True)
    )
    assert ready["result"] == "ready"
    assert ready["schema_version"] == 1

    incompatible = coordinator_control_status(
        "/placeholder/home",
        authority_factory=lambda _home: FakeAuthority(
            exists=True, schema_error=True
        ),
    )
    assert incompatible == {
        "command": "coordinator-control-status",
        "result": "incompatible",
        "database_available": True,
        "schema_compatible": False,
        "schema_version": None,
    }
    assert "private" not in repr(incompatible)


def test_control_init_creates_only_when_absent_and_is_idempotent():
    authority = FakeAuthority()
    first = initialize_coordinator_control(
        "/placeholder/home", authority_factory=lambda _home: authority
    )
    replay = initialize_coordinator_control(
        "/placeholder/home", authority_factory=lambda _home: authority
    )
    assert first == {
        "command": "coordinator-control-init",
        "result": "ready",
        "database_created": True,
        "schema_version": 1,
    }
    assert replay["database_created"] is False
    assert authority.created == 1
    assert authority.initialized == 1
    assert authority.checked == 2


def test_control_init_bounds_schema_failure():
    authority = FakeAuthority(initialize_error=True)
    with pytest.raises(CoordinatorControlError, match="coordinator_control_init_failed") as error:
        initialize_coordinator_control(
            "/placeholder/home", authority_factory=lambda _home: authority
        )
    assert "private initialize detail" not in str(error.value)
    assert authority.dropped == 1


def test_derived_control_database_preserves_namespace_and_refuses_invalid_input():
    assert derived_control_database("graph") == "graph_control"
    with pytest.raises(
        CoordinatorControlError,
        match="coordinator_control_database_invalid",
    ):
        derived_control_database("graph/with-path")


def test_control_init_handles_existing_database_and_cleanup_failure():
    existing = FakeAuthority(exists=True)
    result = initialize_coordinator_control(
        "/placeholder/home", authority_factory=lambda _home: existing
    )
    assert result["database_created"] is False
    assert existing.created == existing.initialized == existing.dropped == 0
    assert existing.reconciled == 1

    cleanup_failure = FakeAuthority(initialize_error=True, drop_error=True)
    with pytest.raises(
        CoordinatorControlError,
        match="coordinator_control_init_cleanup_failed",
    ):
        initialize_coordinator_control(
            "/placeholder/home", authority_factory=lambda _home: cleanup_failure
        )
    assert cleanup_failure.dropped == 1


def test_control_status_preserves_declared_errors_and_bounds_unexpected_errors():
    declared = CoordinatorControlError("declared-control-error")
    with pytest.raises(CoordinatorControlError, match="declared-control-error"):
        coordinator_control_status(
            "/placeholder/home",
            authority_factory=lambda _home: (_ for _ in ()).throw(declared),
        )

    with pytest.raises(
        CoordinatorControlError,
        match="coordinator_control_status_failed",
    ):
        coordinator_control_status(
            "/placeholder/home",
            authority_factory=lambda _home: (_ for _ in ()).throw(
                RuntimeError("private status detail")
            ),
        )


def test_control_upgrade_verifies_backup_before_reference_and_reconciles_roles(
    tmp_path: Path,
):
    events: list[str] = []
    authority = UpgradeAuthority(events)
    backup, inspection = verified_backup(tmp_path)

    def dump_backup(
        repo_map_home: str | Path | None,
        *,
        database: str,
        reason: str | None = None,
        timestamp: str | None = None,
    ) -> BackupResultStub:
        del repo_map_home, database, reason, timestamp
        events.append("backup")
        return backup

    def inspect_backup(
        repo_map_home: str | Path | None,
        backup_id_or_path: str | Path,
    ) -> BackupInspectionStub:
        del repo_map_home, backup_id_or_path
        events.append("verify-backup")
        return inspection

    result = upgrade_coordinator_control(
        tmp_path,
        backup_first=True,
        confirmed=True,
        timestamp="20260716T130000Z",
        authority_factory=lambda home: authority,
        dump_function=dump_backup,
        inspect_function=inspect_backup,
    )

    assert result["result"] == "ready"
    assert result["schema_version"] == 1
    assert result["reference_cleaned"] is True
    assert events == [
        "maintenance-enter",
        "backup",
        "verify-backup",
        "create-reference",
        "initialize-reference",
        "manifest-reference",
        "adopt-target",
        "drop-reference",
        "reconcile-roles",
        "maintenance-exit",
    ]


def test_control_upgrade_rejects_bad_backup_and_cleans_reference_on_adoption_failure(
    tmp_path: Path,
):
    events: list[str] = []
    authority = UpgradeAuthority(events)
    backup, _inspection = verified_backup(tmp_path)
    invalid = BackupInspectionStub(
        checksum_verified=False,
        dump_summaries=(),
        manifest={"restore_supported": False},
    )

    def dump_backup(
        repo_map_home: str | Path | None,
        *,
        database: str,
        reason: str | None = None,
        timestamp: str | None = None,
    ) -> BackupResultStub:
        del repo_map_home, database, reason, timestamp
        return backup

    def inspect_invalid(
        repo_map_home: str | Path | None,
        backup_id_or_path: str | Path,
    ) -> BackupInspectionStub:
        del repo_map_home, backup_id_or_path
        return invalid

    with pytest.raises(CoordinatorControlError, match="upgrade_failed"):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=True,
            confirmed=True,
            authority_factory=lambda home: authority,
            dump_function=dump_backup,
            inspect_function=inspect_invalid,
        )
    assert events == ["maintenance-enter", "maintenance-exit"]

    events.clear()
    authority = UpgradeAuthority(events, fail_adoption=True)
    backup, inspection = verified_backup(tmp_path)

    def inspect_valid(
        repo_map_home: str | Path | None,
        backup_id_or_path: str | Path,
    ) -> BackupInspectionStub:
        del repo_map_home, backup_id_or_path
        return inspection

    with pytest.raises(CoordinatorControlError, match="upgrade_failed"):
        upgrade_coordinator_control(
            tmp_path,
            backup_first=True,
            confirmed=True,
            authority_factory=lambda home: authority,
            dump_function=dump_backup,
            inspect_function=inspect_valid,
        )
    assert events[-3:] == ["adopt-target", "drop-reference", "maintenance-exit"]
