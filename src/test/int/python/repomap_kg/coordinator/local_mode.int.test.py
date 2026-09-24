import os
from pathlib import Path
import re
import uuid

import psycopg
import pytest

from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.job_control import (
    coordinator_health,
    coordinator_job_status,
    format_coordinator_health_table,
    format_coordinator_job_table,
    format_coordinator_jobs_table,
    list_coordinator_jobs,
    wait_for_coordinator_job,
)
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    format_coordinator_refresh_table,
    run_coordinator_refresh,
    serve_configured_coordinator,
    start_configured_coordinator,
)
from repomap_kg.coordinator.local_lifecycle import (
    LocalControlAuthority,
    initialize_coordinator_control,
)
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
            graph_db = _sanitize_db_name(f"async9_mode_refresh_{uuid.uuid4().hex[:8]}")
            graph_postgres = postgres.create_database(graph_db)
            control_authority: LocalControlAuthority | None = None
            runtime = None
            try:
                apply_migrations(
                    default_rdbms_root(),
                    graph_postgres.psql_args,
                    psql_command=graph_postgres.psql_command,
                )
                (home / "configured.rp.toml").write_text(
                    _configured_ops_text(graph_postgres, repository), encoding="utf-8"
                )
                monkeypatch.setenv("ASYNC9_TEST_PASSWORD", postgres.password)
                with pytest.raises(CoordinatorModeError, match="coordinator_start_failed"):
                    start_configured_coordinator(home)
                assert not (home / "coordinator").exists()

                control_authority = LocalControlAuthority(home)
                assert not control_authority.database_exists()

                initialized = initialize_coordinator_control(home)
                assert initialized["result"] == "ready"
                assert initialized["database_created"] is True
                assert initialized["schema_version"] == 1

                reused = initialize_coordinator_control(home)
                assert reused["result"] == "ready"
                assert reused["database_created"] is False
                assert reused["schema_version"] == 1

                role_sql = render_database_role_sql(
                    database=graph_db,
                    owner_role=postgres.user,
                    database_kind="graph",
                    secrets=read_role_secrets(home / "runtime" / ".env"),
                )
                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=graph_db,
                    password=postgres.password,
                ) as connection:
                    connection.execute(role_sql)
                runtime = start_configured_coordinator(home)
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
                runtime.stop()
                runtime = None
                runtime = start_configured_coordinator(home)
                restarted_job = coordinator_job_status(home, first_job_id)["job"]
                assert isinstance(restarted_job, dict)
                assert (restarted_job["job_id"], restarted_job["state"]) == (first_job_id, "succeeded")
                runtime.stop()
                runtime = None
                assert not (home / "coordinator" / "coordinator.sock").exists()
                assert not (home / "coordinator" / "coordinator.token").exists()
                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=graph_db,
                    password=postgres.password,
                ) as graph_connection:
                    row = graph_connection.execute(
                        "SELECT count(*) FROM runs WHERE publication_job_id = %s",
                        (first_job_id,),
                    ).fetchone()
                    assert row is not None
                    count = row[0]
                assert count == 1

                # Rich semantic validations of table formatters
                refresh_table = format_coordinator_refresh_table(first)
                assert "RepoMap coordinator refresh result" in refresh_table
                assert "result | success" in refresh_table
                assert f"job_id | {first_job_id}" in refresh_table
                assert "graph_id | configured-refresh" in refresh_table

                health_table = format_coordinator_health_table(health)
                assert "RepoMap coordinator health" in health_table
                assert "health_schema_version | 1" in health_table
                assert "status | ready" in health_table
                assert "polling | running" in health_table

                job_table = format_coordinator_job_table(resumed_status)
                assert "RepoMap coordinator job" in job_table
                assert f"job_id | {first_job_id}" in job_table
                assert "state | succeeded" in job_table

                jobs_table = format_coordinator_jobs_table(recent)
                assert "RepoMap coordinator jobs" in jobs_table
                assert first_job_id in jobs_table
            finally:
                if runtime is not None:
                    runtime.stop()
                if control_authority is not None and control_authority.database_exists():
                    control_authority.drop_created_database()
                    assert not control_authority.database_exists()
                _drop_graph_database_with_termination(postgres, graph_db)


