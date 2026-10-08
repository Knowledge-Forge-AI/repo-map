from pathlib import Path
import re
import uuid

import psycopg
import pytest

from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    coordinator_control_status,
    format_coordinator_control_table,
    initialize_coordinator_control,
    maintenance_activity_for_home,
    maintenance_window_for_coordinated_backup,
    maintenance_window_for_database_drop,
    maintenance_window_for_graph_upgrade,
    upgrade_coordinator_control,
)
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError
from repomap_test_support.cli_in_process import scrub_coverage_environment
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _sanitize_db_name(raw: str, max_length: int = 55) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"db_{cleaned}"
    cleaned = cleaned[:max_length]
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,54}", cleaned)
    return cleaned


def test_explicit_control_lifecycle_creates_replays_and_rejects_incompatible_state(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async10-", "incompatible/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            ready_db = _sanitize_db_name(f"async10_ready_{uuid.uuid4().hex[:8]}")
            ready_home = _config_home(root / "ready", postgres, ready_db)
            ready_authority = LocalControlAuthority(ready_home)

            inc_graph = _sanitize_db_name(f"synthetic_graph_{uuid.uuid4().hex[:8]}")
            incompatible_home = _config_home(
                root / "incompatible", postgres, inc_graph
            )
            inc_authority = LocalControlAuthority(incompatible_home)
            inc_control = inc_authority.database_name
            try:
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

                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=postgres.database,
                    password=postgres.password,
                    autocommit=True,
                ) as bootstrap:
                    bootstrap.execute(f'CREATE DATABASE "{inc_control}"')
                with psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=inc_control,
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
            finally:
                if ready_authority.database_exists():
                    ready_authority.drop_created_database()
                assert not ready_authority.database_exists()
                if inc_authority.database_exists():
                    inc_authority.drop_created_database()
                assert not inc_authority.database_exists()


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


