from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    coordinator_control_status,
    initialize_coordinator_control,
)
from repomap_kg.coordinator.refresh_adapter import (
    build_refresh_worker_runner,
)
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import short_test_directory


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


def test_control_lifecycle_validates_config_and_credential_paths_where_maintained_entry_exists():
    require_postgres_binaries()
    with short_test_directory("arch5b-", "sec/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            home = root / "sec"
            home.mkdir(mode=0o700, exist_ok=True)
            repository = root / "repository"
            repository.mkdir()
            cred_path = home / "pgpass.pwd"

            missing_home = root / "absent-config"
            with pytest.raises(CoordinatorControlError, match="coordinator_control_status_failed"):
                coordinator_control_status(missing_home)
            with pytest.raises(CoordinatorControlError, match="coordinator_control_init_failed"):
                initialize_coordinator_control(missing_home)

            config_file = home / "configured.rp.toml"
            config_file.write_text(
                f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.host}"
port = {postgres.port}
database = "arch5b-sec"
user = "{postgres.user}"
password_file = "pgpass.pwd"

[[graphs]]
id = "maintained-graph"
name = "Maintained Graph"
root_path = "{repository}"
repository_name = "maintained"
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
            with pytest.raises(CoordinatorControlError, match="coordinator_control_init_failed"):
                initialize_coordinator_control(home)

            cred_path.write_text(postgres.password, encoding="utf-8")
            cred_path.chmod(0o666)
            with pytest.raises(CoordinatorControlError, match="coordinator_control_init_failed"):
                initialize_coordinator_control(home)

            cred_path.chmod(0o600)
            status_before = coordinator_control_status(home)
            assert status_before["database_available"] is False
            first = initialize_coordinator_control(home)
            assert first["result"] == "ready" and first["database_created"] is True
            status_after = coordinator_control_status(home)
            assert status_after["database_available"] is True
            assert status_after["schema_version"] == 1


def _configured_refresh_text(
    postgres, repository: Path, binding_root: Path
) -> str:
    binding_id = graph_source_binding_id("configured-refresh", "root")
    return f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.host}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "ARCH5B_REFRESH_PASSWORD"

[[graphs]]
id = "configured-refresh"
name = "Configured Refresh"
enabled = true
mcp_visible = false
refresh_policy = "manual"

[[graphs.source_bindings]]
schema_version = 1
binding_id = "{binding_id}"
source_definition_id = "src1:root"
alias = "root"
revision = 1
kind = "folder"
root_path = "{binding_root}"
repository_name = "configured-refresh"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"
input_name = "root"
exclude_paths = []

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
'''


def _refresh_request(suffix: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "configured-refresh",
        "request_id": f"arch5b-{suffix}",
        "idempotency_key": f"arch5b-key-{suffix}",
        "priority": "manual",
        "operation_options": {"reason": "arch5b-generation-fence"},
    }


def test_configured_refresh_adapter_refuses_generation_drift_and_missing_source(
    monkeypatch,
):
    require_postgres_binaries()
    with short_test_directory("arch5b-", "adapter/repository/entry.py") as directory:
        root = Path(directory)
        repository = root / "adapter" / "repository"
        repository.mkdir(parents=True)
        (repository / "entry.py").write_text("print('v1')\n", encoding="utf-8")
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ARCH5B_REFRESH_PASSWORD", postgres.password)
            config_path = root / "configured.rp.toml"
            config_path.write_text(
                _configured_refresh_text(postgres, repository, repository),
                encoding="utf-8",
            )
            resolver = ConfiguredRefreshResolver(
                config_path, Path(postgres.psql_command)
            )
            store = ControlStore(
                lambda: psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=postgres.database,
                    password=postgres.password,
                )
            )
            store.initialize_schema()
            runner = build_refresh_worker_runner(
                resolver.resolve_authority, root, DEFAULT_LIMITS
            )
            coordinator = SyntheticCoordinator(
                store,
                "coord-arch5b",
                runner,
                singleton_ttl=timedelta(seconds=30),
            )
            first = store.submit(resolver.resolve_request(_refresh_request("drift")))
            (repository / "entry.py").write_text("print('v2')\n", encoding="utf-8")
            coordinator.startup(lambda: None)
            try:
                assert coordinator.run_once() == "failed"
                drifted = store.status(first.job_id)
                assert (
                    drifted.state,
                    drifted.publication_state,
                    drifted.error_category,
                ) == ("failed", "not_started", "generation_changed")

                second = store.submit(
                    resolver.resolve_request(_refresh_request("missing"))
                )
                missing = root / "missing-source"
                config_path.write_text(
                    _configured_refresh_text(postgres, repository, missing),
                    encoding="utf-8",
                )
                assert coordinator.run_once() == "queued"
                unavailable = store.status(second.job_id)
                assert (
                    unavailable.state,
                    unavailable.publication_state,
                    unavailable.error_category,
                ) == ("queued", "not_started", "source_unavailable")
                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=postgres.database,
                    password=postgres.password,
                ) as connection:
                    assert connection.execute(
                        "SELECT result_category, publication_state, is_current "
                        "FROM job_attempts WHERE job_id = %s AND attempt = 1",
                        (second.job_id,),
                    ).fetchone() == ("source_unavailable", "not_started", False)
            finally:
                coordinator.shutdown()
            assert not tuple(root.glob("refresh-*.json"))