def test_local_mode_boundary_refusals_and_orderly_serve_lifecycle(
    monkeypatch, tmp_path
):
    import threading

    require_postgres_binaries()
    with short_test_directory("async9-serve-", "coordinator/coordinator.sock") as directory:
        home = Path(directory)
        repository = home / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Configured\n", encoding="utf-8")
        authority = controlled_psql_copy(tmp_path).parent
        monkeypatch.setenv("PATH", f"{authority}{os.pathsep}{os.environ['PATH']}")

        with temporary_postgres() as postgres:
            graph_db = _sanitize_db_name(f"async9_serve_{uuid.uuid4().hex[:8]}")
            graph_postgres = postgres.create_database(graph_db)
            control_authority: LocalControlAuthority | None = None
            try:
                apply_migrations(
                    default_rdbms_root(),
                    graph_postgres.psql_args,
                    psql_command=graph_postgres.psql_command,
                )
                (home / "configured.rp.toml").write_text(
                    _configured_ops_text(graph_postgres, repository), encoding="utf-8"
                )
                monkeypatch.setenv("ASYNC9_TEST_PASSWORD", postgres.password)
                control_authority = LocalControlAuthority(home)
                assert not control_authority.database_exists()
                first = initialize_coordinator_control(home)
                assert first["result"] == "ready"
                assert first["database_created"] is True
                assert first["schema_version"] == 1
                reuse = initialize_coordinator_control(home)
                assert reuse["result"] == "ready"
                assert reuse["database_created"] is False
                assert reuse["schema_version"] == 1

                role_sql = render_database_role_sql(
                    database=graph_db,
                    owner_role=postgres.user,
                    database_kind="graph",
                    secrets=read_role_secrets(home / "runtime" / ".env"),
                )
                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=graph_db,
                    password=postgres.password,
                ) as connection:
                    connection.execute(role_sql)

                # Parameter validation refusals
                with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
                    run_coordinator_refresh(
                        home, "configured-refresh", "key-1", wait_timeout_seconds=0
                    )
                with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
                    run_coordinator_refresh(
                        home, "configured-refresh", "key-1", wait_timeout_seconds=86_401
                    )
                with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
                    wait_for_coordinator_job(home, "job-any", wait_timeout_seconds=0)

                # Serve startup wait validation refusals
                with pytest.raises(CoordinatorModeError, match="coordinator_start_wait_invalid"):
                    serve_configured_coordinator(
                        home, lambda _: None, startup_wait_seconds=-1
                    )
                with pytest.raises(CoordinatorModeError, match="coordinator_start_wait_invalid"):
                    serve_configured_coordinator(
                        home, lambda _: None, startup_wait_seconds=301
                    )

                # Orderly serve_configured_coordinator lifecycle with stop_event
                stop_event = threading.Event()
                stop_event.set()
                ready_payloads: list[dict[str, object]] = []
                serve_configured_coordinator(
                    home,
                    ready_callback=lambda p: ready_payloads.append(dict(p)),
                    stop_event=stop_event,
                    startup_wait_seconds=5,
                )
                assert len(ready_payloads) == 1
                assert ready_payloads[0]["result"] == "ready"
                assert not (home / "coordinator" / "coordinator.sock").exists()
            finally:
                if control_authority is not None and control_authority.database_exists():
                    control_authority.drop_created_database()
                    assert not control_authority.database_exists()
                _drop_graph_database_with_termination(postgres, graph_db)


def _sanitize_db_name(raw: str, max_length: int = 55) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"db_{cleaned}"
    cleaned = cleaned[:max_length]
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,54}", cleaned)
    return cleaned


def _drop_graph_database_with_termination(postgres, database: str) -> None:
    postgres.psql_scalar(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{database}' AND pid <> pg_backend_pid();"
    )
    postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{database}";')
    absence = postgres.psql_scalar(
        f"SELECT count(*) FROM pg_database WHERE datname = '{database}';"
    )
    assert absence == "0"


def _configured_ops_text(postgres, repository: Path) -> str:
    return f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
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
