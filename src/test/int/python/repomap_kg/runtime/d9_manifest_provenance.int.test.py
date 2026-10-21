"""Containerized integration tests for ADR 0084 D9-A backup provenance and refusals."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from repomap_kg.coordinator._lifecycle_upgrade import upgrade_coordinator_control
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    initialize_coordinator_control,
    maintenance_window_for_database_drop,
)
from repomap_kg.runtime.backup import (
    drop_database,
    dump_all_databases,
    dump_database,
    init_database_from_dump,
    inspect_backup,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import restore_coordinated_backup
from repomap_kg.runtime.maintenance import MAINTENANCE_LOCK_KEY
from repomap_kg.runtime.release_cluster import ReleaseClusterError, initialize_release_cluster
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema
from repomap_kg.storage import (
    GraphSchemaStatus,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
    graph_schema_readiness,
    run_psql,
)
from repomap_kg.storage.main import _migration_script
from repomap_test_support.local_db_backup import (
    connect_real_postgres as _connect,
    setup_real_backup_home as _setup_real_home,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.test_scratch import short_test_directory


def _pick_contrib_extension(postgres: Any) -> str:
    with closing(_connect(postgres)) as conn:
        for candidate in ("citext", "pg_trgm", "hstore", "ltree", "cube", "unaccent"):
            row = conn.execute(
                "SELECT name FROM pg_available_extensions WHERE name = %s AND default_version IS NOT NULL",
                (candidate,),
            ).fetchone()
            if row is not None:
                return str(row[0])
        row = conn.execute(
            "SELECT name FROM pg_available_extensions WHERE name <> 'plpgsql' AND default_version IS NOT NULL ORDER BY name LIMIT 1"
        ).fetchone()
        assert row is not None, "expected at least one non-plpgsql extension in pg_available_extensions"
        return str(row[0])


def test_real_core_provenance_v1_compatibility_and_consumer_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with short_test_directory("d9a-core-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
            monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
            graph_db = "d9a_graph"
            ctrl_db = f"{graph_db}_control"
            home = root / "home"
            identity, runner = _setup_real_home(home, postgres, graph_db=graph_db)
            contrib_ext = _pick_contrib_extension(postgres)

            g_handle = postgres.create_database(graph_db)
            apply_migrations(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command)
            initialize_coordinator_control(home)
            with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                g_conn.execute(
                    'CREATE SCHEMA app_core; CREATE TABLE app_core.notes(id int PRIMARY KEY); INSERT INTO app_core.notes VALUES (42);'
                    'CREATE SCHEMA "app space_α"; CREATE TABLE "app space_α"."note items"(id int PRIMARY KEY); INSERT INTO "app space_α"."note items" VALUES (7);'
                    'CREATE SCHEMA " app"; CREATE TABLE " app"."notes "(id int); INSERT INTO " app"."notes " VALUES (8);'
                    'CREATE SCHEMA "app "; CREATE TABLE "app ".notes(id int); INSERT INTO "app ".notes VALUES (9);'
                    'CREATE SCHEMA pgxtempymetadata; CREATE TABLE pgxtempymetadata.items(id int PRIMARY KEY);'
                )

            # 1. Baseline + ordinary non-public schema dump & inspect + real outer maintenance window reuse
            with maintenance_window_for_database_drop(home, graph_db):
                with closing(_connect(postgres, ctrl_db)) as c_probe, closing(_connect(postgres, graph_db)) as g_probe:
                    assert c_probe.execute("SELECT pg_try_advisory_lock_shared(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone() == (False,)
                    assert g_probe.execute("SELECT pg_try_advisory_lock_shared(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone() == (False,)
                base_dump = dump_database(home, database=graph_db, timestamp="20261020T010000Z", command_runner=runner)
            assert base_dump.restore_supported is True and base_dump.restore_blockers == ()
            manifest = json.loads(base_dump.plan.manifest_path.read_text(encoding="utf-8"))
            assert (manifest["backup_format_version"], manifest["restore_protocol"]) == (2, "core_v1")
            assert manifest["server_provenance"]["server_version_num"] > 0 and manifest["server_provenance"]["catalog_version_no"] > 0
            assert manifest["server_provenance"]["compile_abi"]["max_data_alignment"] > 0
            assert manifest["server_provenance"]["compile_abi"]["database_block_size"] > 0
            clients = manifest["server_provenance"]["client_identities"]
            assert clients["pg_dump_version"] != "unavailable" and clients["pg_restore_version"] != "unavailable"
            assert manifest["quiescence"]["verified"] is True and manifest["quiescence"]["maintenance_window_held"] is True
            assert manifest["quiescence"]["mode"] == "reused-outer-maintenance-window"
            assert manifest["database_catalogs"][graph_db]["creation_semantics"]["template"] == "unknown"
            assert manifest["database_catalogs"][graph_db]["database_role"] == "graph"
            schema_names = [s["name"] for s in manifest["database_catalogs"][graph_db]["non_system_schemas"]]
            assert {"app space_α", " app", "app ", "app_core", "pgxtempymetadata", "public"} <= set(schema_names)
            inspected = inspect_backup(home, base_dump.plan.backup_id, command_runner=runner)
            assert inspected.checksum_verified is True and not inspected.diagnostics

            # 1b. Drift between pre/post observation and real PostgreSQL query failure / multibyte overflow refusal
            obs_calls = 0

            def drift_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                nonlocal obs_calls
                res = runner(cmd, **kwargs)
                if "repomap_d9_catalog_observation" in " ".join(str(x) for x in cmd):
                    obs_calls += 1
                    if obs_calls == 1:
                        with closing(_connect(postgres, graph_db, autocommit=True)) as mut_conn:
                            mut_conn.execute("CREATE SCHEMA transient_drift;")
                return res

            with pytest.raises(LocalDbBackupError) as drift_exc:
                dump_database(home, database=graph_db, timestamp="20261020T010200Z", command_runner=drift_runner)
            assert drift_exc.value.diagnostics[0].code == "backup-observation-drift"
            with closing(_connect(postgres, graph_db, autocommit=True)) as clean_conn:
                clean_conn.execute("DROP SCHEMA IF EXISTS transient_drift;")

            def sql_err_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                if "repomap_d9_catalog_observation" in " ".join(str(x) for x in cmd):
                    mut_cmd = [tok.replace("version()", "(1/0)::text", 1) for tok in cmd]
                    return runner(mut_cmd, **kwargs)
                return runner(cmd, **kwargs)

            with pytest.raises(LocalDbBackupError) as sql_err_exc:
                dump_database(home, database=graph_db, timestamp="20261020T010230Z", command_runner=sql_err_runner)
            assert sql_err_exc.value.diagnostics[0].code == "backup-observation-incomplete"

            ovf_stdout: list[bytes] = []

            def overflow_obs_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                if "repomap_d9_catalog_observation" in " ".join(str(x) for x in cmd):
                    mut_cmd = [tok.replace("version()", "repeat('α', 1100000)", 1) for tok in cmd]
                    res = runner(mut_cmd, **kwargs)
                    ovf_stdout.append(res.stdout if isinstance(res.stdout, bytes) else str(res.stdout).encode("utf-8"))
                    return res
                return runner(cmd, **kwargs)

            with pytest.raises(LocalDbBackupError) as ovf_exc:
                dump_database(home, database=graph_db, timestamp="20261020T010300Z", command_runner=overflow_obs_runner)
            assert ovf_exc.value.diagnostics[0].code == "backup-observation-incomplete"
            assert ovf_stdout and ovf_stdout[0].startswith(b"OVERFLOW:") and len(ovf_stdout[0]) < 128
            for ts in ("20261020T010230Z", "20261020T010300Z"):
                assert not (home / "backups" / identity.home_hash / graph_db / ts).exists()
            assert list((home / "backups").rglob("*.incomplete*")) == []
            with closing(_connect(postgres, graph_db)) as g_conn:
                assert g_conn.execute("SELECT id FROM app_core.notes").fetchall() == [(42,)]

            # 2. Legacy v1 baseline compatibility (preserves v1 manifest untouched, restores app_core)
            v1_dir = home / "backups" / identity.home_hash / graph_db / "20261020T010500Z"
            v1_dir.mkdir(parents=True)
            dump_bytes = (base_dump.plan.backup_path / "dump.pgcustom").read_bytes()
            assert dump_bytes[:5] == b"PGDMP"
            (v1_dir / "dump.pgcustom").write_bytes(dump_bytes)
            v1_manifest = {
                "backup_format_version": 1, "backup_id": f"{identity.home_hash}--{graph_db}--20261020T010500Z",
                "backup_kind": "manual-dump", "runtime_id": identity.home_hash, "database": graph_db, "databases": [graph_db],
                "timestamp": "20261020T010500Z", "dump_format": "pgcustom", "restore_supported": True,
                "dump_files": [{"name": "dump.pgcustom", "size_bytes": len(dump_bytes), "sha256": hashlib.sha256(dump_bytes).hexdigest()}],
            }
            v1_text = json.dumps(v1_manifest, sort_keys=True)
            (v1_dir / "manifest.json").write_text(v1_text, encoding="utf-8")

            with closing(_connect(postgres, autocommit=True)) as adm:
                adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
            init_res = init_database_from_dump(home, database=graph_db, backup=v1_dir, command_runner=runner)
            assert init_res.result == "success" and init_res.dump_restored is True
            assert (v1_dir / "manifest.json").read_text(encoding="utf-8") == v1_text
            with closing(_connect(postgres, graph_db)) as g_conn:
                assert g_conn.execute("SELECT id FROM app_core.notes").fetchone() == (42,)
                assert g_conn.execute('SELECT id FROM "app space_α"."note items"').fetchone() == (7,)
                assert g_conn.execute('SELECT id FROM " app"."notes "').fetchone() == (8,)
                assert g_conn.execute('SELECT id FROM "app ".notes').fetchone() == (9,)

            # 3. Install real non-baseline extension chain (cube -> earthdistance) in custom schema
            with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                assert g_conn.execute(
                    "SELECT count(*) FROM pg_available_extensions WHERE name IN ('cube', 'earthdistance') AND default_version IS NOT NULL"
                ).fetchone() == (2,)
                g_conn.execute("CREATE SCHEMA custom_ext; CREATE EXTENSION cube SCHEMA custom_ext; CREATE EXTENSION earthdistance SCHEMA custom_ext;")

            ext_dump = dump_database(home, database=graph_db, timestamp="20261020T020000Z", command_runner=runner)
            assert ext_dump.restore_supported is False
            assert {"extension-not-allowlisted", "extension-schema-unsupported"} <= set(ext_dump.restore_blockers)
            assert "restore_supported=false" in ext_dump.plan.restore_path.read_text(encoding="utf-8")
            ext_manifest = json.loads(ext_dump.plan.manifest_path.read_text(encoding="utf-8"))
            ext_items = ext_manifest["database_catalogs"][graph_db]["installed_extensions"]
            ext_names = [e["name"] for e in ext_items]
            assert ext_names.index("cube") < ext_names.index("earthdistance")
            earth_item = next(e for e in ext_items if e["name"] == "earthdistance")
            assert earth_item["prerequisite_extensions"] == ["cube"]

            with pytest.raises(LocalDbBackupError) as drop_exc:
                drop_database(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261020T020500Z", command_runner=runner)
            assert "backup-extension-restore-unsupported" in [d.code for d in drop_exc.value.diagnostics]

            # Legacy v1 archive containing real non-baseline extension in PGDMP TOC is refused before CREATE DATABASE
            v1_ext_dir = home / "backups" / identity.home_hash / graph_db / "20261020T021000Z"
            v1_ext_dir.mkdir(parents=True)
            ext_bytes = (ext_dump.plan.backup_path / "dump.pgcustom").read_bytes()
            (v1_ext_dir / "dump.pgcustom").write_bytes(ext_bytes)
            (v1_ext_dir / "manifest.json").write_text(
                json.dumps(dict(v1_manifest, backup_id=f"{identity.home_hash}--{graph_db}--20261020T021000Z", dump_files=[{"name": "dump.pgcustom", "size_bytes": len(ext_bytes), "sha256": hashlib.sha256(ext_bytes).hexdigest()}])),
                encoding="utf-8",
            )
            with closing(_connect(postgres, autocommit=True)) as adm:
                adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
            for candidate_backup in (ext_dump.plan.backup_path, v1_ext_dir):
                with pytest.raises(LocalDbBackupError) as init_refusal:
                    init_database_from_dump(home, database=graph_db, backup=candidate_backup, command_runner=runner)
                assert "backup-extension-restore-unsupported" in [d.code for d in init_refusal.value.diagnostics]
            with closing(_connect(postgres)) as adm:
                assert adm.execute("SELECT 1 FROM pg_database WHERE datname = %s", (graph_db,)).fetchone() is None

            # 4. Coordinated backup where graph_db is clean and ctrl_db has non-baseline extension
            init_database_from_dump(home, database=graph_db, backup=base_dump.plan.backup_path, command_runner=runner)
            with closing(_connect(postgres, ctrl_db, autocommit=True)) as c_conn:
                c_conn.execute(f'CREATE EXTENSION "{contrib_ext}";')
            coord_dump = dump_all_databases(home, timestamp="20261020T030000Z", command_runner=runner, stable_recovery_point=True)
            assert coord_dump.restore_supported is False
            with closing(_connect(postgres, autocommit=True)) as adm:
                adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                adm.execute(f'DROP DATABASE "{ctrl_db}" WITH (FORCE)')

            with pytest.raises(LocalDbBackupError) as coord_refusal:
                restore_coordinated_backup(home, backup=coord_dump.plan.backup_path, command_runner=runner)
            assert "backup-extension-restore-unsupported" in [d.code for d in coord_refusal.value.diagnostics]
            with closing(_connect(postgres)) as adm:
                assert adm.execute("SELECT datname FROM pg_database WHERE datname = ANY(%s)", ([graph_db, ctrl_db],)).fetchall() == []

            single_extract = init_database_from_dump(home, database=graph_db, backup=coord_dump.plan.backup_path, command_runner=runner)
            assert single_extract.result == "success" and single_extract.dump_restored is True


def test_real_schema_upgrade_control_upgrade_and_release_cluster_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with short_test_directory("d9a-upg-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
            monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
            graph_db = "d9a_upg_graph"
            ctrl_db = f"{graph_db}_control"
            home = root / "home"
            _, runner = _setup_real_home(home, postgres, graph_db=graph_db)
            contrib_ext = _pick_contrib_extension(postgres)

            g_handle = postgres.create_database(graph_db)
            migrations = discover_migrations(default_rdbms_root())
            run_psql(
                [g_handle.psql_command, *g_handle.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
                input_text=_migration_script(migrations[:1], initialize_ledger=True),
            )
            initialize_coordinator_control(home)

            # Positive release-cluster upgrade on baseline behind graph + preledger control DB
            import repomap_kg.runtime._backup_support as bs_mod
            import repomap_kg.runtime.release_cluster as rc_mod

            admin_root = root / "admin"
            admin_root.mkdir(mode=0o700)
            monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(admin_root))
            pg_dump_bin = shutil.which("pg_dump")
            pg_restore_bin = shutil.which("pg_restore")
            monkeypatch.setattr(rc_mod, "PACKAGED_PG_DUMP", pg_dump_bin)
            monkeypatch.setattr(rc_mod, "PACKAGED_PG_RESTORE", pg_restore_bin)
            monkeypatch.setattr(bs_mod, "PACKAGED_PG_RESTORE", pg_restore_bin)
            with closing(_connect(postgres, ctrl_db, autocommit=True)) as c_conn:
                c_conn.execute("DROP TABLE repomap_control_schema_migrations;")
            rc_pos = initialize_release_cluster(home)
            assert rc_pos["result"] == "ready"
            assert graph_schema_readiness(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command).status is GraphSchemaStatus.CURRENT
            assert LocalControlAuthority(home).control_store().schema_readiness().status.value == "current"

            # Revert graph_db to behind and install non-baseline extension to verify upgrade refusals
            with closing(_connect(postgres, autocommit=True)) as adm:
                adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
            g_handle = postgres.create_database(graph_db)
            run_psql(
                [g_handle.psql_command, *g_handle.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
                input_text=_migration_script(migrations[:1], initialize_ledger=True),
            )
            with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                g_conn.execute(f'CREATE EXTENSION "{contrib_ext}";')

            with pytest.raises(LocalDbBackupError) as g_upg_exc:
                upgrade_graph_schema(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261020T040000Z", command_runner=runner)
            assert "backup-extension-restore-unsupported" in [d.code for d in g_upg_exc.value.diagnostics]
            assert graph_schema_readiness(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command).status is GraphSchemaStatus.BEHIND

            # Each independent attempt owns a fresh archive root. Otherwise a
            # same-second positive backup can mask the extension refusal.
            refusal_admin_root = root / "admin-refusal"
            refusal_admin_root.mkdir(mode=0o700)
            monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(refusal_admin_root))
            with pytest.raises(ReleaseClusterError, match="release_cluster_upgrade_backup_invalid") as rc_exc:
                initialize_release_cluster(home, control_initializer=lambda _h: {"command": "coordinator-control-init", "result": "ready"})
            assert isinstance(rc_exc.value.__cause__, LocalDbBackupError)
            assert "backup-extension-restore-unsupported" in [d.code for d in rc_exc.value.__cause__.diagnostics]
            assert graph_schema_readiness(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command).status is GraphSchemaStatus.BEHIND

            with closing(_connect(postgres, ctrl_db, autocommit=True)) as c_conn:
                c_conn.execute("DROP TABLE repomap_control_schema_migrations;")
                c_conn.execute(f'CREATE SCHEMA ext_s; CREATE EXTENSION "{contrib_ext}" SCHEMA ext_s;')

            def _dump_ctrl(repo_map_home: str | Path | None, *, database: str, reason: str | None = None, timestamp: str | None = None) -> Any:
                return dump_database(repo_map_home, database=database, reason=reason, timestamp=timestamp, command_runner=runner)

            with pytest.raises(CoordinatorControlError, match="coordinator_control_upgrade_failed") as cc_exc:
                upgrade_coordinator_control(
                    home, backup_first=True, confirmed=True, timestamp="20261020T040500Z",
                    dump_function=_dump_ctrl, inspect_function=lambda h, p: inspect_backup(h, p, command_runner=runner),
                )
            assert isinstance(cc_exc.value.__cause__, LocalDbBackupError)
            assert "backup-extension-restore-unsupported" in [d.code for d in cc_exc.value.__cause__.diagnostics]
            assert LocalControlAuthority(home).control_store().schema_readiness().status.value == "preledger"


@pytest.mark.requires_pgvector
def test_pgvector_profile_real_extension_provenance_and_consumer_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9a-vec-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
            monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
            graph_db = "d9a_vec_graph"
            home = root / "home"
            _, runner = _setup_real_home(home, postgres, graph_db=graph_db)
            g_handle = postgres.create_database(graph_db)
            apply_migrations(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command)
            initialize_coordinator_control(home)
            with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                g_conn.execute("CREATE EXTENSION vector VERSION '0.8.7';")
                g_conn.execute("CREATE TABLE public.vec_items(id int PRIMARY KEY, emb vector(3));")

            res = dump_database(home, database=graph_db, timestamp="20261020T050000Z", command_runner=runner)
            assert res.restore_supported is False
            assert {"extension-not-allowlisted", "extension-dependency-unsupported"} <= set(res.restore_blockers)
            manifest = json.loads(res.plan.manifest_path.read_text(encoding="utf-8"))
            exts = {e["name"]: e for e in manifest["database_catalogs"][graph_db]["installed_extensions"]}
            assert "vector" in exts and exts["vector"]["version"] == "0.8.7"
            assert manifest["database_catalogs"][graph_db]["extension_dependency_summary"]["edge_count"] >= 1

            with pytest.raises(LocalDbBackupError) as drop_exc:
                drop_database(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261020T050500Z", command_runner=runner)
            assert "backup-extension-restore-unsupported" in [d.code for d in drop_exc.value.diagnostics]
