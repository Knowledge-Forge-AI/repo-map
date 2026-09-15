from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import psycopg

from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.ops.refresh import (
    drift_check_to_jsonable,
    graph_baseline_to_jsonable,
    query_drift_check,
    query_graph_summary,
    refresh_graph,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    repository_identity_reconciliation_sql,
    run_psql,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    postgres_bin_dir,
    require_postgres_binaries,
    temporary_postgres,
)


_DATABASE = "repomap_arch5c3"
_RESTORED_DATABASE = "repomap_arch5c3_restored"
_GRAPH_ID = "arch5c3-fixture"
_REPOSITORY_NAME = "arch5c3-fixture"
_REPOSITORY_IDENTITY = "repo1:arch5c3-fixture"


def test_arch5c3_preserves_baseline_across_rollback_and_forward_reconstruction() -> None:
    require_postgres_binaries()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        old_source = root / "source-old"
        current_source = root / "source-current"
        old_source.mkdir()
        (old_source / "README.md").write_text("# ARCH5C3 fixture\n", encoding="utf-8")
        backup_path = root / "pre-identity.dump"

        with temporary_postgres() as postgres:
            psql_args = _create_graph_database(postgres, _DATABASE)
            apply_migrations(
                default_rdbms_root(),
                psql_args,
                psql_command=postgres.psql_command,
            )
            old_config = _write_config(
                root / "old.toml", postgres, old_source, _DATABASE
            )
            observations = tuple(discover_observations(old_source))
            historical = publish_observation_generation(
                psql_args,
                observations,
                repository_name=_REPOSITORY_NAME,
                root_path=str(old_source.resolve()),
                psql_command=postgres.psql_command,
            )
            baseline = graph_baseline_to_jsonable(
                old_config,
                query_graph_summary(
                    old_config,
                    _GRAPH_ID,
                    psql_command=postgres.psql_command,
                ),
            )["baseline"]
            _dump_database(postgres, psql_args, backup_path)

            old_source.rename(current_source)
            current_config = _write_config(
                root / "current.toml", postgres, current_source, _DATABASE
            )
            _reconcile(postgres, psql_args, current_source)
            migration_drift = drift_check_to_jsonable(
                current_config,
                query_drift_check(
                    current_config,
                    _GRAPH_ID,
                    baseline=baseline,
                    psql_command=postgres.psql_command,
                ),
            )
            refreshed = refresh_graph(
                current_config,
                _GRAPH_ID,
                psql_command=postgres.psql_command,
            )
            stable_state = _repository_state(psql_args)
            stable_baseline = graph_baseline_to_jsonable(
                current_config,
                query_graph_summary(
                    current_config,
                    _GRAPH_ID,
                    psql_command=postgres.psql_command,
                ),
            )["baseline"]
            stable_drift = drift_check_to_jsonable(
                current_config,
                query_drift_check(
                    current_config,
                    _GRAPH_ID,
                    baseline=stable_baseline,
                    psql_command=postgres.psql_command,
                ),
            )

        assert backup_path.is_file() and backup_path.stat().st_size > 0
        assert refreshed.result == "success"
        assert stable_state == (
            historical.repository_id,
            f"graph:{_GRAPH_ID}",
            _REPOSITORY_IDENTITY,
        )
        assert not migration_drift["drift_detected"], migration_drift["drift"]
        assert not stable_drift["drift_detected"], stable_drift["drift"]

        with temporary_postgres() as restored_postgres:
            restored_args = _create_graph_database(
                restored_postgres, _RESTORED_DATABASE
            )
            _restore_database(restored_postgres, restored_args, backup_path)
            restored_config = _write_config(
                root / "restored.toml",
                restored_postgres,
                current_source,
                _RESTORED_DATABASE,
            )
            restored_state = _repository_state(restored_args)
            restored_drift = drift_check_to_jsonable(
                restored_config,
                query_drift_check(
                    restored_config,
                    _GRAPH_ID,
                    baseline=baseline,
                    psql_command=restored_postgres.psql_command,
                ),
            )
            _reconcile(restored_postgres, restored_args, current_source)
            reconstructed_migration_drift = drift_check_to_jsonable(
                restored_config,
                query_drift_check(
                    restored_config,
                    _GRAPH_ID,
                    baseline=baseline,
                    psql_command=restored_postgres.psql_command,
                ),
            )
            reconstructed = refresh_graph(
                restored_config,
                _GRAPH_ID,
                psql_command=restored_postgres.psql_command,
            )
            reconstructed_state = _repository_state(restored_args)
            reconstructed_drift = drift_check_to_jsonable(
                restored_config,
                query_drift_check(
                    restored_config,
                    _GRAPH_ID,
                    baseline=stable_baseline,
                    psql_command=restored_postgres.psql_command,
                ),
            )

        assert restored_state == (
            historical.repository_id,
            str(old_source.resolve()),
            None,
        )
        assert not restored_drift["drift_detected"], restored_drift["drift"]
        assert not reconstructed_migration_drift[
            "drift_detected"
        ], reconstructed_migration_drift["drift"]
        assert reconstructed.result == "success"
        assert reconstructed_state == stable_state
        assert not reconstructed_drift["drift_detected"], reconstructed_drift[
            "drift"
        ]


def _create_graph_database(postgres, database: str) -> list[str]:
    postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE);')
    _run(
        postgres,
        "createdb",
        "-h",
        str(postgres.socket_dir),
        "-p",
        str(postgres.port),
        "-U",
        postgres.user,
        database,
    )
    args = list(postgres.psql_args)
    args[-1] = database
    return args


def _write_config(path: Path, postgres, source: Path, database: str):
    path.write_text(
        f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_default"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "{_GRAPH_ID}"
name = "ARCH5C3 Fixture"
root_path = "{source}"
repository_name = "{_REPOSITORY_NAME}"
database = "{database}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "server-memory"
mode = "read_only"
""",
        encoding="utf-8",
    )
    return load_ops_config(path)


def _dump_database(postgres, psql_args: list[str], backup_path: Path) -> None:
    _run(
        postgres,
        "pg_dump",
        *psql_args,
        "--format=plain",
        "--file",
        str(backup_path),
    )
    portable = "\n".join(
        line
        for line in backup_path.read_text(encoding="utf-8").splitlines()
        if line != "SET transaction_timeout = 0;"
    )
    backup_path.write_text(portable + "\n", encoding="utf-8")


def _restore_database(postgres, psql_args: list[str], backup_path: Path) -> None:
    run_psql(
        [
            postgres.psql_command,
            *psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=backup_path.read_text(encoding="utf-8"),
    )


def _run(postgres, executable: str, *args: str) -> None:
    subprocess.run(
        [str(postgres_bin_dir() / executable), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _reconcile(postgres, psql_args: list[str], source: Path) -> None:
    run_psql(
        [
            postgres.psql_command,
            *psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=repository_identity_reconciliation_sql(
            _REPOSITORY_IDENTITY,
            _REPOSITORY_NAME,
            str(source.resolve()),
        ),
    )


def _repository_state(psql_args: list[str]) -> tuple[int, str, str | None]:
    params = _psycopg_connection_params_from_psql_args(psql_args)
    with psycopg.connect(
        host=params["host"],
        port=int(params["port"]),
        user=params["user"],
        dbname=params["dbname"],
    ) as connection:
        rows = connection.execute(
            "SELECT id, root_path, repository_identity FROM repositories"
        ).fetchall()
    assert len(rows) == 1
    return rows[0]
