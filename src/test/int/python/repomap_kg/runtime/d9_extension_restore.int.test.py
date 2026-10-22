"""Containerized core integration tests for ADR 0084 D9-B extension_v2 restore."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from repomap_kg.coordinator._lifecycle_upgrade import upgrade_coordinator_control
from repomap_kg.coordinator.local_lifecycle import LocalControlAuthority, initialize_coordinator_control
from repomap_kg.runtime.backup import drop_database, dump_all_databases, dump_database, init_database_from_dump, inspect_backup
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import restore_coordinated_backup
from repomap_kg.runtime.release_cluster import initialize_release_cluster
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema
from repomap_kg.storage import GraphSchemaStatus, default_rdbms_root, discover_migrations, graph_schema_readiness, run_psql
from repomap_kg.storage.main import _migration_script
from repomap_test_support.d9_extension_policies import (
    control_extension_policy, hide_extension_script_in_container, installed_synthetic_extensions,
    probe_live_container_qualification, synthetic_multilevel_extension_policy, tamper_extension_script_in_container,
)
from repomap_test_support.d9_extension_restore import (
    clean_template_reference, database_names, observe_template_baseline_in_container, owned_d9_postgres_cluster, seed_synthetic_graph,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

BASELINE_ROLES = ("repomap_read_status", "repomap_refresh_publication", "repomap_coordinator_control")


def _drop_baseline_roles(postgres: Any) -> None:
    with closing(_connect(postgres, autocommit=True)) as adm:
        for role_name in BASELINE_ROLES:
            adm.execute(f'DROP ROLE IF EXISTS "{role_name}";')


def _assert_no_private_toc_dirs(runner: Any, container_name: str) -> None:
    res = runner(["docker", "exec", "-i", container_name, "find", "/tmp", "-maxdepth", "1", "-name", "repomap-ext-toc-*"], capture_output=True, text=True, check=False)
    assert res.returncode == 0 and res.stdout.strip() == "", f"private TOC residue: {res.stdout!r} rc={res.returncode}"


def _refused(code: str, home: Path, backup: Path, runner: Any, policy: Any, postgres: Any, before: list[str]) -> None:
    with pytest.raises(LocalDbBackupError) as exc:
        init_database_from_dump(home, database="d9b_graph", backup=backup, command_runner=runner, extension_restore_policy=policy)
    codes = [d.code for d in exc.value.diagnostics]
    assert code in codes, f"expected {code}, got {codes}"
    assert database_names(postgres) == before, "refusal must happen before any CREATE DATABASE"


def test_d9b_multilevel_synthetic_extension_restore_and_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-core-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        graph_db, ctrl_db, home = "d9b_graph", "d9b_graph_control", root / "home"
        reference = clean_template_reference(root)
        receipts: list[tuple[str, str]] = []
        with owned_d9_postgres_cluster(home, graph_db=graph_db) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            with installed_synthetic_extensions("docker", identity.postgres_container, runner=runner, receipts=receipts):
                qual = probe_live_container_qualification(identity.postgres_container, user=postgres.user, template_baseline_sha256=reference)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, artifact_qualification=qual)
                seed_synthetic_graph(postgres, graph_db)
                core_dump = dump_database(home, database=graph_db, timestamp="20261021T010000Z", command_runner=runner)
                assert core_dump.restore_supported is False and "extension-restore-protocol-unimplemented" in core_dump.restore_blockers
                ext_dump = dump_database(home, database=graph_db, timestamp="20261021T010100Z", command_runner=runner, extension_restore_policy=policy)
                assert ext_dump.restore_supported is True and ext_dump.restore_blockers == (), f"blockers: {ext_dump.restore_blockers}"
                manifest = json.loads(ext_dump.plan.manifest_path.read_text(encoding="utf-8"))
                assert manifest["database_catalogs"][graph_db]["creation_semantics"]["template"] == "unknown", "source template stays an observation"
                assert inspect_backup(home, ext_dump.plan.backup_id, command_runner=runner, extension_restore_policy=policy).diagnostics == ()
                archive_file = ext_dump.plan.backup_path / "dump.pgcustom"
                archive_sha_before = hashlib.sha256(archive_file.read_bytes()).hexdigest()
                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                _drop_baseline_roles(postgres)
                before = database_names(postgres)
                backup = ext_dump.plan.backup_path

                _refused("backup-extension-restore-unsupported", home, backup, runner, None, postgres, before)
                stale = synthetic_multilevel_extension_policy(owner=postgres.user, policy_id="stale-policy-v2", artifact_qualification=qual)
                _refused("backup-extension-restore-unsupported", home, backup, runner, stale, postgres, before)
                restore = hide_extension_script_in_container("docker", identity.postgres_container, "ext_alpha--1.0.sql", runner=runner)
                try:
                    _refused("restore-extension-version-unavailable", home, backup, runner, policy, postgres, before)
                finally:
                    restore()
                orig = deepcopy(manifest)
                try:
                    for mutate, code in (
                        (lambda m: m["artifact_provenance"].__setitem__("container_image_id", "unavailable"), "restore-target-artifact-unqualified"),
                        (lambda m: m["database_catalogs"][graph_db]["creation_semantics"].update(datlocprovider="i", daticulocale="und-x-icu"), "restore-creation-semantics-incompatible"),
                        (lambda m: m["quiescence"].__setitem__("before_after_fingerprint_matched", False), "backup-restore-unsupported"),
                        (lambda m: m["server_provenance"]["client_identities"].__setitem__("pg_restore_version", "unavailable"), "backup-extension-restore-unsupported"),
                    ):
                        bad = deepcopy(orig)
                        mutate(bad)
                        ext_dump.plan.manifest_path.write_text(json.dumps(bad), encoding="utf-8")
                        _refused(code, home, backup, runner, policy, postgres, before)
                finally:
                    ext_dump.plan.manifest_path.write_text(json.dumps(orig), encoding="utf-8")

                with closing(_connect(postgres, "template1", autocommit=True)) as tpl:
                    tpl.execute("COMMENT ON SCHEMA public IS 'administrator modified'; GRANT CREATE ON SCHEMA public TO PUBLIC;")
                try:
                    assert observe_template_baseline_in_container(identity.postgres_container, user=postgres.user) != reference
                    _refused("restore-template-baseline-mismatch", home, backup, runner, policy, postgres, before)
                finally:
                    with closing(_connect(postgres, "template1", autocommit=True)) as tpl:
                        tpl.execute("COMMENT ON SCHEMA public IS 'standard public schema'; REVOKE CREATE ON SCHEMA public FROM PUBLIC;")
                assert observe_template_baseline_in_container(identity.postgres_container, user=postgres.user) == reference

                tamper_extension_script_in_container("docker", identity.postgres_container, "ext_alpha--1.0.sql", runner=runner)
                _refused("restore-target-artifact-unqualified", home, backup, runner, policy, postgres, before)

            with installed_synthetic_extensions("docker", identity.postgres_container, runner=runner, receipts=receipts):
                init_res = init_database_from_dump(home, database=graph_db, backup=backup, command_runner=runner, extension_restore_policy=policy)
                assert init_res.result == "success" and init_res.dump_restored is True
                assert hashlib.sha256(archive_file.read_bytes()).hexdigest() == archive_sha_before
                _assert_no_private_toc_dirs(runner, identity.postgres_container)
                assert not list((home / "runtime").glob(".restore-intents-*")), "a successful restore leaves no intent ledger"
                with closing(_connect(postgres, graph_db)) as g:
                    assert g.execute("SELECT obj_description(oid, 'pg_extension') FROM pg_extension WHERE extname = 'ext_gamma'").fetchone() == ("custom gamma comment",)
                    assert g.execute("SELECT obj_description(oid, 'pg_extension') FROM pg_extension WHERE extname = 'ext_beta'").fetchone() == (None,)
                    assert g.execute("SELECT extversion FROM pg_extension WHERE extname = 'ext_alpha'").fetchone() == ("1.0",), "recorded version, not the target default 1.1"
                    assert g.execute("SELECT coalesce(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE datname = current_database()").fetchone() == ("",)

                initialize_coordinator_control(home)
                coord_dump = dump_all_databases(home, timestamp="20261021T010500Z", command_runner=runner, stable_recovery_point=True, extension_restore_policy=policy)
                assert coord_dump.restore_supported is True
                target_home = root / "target_home"
                with owned_d9_postgres_cluster(target_home, graph_db=graph_db, password=str(postgres.password)) as (target_id, target_pg, target_runner):
                    target_backup = target_home / "backups" / "imported" / coord_dump.plan.backup_path.name
                    target_backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    shutil.copytree(coord_dump.plan.backup_path, target_backup)
                    with installed_synthetic_extensions("docker", target_id.postgres_container, runner=target_runner, receipts=receipts):
                        src_ids = [subprocess.run(["docker", "inspect", "--format", "{{.Id}}", c], capture_output=True, text=True, check=True).stdout.strip() for c in (identity.postgres_container, target_id.postgres_container)]
                        assert src_ids[0] != src_ids[1], "source and target are separate real containers"
                        with closing(_connect(postgres)) as s_adm, closing(_connect(target_pg)) as t_adm:
                            sql = "SELECT system_identifier::text FROM pg_control_system()"
                            assert s_adm.execute(sql).fetchone() != t_adm.execute(sql).fetchone(), "source and target are separate clusters"
                            assert t_adm.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(BASELINE_ROLES),)).fetchall() == []
                        target_before = database_names(target_pg)
                        with closing(_connect(target_pg, "template1", autocommit=True)) as tpl:
                            tpl.execute("CREATE FUNCTION public.admin_injected() RETURNS int LANGUAGE sql AS 'SELECT 1';")
                        with pytest.raises(LocalDbBackupError) as tpl_exc:
                            restore_coordinated_backup(target_home, backup=target_backup, command_runner=target_runner, extension_restore_policy=policy)
                        assert "restore-template-baseline-mismatch" in [d.code for d in tpl_exc.value.diagnostics]
                        assert database_names(target_pg) == target_before, "complete-set refusal before any creation"
                        with closing(_connect(target_pg, "template1", autocommit=True)) as tpl:
                            tpl.execute("DROP FUNCTION public.admin_injected();")
                        coord_res = restore_coordinated_backup(target_home, backup=target_backup, command_runner=target_runner, extension_restore_policy=policy)
                        assert coord_res.result == "success" and set(coord_res.databases) == {graph_db, ctrl_db}
                        _assert_no_private_toc_dirs(target_runner, target_id.postgres_container)
                        with closing(_connect(target_pg, graph_db)) as tg:
                            assert tg.execute("SELECT ext_gamma_s.gamma_probe()").fetchone() == ("1.0:beta-1.0:gamma-1.0",)
                            assert tg.execute("SELECT id, tag FROM app_ext.items").fetchall() == [(1, "alpha-beta-gamma")]
                            assert tg.execute("SELECT last_value, is_called FROM app_ext.item_seq").fetchone() == (50, True)

                cfg_policy = synthetic_multilevel_extension_policy(owner=postgres.user, include_cfg=True, policy_id="synthetic-cfg-v1", artifact_qualification=qual)
                with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                    g_conn.execute("CREATE SCHEMA ext_cfg_s; CREATE EXTENSION ext_cfg WITH SCHEMA ext_cfg_s VERSION '1.0'; INSERT INTO ext_cfg_s.cfg_items (k, is_user) VALUES ('k1', true);")
                cfg_dump = dump_database(home, database=graph_db, timestamp="20261021T011000Z", command_runner=runner, extension_restore_policy=cfg_policy)
                assert cfg_dump.restore_supported is False and "extension-config-table-unsupported" in cfg_dump.restore_blockers
                with pytest.raises(LocalDbBackupError) as cfg_drop_exc:
                    drop_database(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261021T011100Z", command_runner=runner, extension_restore_policy=cfg_policy)
                assert "backup-extension-config-unsupported" in [d.code for d in cfg_drop_exc.value.diagnostics]
        assert receipts and all(outcome in ("REMOVED", "ABSENT") for _name, outcome in receipts), f"synthetic file cleanup receipts: {receipts}"


def test_d9b_backup_first_upgrade_and_drop_consumers_with_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-upg-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        graph_db, ctrl_db, home = "d9b_upg_graph", "d9b_upg_graph_control", root / "home"
        reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=graph_db) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            with installed_synthetic_extensions("docker", identity.postgres_container, runner=runner):
                qual = probe_live_container_qualification(identity.postgres_container, user=postgres.user, template_baseline_sha256=reference)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, include_beta=False, include_gamma=False, artifact_qualification=qual)
                g_handle = postgres.create_database(graph_db)
                migrations = discover_migrations(default_rdbms_root())
                run_psql([g_handle.psql_command, *g_handle.psql_args, "-X", "-v", "ON_ERROR_STOP=1"], input_text=_migration_script(migrations[:1], initialize_ledger=True))
                initialize_coordinator_control(home)
                with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                    g_conn.execute("CREATE SCHEMA ext_alpha_s; CREATE EXTENSION ext_alpha WITH SCHEMA ext_alpha_s VERSION '1.0';")
                upg_res = upgrade_graph_schema(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261021T020000Z", command_runner=runner, extension_restore_policy=policy)
                assert upg_res.result == "success"
                assert graph_schema_readiness(default_rdbms_root(), g_handle.psql_args, psql_command=g_handle.psql_command).status is GraphSchemaStatus.CURRENT

                import repomap_kg.runtime._backup_support as bs_mod
                import repomap_kg.runtime.release_cluster as rc_mod
                admin_root = root / "admin-d9b"
                admin_root.mkdir(mode=0o700)
                monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(admin_root))
                pg_dump_bin, pg_restore_bin = shutil.which("pg_dump"), shutil.which("pg_restore")
                assert pg_dump_bin is not None and pg_restore_bin is not None
                monkeypatch.setattr(rc_mod, "PACKAGED_PG_DUMP", pg_dump_bin)
                monkeypatch.setattr(rc_mod, "PACKAGED_PG_RESTORE", pg_restore_bin)
                monkeypatch.setattr(bs_mod, "PACKAGED_PG_RESTORE", pg_restore_bin)
                host_clients = {subprocess.run([b, "--version"], capture_output=True, text=True, check=True).stdout.split()[2] for b in (pg_dump_bin, pg_restore_bin)}

                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                g_handle = postgres.create_database(graph_db)
                run_psql([g_handle.psql_command, *g_handle.psql_args, "-X", "-v", "ON_ERROR_STOP=1"], input_text=_migration_script(migrations[:1], initialize_ledger=True))
                with closing(_connect(postgres, graph_db, autocommit=True)) as g_conn:
                    g_conn.execute("CREATE SCHEMA ext_alpha_s; CREATE EXTENSION ext_alpha WITH SCHEMA ext_alpha_s VERSION '1.0';")
                with closing(_connect(postgres, ctrl_db, autocommit=True)) as c_conn:
                    c_conn.execute("DROP TABLE repomap_control_schema_migrations;")
                rc_qual = replace(qual, allowed_client_versions=tuple(sorted(host_clients)), allowed_client_majors=tuple(sorted({int(v.split(".")[0]) for v in host_clients})))
                rc_policy = synthetic_multilevel_extension_policy(owner=postgres.user, include_beta=False, include_gamma=False, artifact_qualification=rc_qual)
                assert initialize_release_cluster(home, extension_restore_policy=rc_policy)["result"] == "ready"
                assert LocalControlAuthority(home).control_store().schema_readiness().status.value == "current"

                ctrl_policy = control_extension_policy(postgres.user, qual)
                with closing(_connect(postgres, ctrl_db, autocommit=True)) as c_conn:
                    c_conn.execute("DROP TABLE repomap_control_schema_migrations; CREATE SCHEMA ext_alpha_s; CREATE EXTENSION ext_alpha WITH SCHEMA ext_alpha_s VERSION '1.0';")
                cc_res = upgrade_coordinator_control(
                    home, backup_first=True, confirmed=True, timestamp="20261021T020500Z",
                    dump_function=lambda h, *, database, reason=None, timestamp=None, extension_restore_policy=None: dump_database(h, database=database, reason=reason, timestamp=timestamp, command_runner=runner, extension_restore_policy=extension_restore_policy),
                    inspect_function=lambda h, p, *, extension_restore_policy=None: inspect_backup(h, p, command_runner=runner, extension_restore_policy=extension_restore_policy),
                    extension_restore_policy=ctrl_policy,
                )
                assert cc_res["result"] == "ready"
                drop_res = drop_database(home, database=graph_db, backup_first=True, confirmed=True, timestamp="20261021T021000Z", command_runner=runner, extension_restore_policy=policy)
                assert drop_res.result == "success" and drop_res.database_dropped is True
