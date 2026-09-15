from pathlib import Path

import psycopg
import pytest

from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    coordinator_control_status,
    initialize_coordinator_control,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_explicit_control_lifecycle_creates_replays_and_rejects_incompatible_state(
    monkeypatch,
):
    require_postgres_binaries()
    with short_test_directory("async10-", "incompatible/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            ready_home = _config_home(root / "ready", postgres, "async10-ready")

            absent = coordinator_control_status(ready_home)
            assert absent["result"] == "unavailable"
            assert absent["database_available"] is False

            first = initialize_coordinator_control(ready_home)
            replay = initialize_coordinator_control(ready_home)
            ready = coordinator_control_status(ready_home)
            assert first == {
                "command": "coordinator-control-init",
                "result": "ready",
                "database_created": True,
                "schema_version": 1,
            }
            assert replay["database_created"] is False
            assert ready["result"] == "ready"
            assert ready["schema_compatible"] is True
            assert ready["schema_version"] == 1

            incompatible_home = _config_home(
                root / "incompatible", postgres, "synthetic-graph"
            )
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
                autocommit=True,
            ) as bootstrap:
                bootstrap.execute('CREATE DATABASE "synthetic-graph_control"')
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname="synthetic-graph_control",
                password=postgres.password,
            ) as incompatible:
                incompatible.execute("CREATE TABLE unexpected(id integer)")

            status = coordinator_control_status(incompatible_home)
            assert status["result"] == "incompatible"
            assert status["database_available"] is True
            assert status["schema_compatible"] is False
            with pytest.raises(
                CoordinatorControlError,
                match="coordinator_control_init_failed",
            ):
                initialize_coordinator_control(incompatible_home)


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
password_env = "ASYNC10_TEST_PASSWORD"

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
