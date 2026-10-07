"""Real PostgreSQL readiness, backup, and control-schema upgrade contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from repomap_kg.coordinator._control_schema import (
    ControlSchemaError,
    ControlSchemaStatus,
    _ledger_create_statements,
    _ledger_insert_statement,
    discover_control_migrations,
)
from repomap_kg.coordinator._lifecycle_authority import LocalControlAuthority
from repomap_kg.coordinator._lifecycle_upgrade import (
    CoordinatorControlError,
    _reference_database_name,
    upgrade_coordinator_control,
)
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.runtime.database_role_contract import ensure_role_secrets
from repomap_kg.runtime.backup_manifests import (
    summarize_pg_restore_toc,
    verify_dump_file_checksum_for_inspection,
)
from repomap_test_support.postgres_harness import (
    postgres_bin_dir,
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import short_test_directory


def _connect(postgres, dbname: str | None = None, *, autocommit: bool = False):
    return psycopg.connect(
        host=postgres.host, port=postgres.port, user=postgres.user,
        dbname=dbname or postgres.database, password=postgres.password, autocommit=autocommit,
    )


def _setup_behind_schema(connection: psycopg.Connection) -> None:
    migrations = discover_control_migrations()
    for statement in _ledger_create_statements(): connection.execute(statement)
    connection.execute(migrations[0].path.read_text(encoding="utf-8"))
    connection.execute(_ledger_insert_statement(migrations[0]))
    connection.commit()


def _insert_sentinel_job(connection: psycopg.Connection, job_id: str) -> None:
    connection.execute(
        "INSERT INTO jobs (job_id, schema_version, job_kind, graph_id, request_id, requester, "
        "idempotency_digest, request_fingerprint, priority_class, priority_value, "
        "source_generation, config_generation, extractor_generation, canonicalizer_generation) "
        "VALUES (%s, 1, 'refresh_graph', 'test-graph', 'req-1', 'test', repeat('a', 64), "
        "repeat('b', 64), 'manual', 50, 'sg1:sentinel', 'cg1:sentinel', 'eg1:sentinel', 'kg1:sentinel')",
        (job_id,),
    )
    connection.commit()


def _assert_sentinel_job(connection: psycopg.Connection, job_id: str) -> None:
    row = connection.execute("SELECT job_id FROM jobs WHERE job_id = %s", (job_id,)).fetchone()
    assert row is not None and row[0] == job_id


def _make_home(root: Path, postgres, graph_db: str) -> Path:
    home = root / "home"
    home.mkdir(parents=True, mode=0o700)
    cfg = (
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\n'
        f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\ndatabase = "{graph_db}"\n'
        f'user = "{postgres.user}"\npassword_env = "TEST_PG_PASSWORD"\n[[graphs]]\nid = "test-graph"\n'
        f'name = "Test Graph"\nroot_path = "/placeholder"\nrepository_name = "test"\nprivacy = "public-dev"\n'
        f'enabled = true\nrefresh_policy = "manual"\n[server_memory]\nenabled = false\npath = "disabled"\n'
    )
    (home / "configured.rp.toml").write_text(cfg, encoding="utf-8")
    ensure_role_secrets(home / "runtime" / ".env")
    return home


def _authentic_dump(postgres, backup_root: Path):
    def dump_func(_home, *, database: str, reason=None, timestamp=None):
        ts = (timestamp or "now").replace(":", "_").replace("-", "_")
        bdir = backup_root / f"{database}_{ts}"
        bdir.mkdir(parents=True, exist_ok=True)
        dump_file = bdir / "dump.pgcustom"
        pg_dump = str(postgres_bin_dir() / "pg_dump")
        subprocess.run(
            [pg_dump, "-h", postgres.host, "-p", str(postgres.port), "-U", postgres.user, "-d", database, "-Fc", "-f", str(dump_file)],
            env={**os.environ, "PGPASSWORD": postgres.password}, check=True, capture_output=True,
        )
        checksum = hashlib.sha256(dump_file.read_bytes()).hexdigest()
        manifest = {"backup_format_version": 1, "database": database, "dump_files": [{"name": "dump.pgcustom", "sha256": checksum, "size_bytes": dump_file.stat().st_size}], "restore_supported": True}
        (bdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return SimpleNamespace(plan=SimpleNamespace(backup_path=bdir))
    return dump_func


def _test_inspect_seam(repo_map_home: str | Path | None, backup_id_or_path: str | Path):
    """Adapt a harness dump through maintained checksum and real pg_restore TOC readback."""
    path = Path(backup_id_or_path)
    manifest_file, dump_file = path / "manifest.json", path / "dump.pgcustom"
    if not manifest_file.exists() or not dump_file.exists():
        return SimpleNamespace(checksum_verified=False, dump_summaries=[], manifest={})
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    verified, diagnostics = verify_dump_file_checksum_for_inspection(
        dump_file, manifest["dump_files"][0], dump_file.name,
    )
    toc = subprocess.run(
        [str(postgres_bin_dir() / "pg_restore"), "--list", str(dump_file)],
        check=True, capture_output=True, text=True,
    ).stdout
    summary = summarize_pg_restore_toc(toc, dump_file=dump_file.name, dump_format="pgcustom")
    return SimpleNamespace(
        checksum_verified=verified, dump_summaries=[summary], manifest=manifest,
        diagnostics=diagnostics,
    )


def test_control_schema_readiness_absent_and_diverged_table_sets():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        db_name = f"ctrl_test_{uuid.uuid4().hex[:8]}"
        with _connect(postgres, autocommit=True) as root_conn:
            root_conn.execute(f'CREATE DATABASE "{db_name}"')
        try:
            store = ControlStore(lambda: _connect(postgres, db_name))

            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.UNINITIALIZED
            assert readiness.applied_count == 0
            assert readiness.expected_count == len(discover_control_migrations())

            with _connect(postgres, db_name) as conn:
                conn.execute("CREATE TABLE unexpected_relation (id integer);")
                conn.commit()

            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.DIVERGED
            with pytest.raises(ControlSchemaError, match="incompatible control schema table set"):
                store.check_schema_version()
        finally:
            with _connect(postgres, autocommit=True) as root_conn:
                root_conn.execute(f'DROP DATABASE "{db_name}"')


def test_partial_ledger_behind_state_divergence_and_corrupt_row_detection():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        db_name = f"ctrl_behind_{uuid.uuid4().hex[:8]}"
        with _connect(postgres, autocommit=True) as root_conn:
            root_conn.execute(f'CREATE DATABASE "{db_name}"')
        try:
            with _connect(postgres, db_name) as conn:
                _setup_behind_schema(conn)
                _insert_sentinel_job(conn, "sentinel-job-behind")

            store = ControlStore(lambda: _connect(postgres, db_name))
            migrations = discover_control_migrations()

            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.BEHIND
            assert readiness.applied_count == 1
            assert readiness.expected_count == len(migrations)
            with pytest.raises(ControlSchemaError, match="incompatible control schema state: behind"):
                store.check_schema_version()

            # 2. Corrupt ledger row: drop check constraint, alter ordinal to text
            with _connect(postgres, db_name) as conn:
                conn.execute(
                    "ALTER TABLE repomap_control_schema_migrations DROP CONSTRAINT repomap_control_schema_migrations_ordinal_check; "
                    "ALTER TABLE repomap_control_schema_migrations ALTER COLUMN ordinal TYPE text;"
                )
                conn.commit()
                with pytest.raises(ControlSchemaError, match="invalid control schema ledger"):
                    store.schema_readiness()
                # Restore schema and check data preservation
                conn.execute(
                    "ALTER TABLE repomap_control_schema_migrations ALTER COLUMN ordinal TYPE integer USING ordinal::integer; "
                    "ALTER TABLE repomap_control_schema_migrations ADD CONSTRAINT repomap_control_schema_migrations_ordinal_check CHECK (ordinal > 0);"
                )
                conn.commit()
                _assert_sentinel_job(conn, "sentinel-job-behind")

            # 3. Diverged ledger: checksum tampered
            valid_checksum = migrations[0].checksum
            with _connect(postgres, db_name) as conn:
                conn.execute("UPDATE repomap_control_schema_migrations SET checksum = %s WHERE ordinal = 1;", ("0" * 64,))
                conn.commit()
                readiness = store.schema_readiness()
                assert readiness.status is ControlSchemaStatus.DIVERGED
                with pytest.raises(ControlSchemaError, match="incompatible control schema state: diverged"):
                    store.check_schema_version()

                # Restore valid checksum and assert data preservation
                conn.execute("UPDATE repomap_control_schema_migrations SET checksum = %s WHERE ordinal = 1;", (valid_checksum,))
                conn.commit()
                _assert_sentinel_job(conn, "sentinel-job-behind")
            assert store.schema_readiness().status is ControlSchemaStatus.BEHIND
        finally:
            with _connect(postgres, autocommit=True) as root_conn:
                root_conn.execute(f'DROP DATABASE "{db_name}"')


def test_upgrade_ledgered_schema_refusals_rollback_and_success(tmp_path):
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        db_name, scratch_ref = f"ctrl_upg_{uuid.uuid4().hex[:8]}", f"scratch_ref_{uuid.uuid4().hex[:8]}"
        with _connect(postgres, autocommit=True) as root_conn:
            root_conn.execute(f'CREATE DATABASE "{db_name}"; CREATE DATABASE "{scratch_ref}"')
        try:
            ref_store = ControlStore(lambda: _connect(postgres, scratch_ref))
            ref_store.initialize_schema()
            expected_manifest = ref_store.schema_manifest()

            with _connect(postgres, db_name) as conn:
                _setup_behind_schema(conn)
                _insert_sentinel_job(conn, "sentinel-job-upg")

            store = ControlStore(lambda: _connect(postgres, db_name))
            assert store.schema_readiness().status is ControlSchemaStatus.BEHIND

            # 1. Refusal: backup_verified is False
            with pytest.raises(ControlSchemaError, match="verified backup is required"):
                store.upgrade_ledgered_schema(expected_manifest=expected_manifest, backup_verified=False)
            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.BEHIND and readiness.applied_count == 1
            with _connect(postgres, db_name) as conn:
                _assert_sentinel_job(conn, "sentinel-job-upg")

            backup = _authentic_dump(postgres, tmp_path / "backups")(None, database=db_name)
            inspection = _test_inspect_seam(None, backup.plan.backup_path)
            assert inspection.checksum_verified and inspection.manifest["restore_supported"]
            assert not inspection.diagnostics
            assert inspection.dump_summaries[0].dump_contents_read
            # Separately prove actual persisted backup state directly from disk
            backup_dump, backup_manifest = backup.plan.backup_path / "dump.pgcustom", backup.plan.backup_path / "manifest.json"
            assert backup_dump.is_file() and backup_manifest.is_file()
            manifest_json, dump_raw = json.loads(backup_manifest.read_text(encoding="utf-8")), backup_dump.read_bytes()
            assert dump_raw[:5] == b"PGDMP" and hashlib.sha256(dump_raw).hexdigest() == manifest_json["dump_files"][0]["sha256"]
            assert manifest_json["database"] == db_name and manifest_json["restore_supported"] is True

            # 2. Refusal and Rollback: manifest mismatch
            with pytest.raises(ControlSchemaError, match="upgraded control schema is not exact-current"):
                store.upgrade_ledgered_schema(
                    expected_manifest=("unexpected_manifest_signature",),
                    backup_verified=True,
                )
            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.BEHIND and readiness.applied_count == 1
            with _connect(postgres, db_name) as conn:
                _assert_sentinel_job(conn, "sentinel-job-upg")

            store.upgrade_ledgered_schema(expected_manifest=expected_manifest, backup_verified=True)
            readiness = store.schema_readiness()
            assert readiness.status is ControlSchemaStatus.CURRENT
            assert readiness.applied_count == len(discover_control_migrations())
            assert store.check_schema_version() == 1
            with _connect(postgres, db_name) as conn:
                _assert_sentinel_job(conn, "sentinel-job-upg")
                migrations = discover_control_migrations()
                ledger = conn.execute("SELECT ordinal, changeset_id, migration_path, checksum FROM repomap_control_schema_migrations ORDER BY ordinal").fetchall()
                assert ledger == [(m.ordinal, m.changeset_id, m.relative_path, m.checksum) for m in migrations]

            # Refuse upgrade when the durable control ledger is already current.
            with pytest.raises(ControlSchemaError, match="control schema is not an exact known older ledger"):
                store.upgrade_ledgered_schema(expected_manifest=expected_manifest, backup_verified=True)
            assert store.schema_readiness().status is ControlSchemaStatus.CURRENT
            with _connect(postgres, db_name) as conn:
                _assert_sentinel_job(conn, "sentinel-job-upg")

            # Refuse preledger adoption when current ledger authority already exists.
            with pytest.raises(ControlSchemaError, match="control schema is not adoptable: current"):
                store.adopt_preledger_schema(expected_manifest=expected_manifest, backup_verified=True)
            assert store.schema_readiness().status is ControlSchemaStatus.CURRENT
            with _connect(postgres, db_name) as conn:
                _assert_sentinel_job(conn, "sentinel-job-upg")
        finally:
            with _connect(postgres, autocommit=True) as root_conn:
                root_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"; DROP DATABASE IF EXISTS "{scratch_ref}"')


def test_coordinator_control_upgrade_lifecycle_flow_and_refusals(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("p5-ctrl-", "home/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("TEST_PG_PASSWORD", postgres.password)
            graph_db = f"p5_graph_{uuid.uuid4().hex[:8]}"
            with _connect(postgres, autocommit=True) as root_conn:
                root_conn.execute(f'CREATE DATABASE "{graph_db}"')

            home = _make_home(root, postgres, graph_db)
            authority = LocalControlAuthority(home)
            ts = "20261004T120000Z"
            ref_name = _reference_database_name(ts)
            dump_fn = _authentic_dump(postgres, root / "backups")
            inspect_fn = _test_inspect_seam

            try:
                # 1. Refusal: control database is absent
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(home, backup_first=True, confirmed=True)

                # 2. Initially-behind DB via authority fixture (no DROP SCHEMA CASCADE)
                authority.create_database()
                target_store = authority.control_store()
                with _connect(postgres, authority.database_name) as conn:
                    _setup_behind_schema(conn)
                    _insert_sentinel_job(conn, "sentinel-coord-1")
                assert target_store.schema_readiness().status.value == "behind"

                # 3. Refusal: reference database already exists
                authority.create_reference_database(ref_name)
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(
                        home, backup_first=True, confirmed=True, timestamp=ts, dump_function=dump_fn, inspect_function=inspect_fn,
                    )
                authority.drop_reference_database(ref_name)
                with _connect(postgres, authority.database_name) as conn:
                    _assert_sentinel_job(conn, "sentinel-coord-1")

                # 4. Refusal: backup inspection is not restorable
                bad_inspect = lambda _h, _p: SimpleNamespace(
                    checksum_verified=False, dump_summaries=[], manifest={"restore_supported": False},
                )
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(
                        home, backup_first=True, confirmed=True, timestamp=ts, dump_function=dump_fn, inspect_function=bad_inspect,
                    )
                with _connect(postgres, authority.database_name) as conn:
                    _assert_sentinel_job(conn, "sentinel-coord-1")

                # 5. Refusal: reference database creation fails
                class _FailingAuthority:
                    def __init__(self, inner): self._inner = inner
                    def __getattr__(self, name): return getattr(self._inner, name)
                    def maintenance_window(self, *, graph_databases=()): return self._inner.maintenance_window(graph_databases=graph_databases)
                    def create_reference_database(self, _db): raise RuntimeError("reference_create_failed")

                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(
                        home, backup_first=True, confirmed=True, timestamp=ts,
                        authority_factory=lambda _h: _FailingAuthority(authority), dump_function=dump_fn, inspect_function=inspect_fn,
                    )
                with _connect(postgres, authority.database_name) as conn:
                    _assert_sentinel_job(conn, "sentinel-coord-1")

                # 6. Successful upgrade of BEHIND database
                result = upgrade_coordinator_control(
                    home, backup_first=True, confirmed=True, timestamp=ts, dump_function=dump_fn, inspect_function=inspect_fn,
                )
                assert result["result"] == "ready"
                assert result["schema_before"] == "known-older-ledger"
                assert result["schema_version"] == 1
                assert result["reference_cleaned"] is True
                assert result["backup_verified"] is True
                assert not authority.reference_database_exists(ref_name)
                assert target_store.schema_readiness().status is ControlSchemaStatus.CURRENT
                assert target_store.check_schema_version() == 1

                # Real persisted backup state verified directly
                backup_dir = root / "backups" / f"{authority.database_name}_{ts.replace(':', '_').replace('-', '_')}"
                dump_pg, manifest_pg = backup_dir / "dump.pgcustom", backup_dir / "manifest.json"
                assert dump_pg.is_file() and manifest_pg.is_file()
                dump_data = dump_pg.read_bytes()
                assert dump_data[:5] == b"PGDMP"
                persisted_manifest = json.loads(manifest_pg.read_text(encoding="utf-8"))
                assert hashlib.sha256(dump_data).hexdigest() == persisted_manifest["dump_files"][0]["sha256"]
                assert persisted_manifest["database"] == authority.database_name and persisted_manifest["restore_supported"] is True

                # Data preservation of original rows and sentinel, plus real persisted schema
                with _connect(postgres, authority.database_name) as conn:
                    _assert_sentinel_job(conn, "sentinel-coord-1")
                    row = conn.execute("SELECT has_table_privilege(%s, 'jobs', 'SELECT')", ("repomap_coordinator_control",)).fetchone()
                    assert row is not None and row[0] is True
                    all_migs = discover_control_migrations()
                    ledger_rows = conn.execute("SELECT ordinal, changeset_id, migration_path, checksum FROM repomap_control_schema_migrations ORDER BY ordinal").fetchall()
                    assert ledger_rows == [(m.ordinal, m.changeset_id, m.relative_path, m.checksum) for m in all_migs]

                # 7. Refusal when already current
                with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed"):
                    upgrade_coordinator_control(
                        home, backup_first=True, confirmed=True, timestamp=ts, dump_function=dump_fn, inspect_function=inspect_fn,
                    )
                with _connect(postgres, authority.database_name) as conn:
                    _assert_sentinel_job(conn, "sentinel-coord-1")
            finally:
                if authority.reference_database_exists(ref_name): authority.drop_reference_database(ref_name)
                if authority.database_exists(): authority.drop_created_database()
                with _connect(postgres, autocommit=True) as root_conn:
                    root_conn.execute(f'DROP DATABASE IF EXISTS "{graph_db}"')
