from __future__ import annotations

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
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
    query_canonical_node_records,
    repository_identity_reconciliation_sql,
    run_psql,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.postgres_logical_backup import (
    dump_plain_database,
    restore_plain_database,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root


_GRAPH_ID = "arch5d-fixture"
_REPOSITORY_NAME = "arch5d-fixture"
_REPOSITORY_IDENTITY = "repo1:arch5d-fixture"
_REMOVED_TABLES = (
    "stage_legacy_edges",
    "stage_legacy_evidence",
    "stage_legacy_nodes",
    "edges",
    "evidence",
    "nodes",
)
_RETAINED_TABLES = (
    "repositories",
    "runs",
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
    "ingestion_stages",
    "stage_files",
    "stage_raw_observations",
    "stage_canonical_nodes",
    "stage_canonical_edges",
    "stage_canonical_evidence",
    "stage_canonical_node_evidence",
    "stage_canonical_edge_evidence",
    "graph_publication_authority",
)


def test_arch5d_upgrade_restore_and_forward_recovery() -> None:
    require_postgres_binaries()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        historical_root = pre_arch5d_rdbms_root(root)
        old_source = root / "source-old"
        current_source = root / "source-current"
        old_source.mkdir()
        (old_source / "run.sh").write_text(
            "#!/bin/sh\nprintf '%s\\n' 'ARCH5D fixture'\n",
            encoding="utf-8",
        )
        backup_path = root / "pre-removal.sql"

        with temporary_postgres() as postgres:
            apply_migrations(
                historical_root,
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            old_config = _write_config(root / "old.toml", postgres, old_source)
            observations = tuple(discover_observations(old_source))
            published = publish_observation_generation(
                postgres.psql_args,
                observations,
                repository_name=_REPOSITORY_NAME,
                root_path=str(old_source.resolve()),
                repository_identity=_REPOSITORY_IDENTITY,
                psql_command=postgres.psql_command,
            )
            _seed_legacy_rows(postgres.psql_args)
            baseline = _baseline(old_config, postgres.psql_command)
            canonical_rows_before = _canonical_rows(
                postgres.psql_args,
                old_source,
                postgres.psql_command,
            )
            legacy_counts = _legacy_counts(postgres.psql_args)
            dump_plain_database(postgres, postgres.psql_args, backup_path)

            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            old_source.rename(current_source)
            _reconcile(postgres, current_source)
            current_config = _write_config(
                root / "current.toml", postgres, current_source
            )
            upgraded_presence = _table_presence(postgres.psql_args)
            upgraded_default = _stage_manifest_default(postgres.psql_args)
            canonical_rows_after = _canonical_rows(
                postgres.psql_args,
                current_source,
                postgres.psql_command,
            )
            upgraded_drift = _drift(
                current_config,
                baseline,
                postgres.psql_command,
            )
            upgraded_repository_id = _repository_id(postgres.psql_args)

        assert published.run_id > 0
        assert backup_path.is_file() and backup_path.stat().st_size > 0
        assert all(count > 0 for count in legacy_counts)
        assert canonical_rows_before[0]
        assert canonical_rows_before[1]
        assert canonical_rows_after == canonical_rows_before
        assert not upgraded_drift["drift_detected"], upgraded_drift["drift"]
        _assert_removed_and_retained(upgraded_presence)
        assert "legacy" not in upgraded_default
        assert "canonical_edge_evidence" in upgraded_default

        with temporary_postgres() as restored_postgres:
            restore_plain_database(
                restored_postgres,
                restored_postgres.psql_args,
                backup_path,
            )
            restored_counts = _legacy_counts(restored_postgres.psql_args)
            _reconcile(restored_postgres, current_source)
            restored_config = _write_config(
                root / "restored.toml", restored_postgres, current_source
            )
            restored_drift = _drift(
                restored_config,
                baseline,
                restored_postgres.psql_command,
            )
            apply_migrations(
                default_rdbms_root(),
                restored_postgres.psql_args,
                psql_command=restored_postgres.psql_command,
            )
            reconstructed_presence = _table_presence(restored_postgres.psql_args)
            reconstructed_canonical_rows = _canonical_rows(
                restored_postgres.psql_args,
                current_source,
                restored_postgres.psql_command,
            )
            reconstructed_drift = _drift(
                restored_config,
                baseline,
                restored_postgres.psql_command,
            )
            reconstructed_repository_id = _repository_id(
                restored_postgres.psql_args
            )

        assert restored_counts == legacy_counts
        assert not restored_drift["drift_detected"], restored_drift["drift"]
        _assert_removed_and_retained(reconstructed_presence)
        assert reconstructed_canonical_rows == canonical_rows_before
        assert not reconstructed_drift["drift_detected"], reconstructed_drift[
            "drift"
        ]
        assert reconstructed_repository_id == upgraded_repository_id


def _write_config(path: Path, postgres, source: Path):
    path.write_text(
        f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.psql_args[-1]}"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "{_GRAPH_ID}"
name = "ARCH5D Fixture"
root_path = "{source}"
repository_name = "{_REPOSITORY_NAME}"
database = "{postgres.psql_args[-1]}"
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


def _seed_legacy_rows(psql_args: list[str]) -> None:
    conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(psql_args).items())
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT repositories.id, max(runs.id), min(files.id) "
            "FROM repositories JOIN runs ON runs.repository_id = repositories.id "
            "JOIN files ON files.repository_id = repositories.id "
            "GROUP BY repositories.id"
        ).fetchone()
        assert row is not None
        repository_id, run_id, file_id = row
        s_row = connection.execute(
            "INSERT INTO nodes (repository_id, file_id, kind, name, stable_key) "
            "VALUES (%s, %s, 'legacy.source', 'source', 'legacy:source') RETURNING id",
            (repository_id, file_id),
        ).fetchone()
        assert s_row is not None
        source_id = s_row[0]
        t_row = connection.execute(
            "INSERT INTO nodes (repository_id, file_id, kind, name, stable_key) "
            "VALUES (%s, %s, 'legacy.target', 'target', 'legacy:target') RETURNING id",
            (repository_id, file_id),
        ).fetchone()
        assert t_row is not None
        target_id = t_row[0]
        e_row = connection.execute(
            "INSERT INTO evidence (repository_id, file_id, extractor, stable_key) "
            "VALUES (%s, %s, 'arch5d', 'legacy:evidence') RETURNING id",
            (repository_id, file_id),
        ).fetchone()
        assert e_row is not None
        evidence_id = e_row[0]
        connection.execute(
            "INSERT INTO edges "
            "(repository_id, src_node_id, dst_node_id, kind, confidence, "
            "evidence_id, stable_key) "
            "VALUES (%s, %s, %s, 'legacy.edge', 'extracted', %s, 'legacy:edge')",
            (repository_id, source_id, target_id, evidence_id),
        )
        connection.execute(
            "INSERT INTO ingestion_stages "
            "(stage_id, repository_id, operation_id, attempt, execution_mode, "
            "source_generation, config_generation, extractor_generation, "
            "canonicalizer_generation, state, expires_at, cleanup_eligibility) "
            "VALUES ('arch5d-legacy', %s, 'arch5d-legacy', 1, 'direct', "
            "'sg1:arch5d', 'cg1:arch5d', 'eg1:arch5d', 'kg1:arch5d', "
            "'quarantined', now() + interval '1 hour', 'quarantined')",
            (repository_id,),
        )
        connection.execute(
            "INSERT INTO stage_legacy_nodes "
            "(stage_id, family_ordinal, stable_key, kind, name) "
            "VALUES ('arch5d-legacy', 0, 'legacy:source', 'legacy.source', 'source')"
        )
        connection.execute(
            "INSERT INTO stage_legacy_evidence "
            "(stage_id, family_ordinal, stable_key, extractor) "
            "VALUES ('arch5d-legacy', 0, 'legacy:evidence', 'arch5d')"
        )
        connection.execute(
            "INSERT INTO stage_legacy_edges "
            "(stage_id, family_ordinal, stable_key, source_node_stable_key, "
            "target_node_stable_key, edge_kind, confidence, evidence_stable_key) "
            "VALUES ('arch5d-legacy', 0, 'legacy:edge', 'legacy:source', "
            "'legacy:target', 'legacy.edge', 'extracted', 'legacy:evidence')"
        )
        assert run_id > 0


