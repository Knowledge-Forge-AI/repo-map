import subprocess
import tempfile
from pathlib import Path

import pytest

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    initialize_coordinator_control,
)
from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    init_database_from_dump,
    init_database_from_source,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_kg.storage import discover_migrations


class _GraphProvisionRunner:
    def __init__(self, identity, *, fail_operation_once: str | None = None):
        self.identity = identity
        self.fail_operation_once = fail_operation_once
        self.database_exists = False
        self.drop_count = 0
        self.operation_count = 0
        self.ledger_ready = True
        self.fail_cleanup = False

    def __call__(self, command, **kwargs):
        command = list(command)
        joined = " ".join(command)
        if command[:2] == ["docker", "inspect"]:
            return LocalDbBackupUnitTestCase.owned_container_result(
                self.identity, command
            )
        if "SELECT COUNT(*) FROM pg_database" in joined:
            value = b"1\n" if self.database_exists else b"0\n"
            return subprocess.CompletedProcess(command, 0, stdout=value, stderr=b"")
        if "CREATE DATABASE" in joined:
            self.database_exists = True
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        if "DROP DATABASE" in joined:
            if self.fail_cleanup:
                return subprocess.CompletedProcess(
                    command, 1, stdout=b"", stderr=b"private cleanup detail"
                )
            self.database_exists = False
            self.drop_count += 1
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        if "to_regclass('public.repomap_schema_migrations')" in joined:
            value = b"t\n" if self.ledger_ready else b"f\n"
            return subprocess.CompletedProcess(command, 0, stdout=value, stderr=b"")
        if "FROM repomap_schema_migrations ORDER BY ordinal" in joined:
            rows = "\n".join(
                "\t".join(
                    (
                        str(migration.ordinal),
                        migration.changeset_id,
                        migration.relative_path,
                        migration.checksum,
                    )
                )
                for migration in discover_migrations()
            )
            return subprocess.CompletedProcess(
                command, 0, stdout=(rows + "\n").encode(), stderr=b""
            )
        operation = "dump" if "/usr/bin/pg_restore" in command else "source"
        if operation in {"source", "dump"}:
            self.operation_count += 1
            if self.fail_operation_once == operation:
                self.fail_operation_once = None
                return subprocess.CompletedProcess(
                    command, 1, stdout=b"", stderr=b"bounded provision failure"
                )
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        raise AssertionError(command)


def test_source_provision_failure_cleans_owned_target_and_retry_succeeds():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "repo-map-home"
        setup_local_runtime(home)
        runner = _GraphProvisionRunner(
            LocalRuntimeIdentity.from_home(home), fail_operation_once="source"
        )

        with pytest.raises(LocalDbBackupError):
            init_database_from_source(
                home,
                database="repomap",
                command_runner=runner,
            )

        assert runner.database_exists is False
        assert runner.drop_count == 1
        result = init_database_from_source(
            home,
            database="repomap",
            command_runner=runner,
        )
        assert result.to_jsonable()["schema_ready"] is True
        assert runner.database_exists is True


def test_dump_restore_requires_ready_schema_and_cleans_unready_owned_target():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "repo-map-home"
        setup_local_runtime(home)
        identity = LocalRuntimeIdentity.from_home(home)
        backup = LocalDbBackupUnitTestCase.write_backup_fixture(
            home, identity.home_hash, "repomap"
        )
        runner = _GraphProvisionRunner(identity)
        runner.ledger_ready = False

        with pytest.raises(LocalDbBackupError):
            init_database_from_dump(
                home,
                database="repomap",
                backup=backup,
                command_runner=runner,
            )

        assert runner.database_exists is False
        assert runner.drop_count == 1


def test_dump_restore_failure_cleans_owned_target_and_retry_succeeds():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "repo-map-home"
        setup_local_runtime(home)
        identity = LocalRuntimeIdentity.from_home(home)
        backup = LocalDbBackupUnitTestCase.write_backup_fixture(
            home, identity.home_hash, "repomap"
        )
        runner = _GraphProvisionRunner(identity, fail_operation_once="dump")

        with pytest.raises(LocalDbBackupError):
            init_database_from_dump(
                home,
                database="repomap",
                backup=backup,
                command_runner=runner,
            )

        assert runner.database_exists is False
        result = init_database_from_dump(
            home,
            database="repomap",
            backup=backup,
            command_runner=runner,
        )
        assert result.to_jsonable()["schema_ready"] is True
        assert runner.database_exists is True


def test_cleanup_failure_reports_bounded_recovery_category():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "repo-map-home"
        setup_local_runtime(home)
        runner = _GraphProvisionRunner(
            LocalRuntimeIdentity.from_home(home), fail_operation_once="source"
        )
        runner.fail_cleanup = True

        with pytest.raises(LocalDbBackupError) as caught:
            init_database_from_source(
                home,
                database="repomap",
                command_runner=runner,
            )

        assert caught.value.diagnostics[0].code == "failed-target-cleanup-failed"
        assert "private cleanup detail" not in str(caught.value)


class _ControlStore:
    def __init__(self, authority):
        self.authority = authority

    def initialize_schema(self):
        self.authority.initialize_count += 1
        if self.authority.fail_initialization_once:
            self.authority.fail_initialization_once = False
            raise ControlSchemaError("synthetic initialization failure")
        self.authority.ready = True

    def check_schema_version(self):
        self.authority.check_count += 1
        if not self.authority.ready:
            raise ControlSchemaError("unrecognized control state")
        return 1


class _ControlAuthority:
    def __init__(self, *, exists=False, ready=False, fail_initialization_once=False):
        self.exists = exists
        self.ready = ready
        self.fail_initialization_once = fail_initialization_once
        self.create_count = 0
        self.drop_count = 0
        self.initialize_count = 0
        self.check_count = 0

    def database_exists(self):
        return self.exists

    def create_database(self):
        self.exists = True
        self.create_count += 1
        return True

    def drop_created_database(self):
        self.exists = False
        self.ready = False
        self.drop_count += 1

    def control_store(self):
        return _ControlStore(self)


def test_control_failure_cleans_owned_target_and_retry_succeeds():
    authority = _ControlAuthority(fail_initialization_once=True)

    with pytest.raises(CoordinatorControlError):
        initialize_coordinator_control(
            "/placeholder/home", authority_factory=lambda _home: authority
        )

    assert authority.exists is False
    assert authority.drop_count == 1
    result = initialize_coordinator_control(
        "/placeholder/home", authority_factory=lambda _home: authority
    )
    assert result["result"] == "ready"
    assert result["database_created"] is True


def test_control_init_refuses_preexisting_empty_unrecognized_target():
    authority = _ControlAuthority(exists=True, ready=False)

    with pytest.raises(CoordinatorControlError):
        initialize_coordinator_control(
            "/placeholder/home", authority_factory=lambda _home: authority
        )

    assert authority.initialize_count == 0
    assert authority.drop_count == 0
