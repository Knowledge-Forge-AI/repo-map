from pathlib import Path

import psycopg
import pytest

from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    initialize_coordinator_control,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


class _FailingOnceStore:
    def __init__(self, store, authority):
        self._store = store
        self._authority = authority

    def initialize_schema(self):
        if self._authority.fail_once:
            self._authority.fail_once = False
            raise ControlSchemaError("synthetic control provision failure")
        self._store.initialize_schema()

    def check_schema_version(self):
        return self._store.check_schema_version()


class _FailingOnceAuthority(LocalControlAuthority):
    def __init__(self, repo_map_home):
        super().__init__(repo_map_home)
        self.fail_once = True

    def control_store(self):
        return _FailingOnceStore(super().control_store(), self)


def test_control_provision_failure_removes_target_and_retry_is_idempotent(
    monkeypatch,
):
    require_postgres_binaries()
    with short_test_directory("arch5b-", "recovery/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ARCH5B_TEST_PASSWORD", postgres.password)
            home = _config_home(root / "recovery", postgres, "arch5b-recovery")
            authority = _FailingOnceAuthority(home)

            with pytest.raises(
                CoordinatorControlError,
                match="coordinator_control_init_failed",
            ):
                initialize_coordinator_control(
                    home,
                    authority_factory=lambda _home: authority,
                )

            assert authority.database_exists() is False
            first = initialize_coordinator_control(
                home,
                authority_factory=lambda _home: authority,
            )
            replay = initialize_coordinator_control(
                home,
                authority_factory=lambda _home: authority,
            )
            assert first["database_created"] is True
            assert replay["database_created"] is False
            assert replay["schema_version"] == 1


def test_control_init_does_not_adopt_preexisting_empty_database(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("arch5b-", "recovery/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ARCH5B_TEST_PASSWORD", postgres.password)
            home = _config_home(root / "empty", postgres, "arch5b-empty")
            authority = LocalControlAuthority(home)
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
                autocommit=True,
            ) as bootstrap:
                bootstrap.execute('CREATE DATABASE "arch5b-empty_control"')

            with pytest.raises(
                CoordinatorControlError,
                match="coordinator_control_init_failed",
            ):
                initialize_coordinator_control(home)

            assert authority.database_exists() is True
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname="arch5b-empty_control",
                password=postgres.password,
            ) as empty:
                tables = empty.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                ).fetchall()
            assert tables == []


def _config_home(path: Path, postgres, graph_database: str) -> Path:
    path.mkdir(mode=0o700)
    (path / "configured.rp.toml").write_text(
        f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{graph_database}"
user = "{postgres.user}"
password_env = "ARCH5B_TEST_PASSWORD"

[[graphs]]
id = "configured-refresh"
name = "Configured Refresh"
root_path = "/placeholder/repository"
repository_name = "configured-refresh"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
''',
        encoding="utf-8",
    )
    return path