def _canonical_rows(psql_args: list[str], source: Path, psql: str):
    root = str(source.resolve())
    nodes = query_canonical_node_records(
        psql_args,
        root_path=root,
        graph_key_version=1,
        psql_command=psql,
    )
    edges = query_canonical_edge_records(
        psql_args,
        root_path=root,
        graph_key_version=1,
        psql_command=psql,
    )
    return (
        tuple(record.to_dict() for record in nodes),
        tuple(record.to_dict() for record in edges),
    )


def _legacy_counts(psql_args: list[str]) -> tuple[int, ...]:
    conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(psql_args).items())
    with psycopg.connect(conninfo) as conn:
        return tuple(int((conn.execute(f"SELECT count(*) FROM {t}").fetchone() or (0,))[0]) for t in _REMOVED_TABLES)


def _table_presence(psql_args: list[str]) -> dict[str, bool]:
    conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(psql_args).items())
    with psycopg.connect(conninfo) as conn:
        return {
            t: bool((conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",)).fetchone() or (False,))[0])
            for t in (*_REMOVED_TABLES, *_RETAINED_TABLES)
        }


def _stage_manifest_default(psql_args: list[str]) -> str:
    conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(psql_args).items())
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'ingestion_stages' "
            "AND column_name = 'expected_family_manifest'"
        ).fetchone()
        assert row is not None
        return str(row[0])


def _assert_removed_and_retained(presence: dict[str, bool]) -> None:
    assert all(not presence[table] for table in _REMOVED_TABLES)
    assert all(presence[table] for table in _RETAINED_TABLES)


def _baseline(config, psql: str) -> dict[str, object]:
    return graph_baseline_to_jsonable(
        config,
        query_graph_summary(config, _GRAPH_ID, psql_command=psql),
    )["baseline"]


def _drift(config, baseline: dict[str, object], psql: str) -> dict[str, object]:
    return drift_check_to_jsonable(
        config,
        query_drift_check(
            config,
            _GRAPH_ID,
            baseline=baseline,
            psql_command=psql,
        ),
    )


def _repository_id(psql_args: list[str]) -> int:
    conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(psql_args).items())
    with psycopg.connect(conninfo) as connection:
        row = connection.execute("SELECT id FROM repositories").fetchone()
        assert row is not None
        return int(row[0])


def _reconcile(postgres, source: Path) -> None:
    run_psql(
        [
            postgres.psql_command,
            *postgres.psql_args,
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