def test_coordinator_maintenance_windows_and_activities(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async10-maint-", "ready/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            ready_home = _config_home(root / "ready", postgres, postgres.database)
            initialize_coordinator_control(ready_home)

            with maintenance_activity_for_home(ready_home):
                assert coordinator_control_status(ready_home)["schema_compatible"] is True

            # Graph upgrade window: excludes concurrent activity, allows recovery post-exit
            with maintenance_window_for_graph_upgrade(ready_home, postgres.database):
                with pytest.raises(MaintenanceUnavailableError, match="maintenance is active"):
                    with maintenance_activity_for_home(ready_home):
                        pytest.fail("graph upgrade maintenance admitted a concurrent activity")
            with maintenance_activity_for_home(ready_home):
                assert coordinator_control_status(ready_home)["schema_compatible"] is True

            with pytest.raises(
                MaintenanceUnavailableError,
                match="maintenance target is not an owned graph database",
            ):
                with maintenance_window_for_graph_upgrade(ready_home, "unowned_graph_db"):
                    pass

            # Coordinated backup window: excludes concurrent activity, allows recovery post-exit
            with maintenance_window_for_coordinated_backup(ready_home):
                with pytest.raises(MaintenanceUnavailableError, match="maintenance is active"):
                    with maintenance_activity_for_home(ready_home):
                        pytest.fail("coordinated backup admitted a concurrent activity")
            with maintenance_activity_for_home(ready_home):
                assert coordinator_control_status(ready_home)["schema_compatible"] is True

            # Drop window on control database: excludes concurrent activity, allows recovery post-exit
            with maintenance_window_for_database_drop(ready_home, f"{postgres.database}_control"):
                with pytest.raises(MaintenanceUnavailableError, match="maintenance is active"):
                    with maintenance_activity_for_home(ready_home):
                        pytest.fail("control drop maintenance admitted a concurrent activity")
            with maintenance_activity_for_home(ready_home):
                assert coordinator_control_status(ready_home)["schema_compatible"] is True

            # Drop window on graph database: excludes concurrent activity, allows recovery post-exit
            with maintenance_window_for_database_drop(ready_home, postgres.database):
                with pytest.raises(MaintenanceUnavailableError, match="maintenance is active"):
                    with maintenance_activity_for_home(ready_home):
                        pytest.fail("graph drop maintenance admitted a concurrent activity")
            with maintenance_activity_for_home(ready_home):
                assert coordinator_control_status(ready_home)["schema_compatible"] is True

            # Drop window on unowned database
            with pytest.raises(
                MaintenanceUnavailableError,
                match="maintenance target is not an owned database",
            ):
                with maintenance_window_for_database_drop(ready_home, "unowned_db"):
                    pass


def test_coordinator_control_upgrade_lifecycle_refusals_and_dry_run(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async10-upg-", "ready/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            ready_home = _config_home(root / "ready", postgres, "async10-ready")
            initialize_coordinator_control(ready_home)

            with pytest.raises(
                CoordinatorControlError,
                match="coordinator_control_backup_first_required",
            ):
                upgrade_coordinator_control(ready_home, backup_first=False)

            with pytest.raises(
                CoordinatorControlError,
                match="coordinator_control_upgrade_confirmation_required",
            ):
                upgrade_coordinator_control(
                    ready_home, backup_first=True, dry_run=False, confirmed=False
                )

            plan = upgrade_coordinator_control(ready_home, backup_first=True, dry_run=True)
            assert plan["command"] == "coordinator-control-upgrade"
            assert plan["result"] == "planned"
            assert plan["backup_verified"] is False
            assert plan["rollback_available"] is False
            assert plan["reference_cleaned"] is False
            assert isinstance(plan["planned_actions"], list)
            assert set(plan["planned_actions"]) == {
                "inspect-control-schema",
                "create-and-inspect-backup",
                "create-reference-database",
                "compare-schema-manifest",
                "bootstrap-control-ledger",
                "drop-reference-database",
            }
            assert len(plan["planned_actions"]) == 6
            formatted = format_coordinator_control_table(plan)
            assert "result | planned" in formatted


def test_coordinator_control_lifecycle_reuse_and_formatting(monkeypatch):
    require_postgres_binaries()

    with short_test_directory("async10-reuse-", "ready/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            graph_db = _sanitize_db_name(f"async10_reuse_{uuid.uuid4().hex[:8]}")
            ready_home = _config_home(root / "ready", postgres, graph_db)
            authority = LocalControlAuthority(ready_home)
            try:
                # Table formatting across unavailable status
                unavail = coordinator_control_status(ready_home)
                unavail_tbl = format_coordinator_control_table(unavail)
                assert "result | unavailable" in unavail_tbl
                assert "database_available | false" in unavail_tbl

                # Table formatting across first initialization
                first = initialize_coordinator_control(ready_home)
                assert first["result"] == "ready"
                assert first["database_created"] is True
                first_tbl = format_coordinator_control_table(first)
                assert "result | ready" in first_tbl
                assert "database_created | true" in first_tbl
                assert "schema_version | 1" in first_tbl

                # Table formatting across ready status
                ready_status = coordinator_control_status(ready_home)
                ready_tbl = format_coordinator_control_table(ready_status)
                assert "result | ready" in ready_tbl
                assert "database_available | true" in ready_tbl
                assert "schema_compatible | true" in ready_tbl
                assert "schema_version | 1" in ready_tbl

                # Re-initialization reuse: idempotent second call does not re-create database
                replay = initialize_coordinator_control(ready_home)
                assert replay["result"] == "ready"
                assert replay["database_created"] is False
                replay_tbl = format_coordinator_control_table(replay)
                assert "database_created | false" in replay_tbl
            finally:
                if authority.database_exists():
                    authority.drop_created_database()
                assert not authority.database_exists()


def test_coordinator_control_upgrade_rejections(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async10-rej-", "ready/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ASYNC10_TEST_PASSWORD", postgres.password)
            graph_db = _sanitize_db_name(f"async10_rej_{uuid.uuid4().hex[:8]}")
            ready_home = _config_home(root / "ready", postgres, graph_db)
            uninit_db = _sanitize_db_name(f"async10_uninit_{uuid.uuid4().hex[:8]}")
            uninit_home = _config_home(root / "uninit", postgres, uninit_db)
            authority = LocalControlAuthority(ready_home)
            try:
                initialize_coordinator_control(ready_home)

                # Executing upgrade on already-version-1 schema refuses (not preledger)
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(ready_home, backup_first=True, confirmed=True)

                # Executing upgrade on absent control database refuses
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(uninit_home, backup_first=True, confirmed=True)
            finally:
                if authority.database_exists():
                    authority.drop_created_database()
                assert not authority.database_exists()
                assert not LocalControlAuthority(uninit_home).database_exists()


@pytest.mark.parametrize("credential_authority", ["generated", "literal", "environment"])
def test_local_direct_route_control_lifecycle(tmp_path, monkeypatch, credential_authority):
    import json
    import os
    import subprocess
    import sys
    from psycopg import sql
    import repomap_kg
    from repomap_kg.runtime.local import setup_local_runtime
    home = tmp_path / "native-home"
    setup_local_runtime(home)
    assert home.stat().st_mode & 0o777 == 0o700
    values = dict(line.split("=", 1) for line in
                  (home / "runtime/.env").read_text().splitlines() if "=" in line)
    secret = values["REPOMAP_PG_PASSWORD"]
    if credential_authority != "generated":
        secret = "fixture-explicit\ncredential"
    with temporary_postgres() as postgres:
        role = "home_authority_" + uuid.uuid4().hex[:12]
        with psycopg.connect(host=postgres.host, port=postgres.port,
                              user=postgres.user, dbname=postgres.database,
                              password=postgres.password, autocommit=True) as bootstrap:
            bootstrap.execute(sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(secret)))
            path = home / "repomap.rpl.toml"
            path.write_text(path.read_text().replace(
                "direct_host_port_enabled = false", "direct_host_port_enabled = true"
            ).replace("host_port = 55432", f"host_port = {postgres.port}").replace(
                'user = "repomap"', f'user = "{role}"'
            ).replace('database = "repomap"', 'database = "native_route_fixture"'))
            for key in ("REPOMAP_PG_PASSWORD", "PGPASSWORD", "PGPASSFILE", "PGSERVICE"):
                monkeypatch.delenv(key, raising=False)
            if credential_authority == "literal":
                original = 'password_env = "REPOMAP_PG_PASSWORD"'
                path.write_text(path.read_text().replace(original, "password = " + json.dumps(secret)))
            elif credential_authority == "environment":
                monkeypatch.setenv("REPOMAP_PG_PASSWORD", secret)
            environment = scrub_coverage_environment(os.environ)
            environment["PYTHONPATH"] = str(Path(repomap_kg.__file__).parents[1])
            environment["PGPASSFILE"] = str(tmp_path / "absent-pgpass")
            def command(name):
                result = subprocess.run(
                    [sys.executable, "-m", "repomap_kg", "ops", name,
                     "--repo-map-home", str(home), "--json"],
                    env=environment, capture_output=True, text=True, timeout=60,
                )
                assert not any(v in result.stdout + result.stderr for k, v in values.items()
                               if "PASSWORD" in k and v)
                payload = json.loads(result.stdout)
                assert result.returncode == (1 if payload.get("result") == "unavailable" else 0)
                assert not result.stderr
                return payload
            authority = LocalControlAuthority(home)
            try:
                assert command("coordinator-control-status")["result"] == "unavailable"
                assert command("coordinator-control-init")["database_created"] is True
                assert command("coordinator-control-status")["result"] == "ready"
                assert command("coordinator-control-init")["database_created"] is False
            finally:
                if authority.database_exists():
                    authority.drop_created_database()
                bootstrap.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_custom_credential_does_not_use_generated_admin(tmp_path, monkeypatch):
    from repomap_kg.runtime.local import setup_local_runtime

    home = tmp_path / "custom-home"
    setup_local_runtime(home)
    path = home / "repomap.rpl.toml"
    path.write_text(path.read_text().replace(
        'password_env = "REPOMAP_PG_PASSWORD"', 'password_env = "CUSTOM_ADMIN_PASSWORD"'
    ))
    monkeypatch.delenv("CUSTOM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(CoordinatorControlError, match="local-admin-credential"):
        coordinator_control_status(home)
