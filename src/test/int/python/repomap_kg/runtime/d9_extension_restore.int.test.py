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
from repomap_kg.runtime._extension_restore_qualification import qualify_server_provenance
from repomap_kg.runtime.backup import drop_database, dump_all_databases, dump_database, init_database_from_dump, inspect_backup
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import restore_coordinated_backup
from repomap_kg.runtime.release import POSTGRES_RELEASE_IMAGE
from repomap_kg.runtime.release_cluster import initialize_release_cluster
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema
from repomap_kg.storage import (
    GraphSchemaStatus, apply_migrations, default_rdbms_root, discover_migrations, graph_schema_readiness, run_psql,
)
from repomap_kg.storage.main import _migration_script
from repomap_test_support.d9_extension_policies import (
    control_extension_policy, hide_extension_script_in_container, installed_synthetic_extensions,
    probe_live_container_qualification, synthetic_multilevel_extension_policy, tamper_extension_script_in_container,
)
from repomap_test_support.d9_extension_restore import (
    SYNTHETIC_GRAPH_SQL, clean_template_reference, database_names, observe_template_baseline_in_container,
    owned_d9_postgres_cluster, postmaster_crash_lines, seed_synthetic_graph,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

BASELINE_ROLES = ("repomap_read_status", "repomap_refresh_publication", "repomap_coordinator_control")
TRIXIE_SERVER_VERSION = "16.15 (Debian 16.15-1.pgdg13+2)"  # observed on POSTGRES_RELEASE_IMAGE


def _drop_baseline_roles(postgres: Any) -> None:
    with closing(_connect(postgres, autocommit=True)) as adm:
        for role_name in BASELINE_ROLES:
            adm.execute(f'DROP ROLE IF EXISTS "{role_name}";')


def _assert_no_private_toc_dirs(runner: Any, container_name: str) -> None:
    res = runner(["docker", "exec", "-i", container_name, "find", "/tmp", "-maxdepth", "1", "-name", "repomap-ext-toc-*"], capture_output=True, text=True, check=False)
    assert res.returncode == 0 and res.stdout.strip() == "", f"private TOC residue: {res.stdout!r} rc={res.returncode}"


def _refused(
    code: str, home: Path, backup: Path, runner: Any, policy: Any, postgres: Any, before: list[str],
    *, database: str = "d9b_graph",
) -> None:
    with pytest.raises(LocalDbBackupError) as exc:
        init_database_from_dump(
            home, database=database, backup=backup, command_runner=runner, extension_restore_policy=policy)
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


_CREATION_FACTS_SQL = ("SELECT datlocprovider::text, datcollate, datctype, daticulocale, datcollversion, "
                       "pg_database_collation_actual_version(oid) FROM pg_database WHERE datname = %s")


def _creation_facts(postgres: Any, database: str) -> tuple[Any, ...]:
    with closing(_connect(postgres, autocommit=True)) as adm:
        return tuple(adm.execute(_CREATION_FACTS_SQL, (database,)).fetchone())


def _graph_content(postgres: Any, database: str) -> tuple[Any, ...]:
    with closing(_connect(postgres, database)) as g:
        return (g.execute("SELECT id, tag FROM app_ext.items ORDER BY id").fetchall(),
                g.execute("SELECT last_value, is_called FROM app_ext.item_seq").fetchone(),
                g.execute(
                    "SELECT extname, extversion FROM pg_extension WHERE extname LIKE 'ext_%%' ORDER BY 1"
                ).fetchall())

def _exact_trixie_container(container: str) -> dict[str, str]:
    """The owned server runs the exact preloaded release pin; nothing is pulled (--pull=never)."""
    run_dk = lambda *argv: subprocess.run(["docker", *argv], capture_output=True, text=True, check=True).stdout
    inspect = lambda *argv: json.loads(run_dk(*argv))[0]
    item = inspect("inspect", container)
    digests = inspect("image", "inspect", item["Image"]).get("RepoDigests") or []
    release = run_dk("exec", container, "cat", "/etc/os-release")
    listed = run_dk(
        "exec", container, "dpkg-query", "-W", "-f=${db:Status-Abbrev}${Package} ${Version}\\n", "libicu[0-9]*")
    icu = [part for line in listed.splitlines() if line.startswith("ii ") for part in line.split()[1:]]
    assert item["Config"]["Image"] == POSTGRES_RELEASE_IMAGE, item["Config"]["Image"]
    assert any(d.endswith("@" + POSTGRES_RELEASE_IMAGE.split("@", 1)[1]) for d in digests), digests
    assert "VERSION_CODENAME=trixie" in release.splitlines() and len(icu) == 2, (release, icu)
    return {"image_id": item["Image"], "icu_package": icu[0], "icu_version": icu[1]}


def test_d12_trixie_backup_restore_and_collation_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0091 D9 compatibility on the exact Trixie release server, separate disposable clusters only."""
    require_postgres_binaries()
    with short_test_directory("d12t-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        graph_db, home = "d12t_graph", root / "home"
        reference = clean_template_reference(root, image=POSTGRES_RELEASE_IMAGE)
        receipts: list[tuple[str, str]] = []
        with owned_d9_postgres_cluster(
            home, graph_db=graph_db, image=POSTGRES_RELEASE_IMAGE,
        ) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            facts = _exact_trixie_container(identity.postgres_container)
            assert observe_template_baseline_in_container(identity.postgres_container, user=postgres.user) == reference
            assert _creation_facts(postgres, "template1") == ("c", "C", "C", None, None, None), "product C template1"
            with closing(_connect(postgres, autocommit=True)) as adm:
                icu_root = adm.execute("SELECT collversion, pg_collation_actual_version(oid) FROM pg_collation "
                                       "WHERE collname = 'und-x-icu' AND collprovider = 'i'").fetchone()
            assert icu_root is not None and icu_root[1], f"the Trixie server's ICU root collation: {icu_root} {facts}"
            cid = identity.postgres_container
            with installed_synthetic_extensions("docker", cid, runner=runner, receipts=receipts):
                qual = probe_live_container_qualification(cid, user=postgres.user, template_baseline_sha256=reference)
                assert qual.allowed_server_versions == (TRIXIE_SERVER_VERSION,)
                assert qual.allowed_engine_image_ids == (facts["image_id"],)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, artifact_qualification=qual)
                # C-locale round trip: the product's own template1 route, backup first, unchanged archive and content.
                seed_synthetic_graph(postgres, graph_db)
                source_facts, source_content = _creation_facts(postgres, graph_db), _graph_content(postgres, graph_db)
                assert source_facts == ("c", "C", "C", None, None, None), source_facts
                c_dump = dump_database(
                    home, database=graph_db, timestamp="20261023T010000Z",
                    command_runner=runner, extension_restore_policy=policy)
                assert c_dump.restore_supported is True and c_dump.restore_blockers == (), c_dump.restore_blockers
                c_manifest = json.loads(c_dump.plan.manifest_path.read_text(encoding="utf-8"))
                assert c_manifest["server_provenance"]["server_version"] == qual.allowed_server_versions[0]
                semantics = c_manifest["database_catalogs"][graph_db]["creation_semantics"]
                assert (semantics["datlocprovider"], semantics["datcollate"], semantics["datcollversion"]) == (
                    "c", "C", None)
                archive = c_dump.plan.backup_path / "dump.pgcustom"
                c_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                _drop_baseline_roles(postgres)
                before = database_names(postgres)

                # Deliberately tampered metadata, not a migration: a fabricated source collation version must refuse.
                manifest_bytes = c_dump.plan.manifest_path.read_bytes()
                tampered = json.loads(manifest_bytes)
                tampered["database_catalogs"][graph_db]["creation_semantics"]["datcollversion"] = "153.128"
                c_dump.plan.manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
                c_bkp = c_dump.plan.backup_path
                try:
                    _refused(
                        "restore-creation-semantics-incompatible", home, c_bkp,
                        runner, policy, postgres, before, database=graph_db)
                finally:
                    c_dump.plan.manifest_path.write_bytes(manifest_bytes)
                # DELIBERATELY TAMPERED ABI METADATA, not an ABI migration: a test-only qualification copy admits one
                # synthetic second ABI (declaration binding unchanged); the source manifest claims it, so source and
                # actual target are each admitted but differ, and the cross-ABI guard refuses before CREATE DATABASE.
                synthetic_abi = "repomap-test-tampered-abi"
                abi_qual = replace(qual, allowed_os_arch_abis=(*qual.allowed_os_arch_abis, synthetic_abi))
                abi_policy = replace(policy, artifact_qualification=abi_qual)
                assert abi_policy.policy_binding_record() == policy.policy_binding_record()
                assert synthetic_abi not in qual.allowed_os_arch_abis
                tampered = json.loads(manifest_bytes)
                tampered["server_provenance"]["os_arch_abi"] = synthetic_abi
                assert qualify_server_provenance(tampered["server_provenance"], abi_qual) == set()
                c_dump.plan.manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
                try:
                    _refused(
                        "restore-target-incompatible", home, c_bkp,
                        runner, abi_policy, postgres, before, database=graph_db)
                finally:
                    c_dump.plan.manifest_path.write_bytes(manifest_bytes)
                assert c_dump.plan.manifest_path.read_bytes() == manifest_bytes
                assert hashlib.sha256(archive.read_bytes()).hexdigest() == c_sha
                restored = init_database_from_dump(
                    home, database=graph_db, backup=c_bkp, command_runner=runner, extension_restore_policy=policy)
                assert restored.result == "success" and restored.dump_restored is True
                assert hashlib.sha256(archive.read_bytes()).hexdigest() == c_sha, "the archive is never rewritten"
                assert _creation_facts(postgres, graph_db) == source_facts
                assert _graph_content(postgres, graph_db) == source_content
                _assert_no_private_toc_dirs(runner, identity.postgres_container)

                # Real ICU source semantics on this server against the product C template1: refused before creation.
                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                    adm.execute(f"CREATE DATABASE \"{graph_db}\" WITH TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C' "
                                "LOCALE_PROVIDER icu ICU_LOCALE 'und'")
                icu_handle = replace(postgres, database=graph_db)
                apply_migrations(default_rdbms_root(), icu_handle.psql_args, psql_command=icu_handle.psql_command)
                with closing(_connect(postgres, graph_db, autocommit=True)) as conn:
                    conn.execute(SYNTHETIC_GRAPH_SQL)
                provider, _collate, _ctype, icu_locale, icu_version, actual = _creation_facts(postgres, graph_db)
                assert provider == "i" and icu_locale and icu_version == actual, (icu_locale, icu_version, actual)
                icu_dump = dump_database(
                    home, database=graph_db, timestamp="20261023T011000Z",
                    command_runner=runner, extension_restore_policy=policy)
                assert icu_dump.restore_supported is True, icu_dump.restore_blockers
                icu_manifest = json.loads(icu_dump.plan.manifest_path.read_text(encoding="utf-8"))
                semantics = icu_manifest["database_catalogs"][graph_db]["creation_semantics"]
                assert (semantics["datlocprovider"], semantics["daticulocale"], semantics["datcollversion"]) == (
                    "i", icu_locale, icu_version)
                icu_archive = icu_dump.plan.backup_path / "dump.pgcustom"
                icu_sha = hashlib.sha256(icu_archive.read_bytes()).hexdigest()
                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                _drop_baseline_roles(postgres)
                _refused(
                    "restore-creation-semantics-incompatible", home, icu_dump.plan.backup_path,
                    runner, policy, postgres, database_names(postgres), database=graph_db)
                assert hashlib.sha256(icu_archive.read_bytes()).hexdigest() == icu_sha
                assert graph_db not in database_names(postgres), "no ICU target was created, refreshed or migrated"
                _assert_no_private_toc_dirs(runner, cid)
            assert postmaster_crash_lines(cid) == [], "no backend crash on the Trixie server"
        assert receipts and all(outcome in ("REMOVED", "ABSENT") for _name, outcome in receipts), receipts
