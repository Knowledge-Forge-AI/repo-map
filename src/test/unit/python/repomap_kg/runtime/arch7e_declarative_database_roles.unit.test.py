import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.coordinator.local_lifecycle import LocalControlAuthority
from repomap_kg.runtime.backup import init_database_from_source
from repomap_kg.runtime.backup_restore_sets import restore_coordinated_backup
from repomap_kg.runtime.commands import default_env_text, render_compose_yaml
from repomap_kg.runtime.database_roles import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    ensure_role_secrets,
    read_role_secrets,
    render_database_role_sql,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import build_local_runtime_plan
from repomap_kg.server.http import load_config_for_server
from repomap_kg.server.ops import load_mcp_ops_config


def _env_values(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def _write_coordinated_backup(home: Path) -> Path:
    plan = build_local_runtime_plan(home)
    backup_path = home / "backups" / "coordinated-backup"
    backup_path.mkdir(parents=True)
    dump_files = []
    for database in plan.owned_databases:
        content = f"dump:{database}".encode()
        path = backup_path / f"{database}.pgcustom"
        path.write_bytes(content)
        dump_files.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    manifest = {
        "backup_format_version": 1,
        "backup_id": "coordinated-backup",
        "backup_kind": "manual-dump-all",
        "databases": list(plan.owned_databases),
        "dump_files": dump_files,
        "dump_format": "pgcustom",
        "recovery_point": {
            "held_through": "atomic-backup-publication",
            "method": "control-then-graph-maintenance-exclusion",
            "status": "stable",
        },
        "scope": "exact-configured-graph-control-databases",
    }
    (backup_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return backup_path


def test_default_env_has_distinct_owner_protected_role_secrets() -> None:
    values = _env_values(default_env_text())

    secrets = {
        values["POSTGRES_PASSWORD"],
        values["REPOMAP_READ_STATUS_PASSWORD"],
        values["REPOMAP_REFRESH_PUBLICATION_PASSWORD"],
        values["REPOMAP_COORDINATOR_CONTROL_PASSWORD"],
    }
    assert len(secrets) == 4
    assert values["REPOMAP_PG_PASSWORD"] == values["POSTGRES_PASSWORD"]
    assert values["PGPASSWORD"] == values["POSTGRES_PASSWORD"]


def test_existing_env_gains_only_missing_private_role_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=existing\nCUSTOM=value\n", encoding="utf-8")
    env_file.chmod(0o644)

    added = ensure_role_secrets(env_file)
    values = _env_values(env_file.read_text(encoding="utf-8"))

    assert added == (
        "REPOMAP_READ_STATUS_PASSWORD",
        "REPOMAP_REFRESH_PUBLICATION_PASSWORD",
        "REPOMAP_COORDINATOR_CONTROL_PASSWORD",
    )
    assert values["POSTGRES_PASSWORD"] == "existing"
    assert values["CUSTOM"] == "value"
    assert len(values) == 5
    assert env_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("invalid", ("", "line\nbreak", "x" * 257))
def test_role_secrets_reject_invalid_credential_values(invalid: str) -> None:
    with pytest.raises(ValueError, match="database role credential is invalid"):
        RoleSecrets(invalid, "refresh", "control")


def test_http_render_receives_only_read_status_database_secret(tmp_path: Path) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    compose = render_compose_yaml(build_local_runtime_plan(home))
    http = compose.split("\n  http:\n", 1)[1].split("\n  mcp:\n", 1)[0]

    assert f"REPOMAP_PG_USER: {READ_STATUS_ROLE}" in http
    assert "PGPASSWORD: ${REPOMAP_READ_STATUS_PASSWORD}" in http
    assert "REPOMAP_PG_PASSWORD: ${REPOMAP_READ_STATUS_PASSWORD}" in http
    assert "REPOMAP_READ_STATUS_PASSWORD: ${REPOMAP_READ_STATUS_PASSWORD}" in http
    assert "env_file:" not in http
    assert "${POSTGRES_PASSWORD}" not in http
    assert f'source: "{home / "repomap.rpl.toml"}"' in http
    assert 'target: "/repo-map-home/repomap.rpl.toml"' in http
    assert "read_only: true" in http


def test_read_only_services_project_the_parsed_config_onto_read_role(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)

    http_config, diagnostic_count, truncated = load_config_for_server(home)
    config_path = next(
        path
        for path in home.rglob("*.toml")
        if path.name.endswith((".rp.toml", ".rpl.toml"))
    )
    with patch.dict(
        "os.environ",
        {"REPOMAP_READ_STATUS_PASSWORD": "read-secret"},
    ):
        mcp_config = load_mcp_ops_config(config_path)

    assert diagnostic_count == 0
    assert truncated is False
    assert http_config is not None
    for config in (http_config, mcp_config):
        assert config.postgres.user == READ_STATUS_ROLE
        assert config.postgres.password_env == "REPOMAP_READ_STATUS_PASSWORD"
        assert config.postgres.password is None
        assert config.postgres.password_file is None


def test_explicit_empty_mcp_read_secret_does_not_restore_admin_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    config_path = next(
        path
        for path in home.rglob("*.toml")
        if path.name.endswith((".rp.toml", ".rpl.toml"))
    )

    with patch.dict(
        "os.environ",
        {"REPOMAP_READ_STATUS_PASSWORD": ""},
    ):
        config = load_mcp_ops_config(config_path)

    assert config.postgres.user == READ_STATUS_ROLE
    assert config.postgres.password_env == "REPOMAP_READ_STATUS_PASSWORD"
    assert config.postgres.password is None
    assert config.postgres.password_file is None


def test_coordinator_authority_never_loads_admin_secret_and_routes_exact_roles(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    home.chmod(0o700)
    secrets = read_role_secrets(home / "runtime" / ".env")

    with (
        patch(
            "repomap_kg.coordinator._lifecycle_authority._postgres_password",
            side_effect=AssertionError("administrator secret must not be loaded"),
        ),
        patch("repomap_kg.coordinator.local_lifecycle.psycopg.connect") as connect,
    ):
        authority = LocalControlAuthority(home, capability="coordinator")
        authority._connect(authority.database_name)
        authority._connect(authority.graph_databases[0])
        with pytest.raises(
            RuntimeError,
            match="coordinator_database_capability_denied",
        ):
            authority._connect(authority._maintenance_database)

    assert connect.call_args_list[0].kwargs["user"] == COORDINATOR_CONTROL_ROLE
    assert connect.call_args_list[0].kwargs["password"] == secrets.coordinator_control
    assert connect.call_args_list[1].kwargs["user"] == REFRESH_PUBLICATION_ROLE
    assert connect.call_args_list[1].kwargs["password"] == secrets.refresh_publication


def test_graph_role_sql_has_exact_capability_matrix() -> None:
    sql = render_database_role_sql(
        database="graph_db",
        owner_role="repomap",
        database_kind="graph",
        secrets=RoleSecrets("read-secret", "refresh-secret", "control-secret"),
    )
    normalized = " ".join(sql.split())

    assert sql.startswith("BEGIN;\n")
    assert sql.endswith("COMMIT;\n")
    assert f'GRANT CONNECT ON DATABASE "graph_db" TO "{READ_STATUS_ROLE}"' in sql
    assert (
        f'GRANT CONNECT, TEMPORARY ON DATABASE "graph_db" '
        f'TO "{REFRESH_PUBLICATION_ROLE}"' in sql
    )
    assert (
        f'REVOKE CONNECT ON DATABASE "graph_db" '
        f'FROM "{COORDINATOR_CONTROL_ROLE}"' in sql
    )
    assert f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{READ_STATUS_ROLE}"' in sql
    assert "SELECT, INSERT, UPDATE, DELETE" in normalized
    assert "read-secret" in sql
    assert "refresh-secret" in sql
    assert "control-secret" in sql
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in normalized
    assert "NOREPLICATION NOBYPASSRLS" in normalized
    assert "REVOKE %I FROM %I" in sql
    assert "database capability role owns objects" in sql


def test_role_sql_preserves_existing_quoted_owner_identifier_contract() -> None:
    sql = render_database_role_sql(
        database="graph_db",
        owner_role='release-owner@example.com',
        database_kind="graph",
        secrets=RoleSecrets("read-secret", "refresh-secret", "control-secret"),
    )

    assert (
        'ALTER DEFAULT PRIVILEGES FOR ROLE "release-owner@example.com"'
        in sql
    )


def test_control_role_sql_excludes_refresh_publication() -> None:
    sql = render_database_role_sql(
        database="control_db",
        owner_role="repomap",
        database_kind="control",
        secrets=RoleSecrets("read-secret", "refresh-secret", "control-secret"),
    )
    normalized = " ".join(sql.split())

    assert f'GRANT CONNECT ON DATABASE "control_db" TO "{READ_STATUS_ROLE}"' in sql
    assert (
        f'GRANT CONNECT ON DATABASE "control_db" '
        f'TO "{COORDINATOR_CONTROL_ROLE}"' in sql
    )
    assert (
        f'REVOKE CONNECT ON DATABASE "control_db" '
        f'FROM "{REFRESH_PUBLICATION_ROLE}"' in sql
    )
    mutation_grant = "SELECT, INSERT, UPDATE, DELETE"
    assert (
        f'{mutation_grant}, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES '
        f'IN SCHEMA public TO "{COORDINATOR_CONTROL_ROLE}"' in normalized
    )
    assert (
        f'{mutation_grant}, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES '
        f'IN SCHEMA public TO "{REFRESH_PUBLICATION_ROLE}"' not in normalized
    )


def test_fresh_graph_init_reconciles_roles_inside_cleanup_boundary(tmp_path: Path) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    database = plan.graph_databases[0]
    events: list[str] = []

    with (
        patch("repomap_kg.runtime._backup_lifecycle.inspect_owned_postgres_container"),
        patch("repomap_kg.runtime._backup_lifecycle.database_exists", return_value=False),
        patch("repomap_kg.runtime._backup_lifecycle.create_database"),
        patch(
            "repomap_kg.runtime._backup_lifecycle.apply_source_schema",
            side_effect=lambda *_args: events.append("schema"),
        ),
        patch(
            "repomap_kg.runtime._backup_lifecycle.reconcile_graph_database_roles",
            side_effect=lambda *_args: events.append("roles"),
        ),
        patch(
            "repomap_kg.runtime.provisioning.require_graph_schema_ready",
            side_effect=lambda *_args: events.append("ready"),
        ),
    ):
        init_database_from_source(home, database=database)

    assert events == ["schema", "roles", "ready"]


def test_coordinated_restore_reconciles_graphs_then_control(tmp_path: Path) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    backup_path = _write_coordinated_backup(home)
    plan = build_local_runtime_plan(home)
    events: list[tuple[str, str]] = []

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container"
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            return_value=False,
        ),
        patch("repomap_kg.runtime.backup_restore_sets.create_database"),
        patch("repomap_kg.runtime.backup_restore_sets.run_pg_restore"),
        patch(
            "repomap_kg.runtime.backup_restore_sets.reconcile_graph_database_roles",
            side_effect=lambda _plan, database, _runner: events.append(
                ("graph", database)
            ),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.reconcile_control_database_roles",
            side_effect=lambda _plan, database, _runner: events.append(
                ("control", database)
            ),
        ),
    ):
        restore_coordinated_backup(home, backup=backup_path)

    control = tuple(
        database for database in plan.owned_databases if database not in plan.graph_databases
    )
    assert events == [
        *(("graph", database) for database in sorted(plan.graph_databases)),
        ("control", control[0]),
    ]
