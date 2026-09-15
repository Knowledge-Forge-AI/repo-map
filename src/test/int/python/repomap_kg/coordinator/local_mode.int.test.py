import os
from pathlib import Path

import psycopg
import pytest

from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.job_control import (
    coordinator_job_status,
    coordinator_health,
    list_coordinator_jobs,
    wait_for_coordinator_job,
)
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    run_coordinator_refresh,
    start_configured_coordinator,
)
from repomap_kg.coordinator.local_lifecycle import initialize_coordinator_control
from repomap_kg.runtime.database_roles import (
    read_role_secrets,
    render_database_role_sql,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_explicit_local_mode_launches_and_replays_configured_refresh(
    monkeypatch, tmp_path
):
    require_postgres_binaries()
    with short_test_directory("async9-", "coordinator/coordinator.sock") as directory:
        home = Path(directory)
        repository = home / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Configured\n", encoding="utf-8")
        # ``start_configured_coordinator`` discovers psql from PATH; state the
        # client authority here rather than inheriting the host's packaging.
        authority = controlled_psql_copy(tmp_path).parent
        monkeypatch.setenv("PATH", f"{authority}{os.pathsep}{os.environ['PATH']}")
        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            (home / "configured.rp.toml").write_text(
                _configured_ops_text(postgres, repository), encoding="utf-8"
            )
            monkeypatch.setenv("ASYNC9_TEST_PASSWORD", postgres.password)
            with pytest.raises(CoordinatorModeError, match="coordinator_start_failed"):
                start_configured_coordinator(home)
            assert not (home / "coordinator").exists()

            initialized = initialize_coordinator_control(home)
            assert initialized["database_created"] is True
            role_sql = render_database_role_sql(
                database=postgres.database,
                owner_role=postgres.user,
                database_kind="graph",
                secrets=read_role_secrets(home / "runtime" / ".env"),
            )
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            ) as connection:
                connection.execute(role_sql)
            runtime = start_configured_coordinator(home)
            try:
                health = coordinator_health(home)
                assert health["result"] == "ready"
                health_payload = health["health"]
                assert isinstance(health_payload, dict)
                polling_payload = health_payload["polling"]
                assert isinstance(polling_payload, dict)
                assert health_payload["health_schema_version"] == 1
                assert polling_payload["status"] == "running"
                first = run_coordinator_refresh(
                    home,
                    "configured-refresh",
                    "async9-manual-refresh",
                    wait_timeout_seconds=15,
                )
                replay = run_coordinator_refresh(
                    home,
                    "configured-refresh",
                    "async9-manual-refresh",
                    wait_timeout_seconds=15,
                )
                first_job = first["job"]
                assert isinstance(first_job, dict)
                first_job_id = first_job["job_id"]
                assert isinstance(first_job_id, str)
                resumed_status = coordinator_job_status(home, first_job_id)
                resumed_wait = wait_for_coordinator_job(
                    home,
                    first_job_id,
                    wait_timeout_seconds=15,
                )
                recent = list_coordinator_jobs(
                    home, limit=1, graph_id="configured-refresh"
                )
            finally:
                runtime.stop()

            assert first["result"] == "success"
            assert first["replayed"] is False
            assert replay["result"] == "success"
            assert replay["replayed"] is True
            replay_job = replay["job"]
            assert isinstance(replay_job, dict)
            assert replay_job["job_id"] == first_job_id
            resumed_status_job = resumed_status["job"]
            assert isinstance(resumed_status_job, dict)
            assert resumed_status_job["state"] == "succeeded"
            assert resumed_wait["result"] == "success"
            resumed_wait_job = resumed_wait["job"]
            assert isinstance(resumed_wait_job, dict)
            assert resumed_wait_job["job_id"] == first_job_id
            recent_jobs = recent["jobs"]
            assert isinstance(recent_jobs, list)
            first_recent_job = recent_jobs[0]
            assert isinstance(first_recent_job, dict)
            assert first_recent_job["job_id"] == first_job_id
            assert not (home / "coordinator" / "coordinator.sock").exists()
            assert not (home / "coordinator" / "coordinator.token").exists()
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            ) as graph_connection:
                row = graph_connection.execute(
                    "SELECT count(*) FROM runs WHERE publication_job_id = %s",
                    (first_job_id,),
                ).fetchone()
                assert row is not None
                count = row[0]
            assert count == 1


def _configured_ops_text(postgres, repository: Path) -> str:
    return f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "ASYNC9_TEST_PASSWORD"

[[graphs]]
id = "configured-refresh"
name = "Configured Refresh"
root_path = "{repository}"
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
'''
