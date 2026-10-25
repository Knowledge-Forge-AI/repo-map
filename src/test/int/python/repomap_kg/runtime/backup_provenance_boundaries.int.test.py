"""Containerized integration tests for backup observation, provenance, and on-disk release artifact boundaries."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any, Iterator

import psycopg
import pytest

from repomap_kg.coordinator.local_lifecycle import LocalControlAuthority, initialize_coordinator_control
from repomap_kg.runtime import _backup_provenance as prov_mod
from repomap_kg.runtime import _backup_support as sup_mod
from repomap_kg.runtime.backup import dump_database
from repomap_kg.runtime.backup_inspection import verify_archive_toc_for_restore
from repomap_kg.runtime.backup_manifests import read_manifest_file
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.backup_provenance_boundaries import (
    malformed_database_catalog_cases, malformed_format2_manifest_cases,
    malformed_server_provenance_cases, malformed_toc_bytes_cases,
    malformed_toc_catalog_cases, sql_state_snapshot,
)
from repomap_test_support.local_db_backup import connect_real_postgres, setup_real_backup_home
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.test_scratch import short_test_directory


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_upgrade_refusal(
    artifact: Path, *, database: str, code: str, reason_substr: str, verify_dump_on_disk: bool = False
) -> None:
    with pytest.raises(LocalDbBackupError) as exc_info:
        sup_mod.load_and_verify_release_cluster_upgrade_artifact(
            artifact, database=database, verify_dump_on_disk=verify_dump_on_disk
        )
    diag = exc_info.value.diagnostics[0]
    assert diag.code == code and diag.path == database and reason_substr in diag.message


@dataclass(frozen=True)
class _RealBackupSeed:
    root: Path
    postgres: Any
    runner: Any
    authority: LocalControlAuthority
    live_op: Any
    plan: Any
    dumped: Any
    dump_file: Path
    dump_bytes: bytes
    dump_sha: str
    manifest: dict[str, Any]
    cat: dict[str, Any]
    srv: dict[str, Any]
    built_v2: dict[str, object]
    pg_restore_bin: str
    graph_db: str
    ctrl_db: str
    graph_before: dict[str, object]
    ctrl_before: dict[str, object]

    def assert_unchanged(self) -> None:
        assert self.dump_file.read_bytes() == self.dump_bytes
        assert hashlib.sha256(self.dump_file.read_bytes()).hexdigest() == self.dump_sha
        assert read_manifest_file(self.dumped.plan.manifest_path) == self.manifest
        assert sql_state_snapshot(self.postgres, self.graph_db, is_control=False) == self.graph_before
        assert sql_state_snapshot(self.postgres, self.ctrl_db, is_control=True) == self.ctrl_before


@pytest.fixture(scope="module")
def real_backup_seed() -> Iterator[_RealBackupSeed]:
    require_postgres_binaries()
    pg_restore_bin, pg_dump_bin = shutil.which("pg_restore"), shutil.which("pg_dump")
    assert pg_restore_bin is not None and pg_dump_bin is not None
    with (
        pytest.MonkeyPatch.context() as mp,
        short_test_directory("bpb-real-", "home/repomap.rpl.toml") as directory,
        temporary_postgres() as postgres,
    ):
        mp.setattr(sup_mod, "PACKAGED_PG_RESTORE", pg_restore_bin)
        mp.setattr(sup_mod, "PACKAGED_PG_DUMP", pg_dump_bin)
        mp.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        mp.setenv("POSTGRES_PASSWORD", postgres.password)
        root, home = Path(directory), Path(directory) / "home"
        graph_db, ctrl_db = "bpb_graph", "bpb_graph_control"
        _identity, runner = setup_real_backup_home(home, postgres, graph_db=graph_db)
        handle = postgres.create_database(graph_db)
        apply_migrations(default_rdbms_root(), handle.psql_args, psql_command=handle.psql_command)
        with closing(connect_real_postgres(postgres, graph_db, autocommit=True)) as conn:
            conn.execute(
                "INSERT INTO public.repositories (name, root_path, repository_identity) "
                "VALUES ('repo-map', './repo-map', 'repo1:repo-map')"
            )
        initialize_coordinator_control(home)
        authority = LocalControlAuthority(home)
        graph_before = sql_state_snapshot(postgres, graph_db, is_control=False)
        ctrl_before = sql_state_snapshot(postgres, ctrl_db, is_control=True)
        assert graph_before["tables"] and graph_before["ledger_rows"]
        assert graph_before["repo_rows"] == [("repo-map", "./repo-map", "repo1:repo-map")]
        assert ctrl_before["tables"] and ctrl_before["ledger_rows"] and ctrl_before["job_count"] == 0

        plan = build_local_runtime_plan(home)
        dumped = dump_database(home, database=graph_db, timestamp="20261024T010000Z", command_runner=runner)
        dump_file = dumped.plan.backup_path / "dump.pgcustom"
        dump_bytes = dump_file.read_bytes()
        dump_sha = hashlib.sha256(dump_bytes).hexdigest()
        manifest = read_manifest_file(dumped.plan.manifest_path)
        cat, srv = manifest["database_catalogs"][graph_db], manifest["server_provenance"]

        class _LiveOp:
            databases, control_database, password = (graph_db,), ctrl_db, postgres.password
            authority_namespace = authority.authority_namespace
            _connect = staticmethod(lambda db_name: connect_real_postgres(postgres, db_name, autocommit=True))
            pg_dump_command = staticmethod(lambda _db_name: (pg_dump_bin,))

        with authority.maintenance_window(graph_databases=(graph_db,)):
            held_before = sup_mod.observe_connection_provenance(_LiveOp, graph_db)
            built_v2 = sup_mod.build_and_verify_release_cluster_upgrade_manifest(
                operator=_LiveOp, database=graph_db, dump=dumped.dump_files[0], dump_path=dump_file,
                restore_client=pg_restore_bin, command_runner=subprocess.run,
                env=dict(os.environ, PGPASSWORD=postgres.password), before_obs=held_before,
            )

        yield _RealBackupSeed(
            root=root, postgres=postgres, runner=runner, authority=authority, live_op=_LiveOp,
            plan=plan, dumped=dumped, dump_file=dump_file, dump_bytes=dump_bytes, dump_sha=dump_sha,
            manifest=manifest, cat=cat, srv=srv, built_v2=built_v2, pg_restore_bin=pg_restore_bin,
            graph_db=graph_db, ctrl_db=ctrl_db, graph_before=graph_before, ctrl_before=ctrl_before,
        )


def test_real_postgres_archive_toc_observation_and_malformed_toc_boundaries(real_backup_seed: _RealBackupSeed) -> None:
    s = real_backup_seed
    sanitized = sup_mod.sanitize_public_manifest(s.manifest)
    assert "server_provenance" not in sanitized and sanitized["restore_protocol"] == "core_v1"
    toc_obs = prov_mod.observe_archive_toc(s.plan, s.graph_db, s.dump_file, s.runner, s.cat)
    assert toc_obs.entry_count > 0
    verify_archive_toc_for_restore(
        s.plan, s.manifest, database=s.graph_db, dump_path=s.dump_file, command_runner=s.runner
    )
    corrupt_archive = s.root / "corrupt.pgcustom"
    corrupt_archive.write_bytes(b"not-a-valid-pgcustom-archive")
    for bad_archive in (s.root / "no-such.pgcustom", corrupt_archive):
        with pytest.raises(LocalDbBackupError) as archive_err:
            prov_mod.observe_archive_toc(s.plan, s.graph_db, bad_archive, s.runner, s.cat)
        assert archive_err.value.diagnostics[0].code == "backup-toc-inconsistent"
        assert archive_err.value.diagnostics[0].path == s.graph_db

    real_toc = subprocess.run([s.pg_restore_bin, "-l", str(s.dump_file)], capture_output=True, check=True).stdout
    for bad_toc, exp_msg in malformed_toc_bytes_cases(real_toc):
        with pytest.raises(LocalDbBackupError) as toc_err:
            prov_mod.parse_toc_entries(bad_toc, database=s.graph_db)
        diag = toc_err.value.diagnostics[0]
        assert diag.code == "backup-toc-inconsistent" and exp_msg in diag.message

    toc_with_ambig_data = real_toc + b"\n99998; 0 1 TABLE DATA a b c repomap\n"
    for bad_toc_cat, exp_cat_msg in malformed_toc_catalog_cases(s.cat):
        with pytest.raises(LocalDbBackupError) as toc_cat_err:
            prov_mod.parse_and_verify_toc_provenance(
                toc_with_ambig_data, database=s.graph_db, database_catalog=bad_toc_cat
            )
        diag = toc_cat_err.value.diagnostics[0]
        assert diag.code == "backup-toc-inconsistent" and exp_cat_msg in diag.message
    s.assert_unchanged()


def test_real_postgres_connection_provenance_and_maintenance_window_custody(real_backup_seed: _RealBackupSeed) -> None:
    s = real_backup_seed
    live_graph = sup_mod.observe_connection_provenance(s.live_op, s.graph_db)
    live_ctrl = sup_mod.observe_connection_provenance(s.live_op, s.ctrl_db)
    assert live_graph.database_catalog["database_role"] == "graph"
    assert live_ctrl.database_catalog["database_role"] == "control"
    assert live_graph.database == s.graph_db and live_ctrl.database == s.ctrl_db

    with pytest.raises(LocalDbBackupError) as unowned_err:
        sup_mod.observe_connection_provenance(s.live_op, "unowned_db")
    assert "not an owned" in unowned_err.value.diagnostics[0].message

    class _NoConnOp:
        databases, control_database, _connect = (s.graph_db,), s.ctrl_db, None

    with pytest.raises(LocalDbBackupError) as no_conn_err:
        sup_mod.observe_connection_provenance(_NoConnOp, s.graph_db)
    assert "connection authority unavailable" in no_conn_err.value.diagnostics[0].message

    closed_port = _unused_local_port()

    class _UnreachOp:
        databases, control_database = (s.graph_db,), s.ctrl_db
        _connect = staticmethod(
            lambda db_name: psycopg.connect(
                host="127.0.0.1", port=closed_port, dbname=db_name,
                user=s.postgres.user, password=s.postgres.password, connect_timeout=2,
            )
        )

    with pytest.raises(LocalDbBackupError) as unreach_err:
        sup_mod.observe_connection_provenance(_UnreachOp, s.graph_db)
    assert "query failed" in unreach_err.value.diagnostics[0].message

    unheld_v2 = sup_mod.build_and_verify_release_cluster_upgrade_manifest(
        operator=s.live_op, database=s.graph_db, dump=s.dumped.dump_files[0],
        dump_path=s.dump_file, restore_client=s.pg_restore_bin, command_runner=subprocess.run,
        env=dict(os.environ, PGPASSWORD=s.postgres.password), before_obs=live_graph,
    )
    assert unheld_v2["schema_version"] == 2 and unheld_v2["restore_supported"] is False
    assert unheld_v2["restore_blockers"] == ["quiescence-not-verified"]
    unheld_q = unheld_v2["quiescence"]
    assert isinstance(unheld_q, dict)
    expected_unheld = {
        "mode": "unheld", "maintenance_window_mode": "unheld", "maintenance_window_held": False,
        "control_database": None, "locked_databases": [], "verified": False,
        "before_after_fingerprint_matched": True,
    }
    assert {key: unheld_q[key] for key in expected_unheld} == expected_unheld
    unheld_dir = s.root / "rel_unheld_v2"
    unheld_dir.mkdir(exist_ok=True)
    (unheld_dir / "database.dump").write_bytes(s.dump_bytes)
    (unheld_dir / "schema-upgrade.json").write_text(
        json.dumps({**unheld_v2, "artifact": "database.dump"}), encoding="utf-8"
    )
    _assert_upgrade_refusal(
        unheld_dir, database=s.graph_db, code="backup-restore-unsupported", reason_substr="quiescence-not-verified"
    )

    with s.authority.maintenance_window(graph_databases=(s.graph_db,)):
        held_before = sup_mod.observe_connection_provenance(s.live_op, s.graph_db)
        assert held_before.database == s.graph_db and held_before.fingerprint == live_graph.fingerprint
        held_v2 = sup_mod.build_and_verify_release_cluster_upgrade_manifest(
            operator=s.live_op, database=s.graph_db, dump=s.dumped.dump_files[0],
            dump_path=s.dump_file, restore_client=s.pg_restore_bin, command_runner=subprocess.run,
            env=dict(os.environ, PGPASSWORD=s.postgres.password), before_obs=held_before,
        )
    assert held_v2["schema_version"] == 2 and held_v2["restore_supported"] is True
    assert held_v2["restore_blockers"] == []
    held_q = held_v2["quiescence"]
    assert isinstance(held_q, dict)
    expected_held = {
        "mode": "coordinator-maintenance-window", "maintenance_window_mode": "coordinator-maintenance-window",
        "maintenance_window_held": True, "before_after_fingerprint_matched": True,
        "control_database": s.ctrl_db, "locked_databases": [s.ctrl_db, s.graph_db], "verified": True,
    }
    assert {key: held_q[key] for key in expected_held} == expected_held
    assert s.built_v2 == held_v2
    s.assert_unchanged()


def test_real_postgres_on_disk_release_upgrade_artifact_boundaries(real_backup_seed: _RealBackupSeed) -> None:
    s = real_backup_seed
    root, graph_db, dump_bytes, dump_sha = s.root, s.graph_db, s.dump_bytes, s.dump_sha
    built_v2, srv, cat, inv = s.built_v2, s.srv, s.cat, "backup-manifest-invalid"
    v1_dir = root / "rel_v1"
    v1_dir.mkdir()
    (v1_dir / "database.dump").write_bytes(dump_bytes)
    v1_payload: dict[str, object] = {
        "schema_version": 1, "restore_supported": True, "database": graph_db,
        "artifact": "database.dump", "sha256": dump_sha, "size_bytes": len(dump_bytes),
    }
    (v1_dir / "schema-upgrade.json").write_text(json.dumps(v1_payload), encoding="utf-8")
    loaded_v1, eval_v1 = sup_mod.load_and_verify_release_cluster_upgrade_artifact(
        v1_dir, database=graph_db, verify_dump_on_disk=True
    )
    assert eval_v1.restore_supported is True and "_verified_toc_summary" in loaded_v1

    v2_dir = root / "rel_v2"
    v2_dir.mkdir()
    (v2_dir / "database.dump").write_bytes(dump_bytes)
    v2_payload: dict[str, object] = {**built_v2, "artifact": "database.dump"}
    v2_json = v2_dir / "schema-upgrade.json"
    v2_json.write_text(json.dumps(v2_payload), encoding="utf-8")
    loaded_v2, eval_v2 = sup_mod.load_and_verify_release_cluster_upgrade_artifact(
        v2_dir, database=graph_db, verify_dump_on_disk=True
    )
    assert eval_v2.restore_supported is True and "_verified_toc_summary" in loaded_v2
    assert sup_mod.evaluate_release_cluster_upgrade_artifact(v2_dir, database=graph_db).restore_supported is True

    sym_dir = root / "sym_rel"
    sym_dir.symlink_to(v2_dir)
    _assert_upgrade_refusal(sym_dir, database=graph_db, code=inv, reason_substr="symlink")
    empty_dir = root / "empty_rel"
    empty_dir.mkdir()
    _assert_upgrade_refusal(empty_dir, database=graph_db, code=inv, reason_substr="is missing")
    raw_dir = root / "raw_json_rel"
    raw_dir.mkdir()
    raw_file = raw_dir / "schema-upgrade.json"
    raw_file.write_bytes(b"\xff\xfe")
    _assert_upgrade_refusal(raw_dir, database=graph_db, code=inv, reason_substr="invalid JSON")
    for bad_text, reason in (
        ("{bad", "invalid JSON"),
        ('{"schema_version": 1, "schema_version": 1}', "invalid JSON"),
        ('{"schema_version": NaN}', "invalid JSON"),
        ("[]", "must be an object"),
    ):
        raw_file.write_text(bad_text, encoding="utf-8")
        _assert_upgrade_refusal(raw_dir, database=graph_db, code=inv, reason_substr=reason)
    for bad_ver in (99, True, "2"):
        v2_json.write_text(json.dumps({**v2_payload, "schema_version": bad_ver}), encoding="utf-8")
        _assert_upgrade_refusal(
            v2_dir, database=graph_db, code="backup-format-unsupported", reason_substr="unsupported schema-upgrade.json"
        )
    for mutated, reason in (
        ({**v2_payload, "restore_supported": "yes"}, "boolean restore_supported"),
        ({**v2_payload, "database": "other_db"}, "archive integrity fields"),
        ({**v2_payload, "artifact": "../outside.dump"}, "archive integrity fields"),
        ({**v2_payload, "sha256": "bad"}, "archive integrity fields"),
        ({**v2_payload, "size_bytes": 0}, "archive integrity fields"),
        ({**v2_payload, "toc_sha256": "bad"}, "missing format-2 artifact bindings"),
        ({**v2_payload, "restore_client": ""}, "missing format-2 artifact bindings"),
    ):
        v2_json.write_text(json.dumps(mutated), encoding="utf-8")
        _assert_upgrade_refusal(v2_dir, database=graph_db, code=inv, reason_substr=reason)
    v2_json.write_text(json.dumps({**v2_payload, "database_catalogs": {}}), encoding="utf-8")
    _assert_upgrade_refusal(
        v2_dir, database=graph_db, code="backup-restore-unsupported", reason_substr="extension-catalog-incomplete"
    )
    for bad_srv in malformed_server_provenance_cases(srv):
        v2_json.write_text(json.dumps({**v2_payload, "server_provenance": bad_srv}), encoding="utf-8")
        _assert_upgrade_refusal(v2_dir, database=graph_db, code=inv, reason_substr="invalid provenance")
    for bad_cat in malformed_database_catalog_cases(cat)[1:7]:
        v2_json.write_text(json.dumps({**v2_payload, "database_catalogs": {graph_db: bad_cat}}), encoding="utf-8")
        _assert_upgrade_refusal(v2_dir, database=graph_db, code=inv, reason_substr="invalid provenance")
    cube_cat = malformed_database_catalog_cases(cat)[9]
    v2_json.write_text(json.dumps({**v2_payload, "database_catalogs": {graph_db: cube_cat}}), encoding="utf-8")
    _assert_upgrade_refusal(
        v2_dir, database=graph_db,
        code="backup-extension-restore-unsupported", reason_substr="extension-catalog-incomplete",
    )
    v2_json.write_text(json.dumps({**v2_payload, "toc_sha256": "0" * 64}), encoding="utf-8")
    _assert_upgrade_refusal(
        v2_dir, database=graph_db, code="backup-toc-inconsistent", reason_substr="TOC digest", verify_dump_on_disk=True
    )
    ghost_schemas = [*cat["non_system_schemas"], {"name": "ghost_schema", "owner": "repomap"}]
    ghost_cat = {**cat, "non_system_schemas": ghost_schemas}
    v2_json.write_text(json.dumps({**v2_payload, "database_catalogs": {graph_db: ghost_cat}}), encoding="utf-8")
    _assert_upgrade_refusal(
        v2_dir, database=graph_db, code="backup-toc-inconsistent", reason_substr="TOC schemas", verify_dump_on_disk=True
    )
    v2_json.write_text(json.dumps(v2_payload), encoding="utf-8")
    (v2_dir / "database.dump").write_bytes(b"tampered-dump-bytes")
    _assert_upgrade_refusal(v2_dir, database=graph_db, code=inv, reason_substr="checksum", verify_dump_on_disk=True)
    corrupt_bytes = b"not-a-pgcustom-archive"
    corrupt_sha = hashlib.sha256(corrupt_bytes).hexdigest()
    (v2_dir / "database.dump").write_bytes(corrupt_bytes)
    v2_json.write_text(
        json.dumps({**v2_payload, "sha256": corrupt_sha, "size_bytes": len(corrupt_bytes)}), encoding="utf-8"
    )
    _assert_upgrade_refusal(
        v2_dir, database=graph_db, code="backup-toc-inconsistent", reason_substr="", verify_dump_on_disk=True
    )
    (v2_dir / "database.dump").unlink()
    v2_json.write_text(json.dumps(v2_payload), encoding="utf-8")
    _assert_upgrade_refusal(v2_dir, database=graph_db, code=inv, reason_substr="missing", verify_dump_on_disk=True)
    s.assert_unchanged()


def test_real_postgres_on_disk_backup_manifest_boundaries(real_backup_seed: _RealBackupSeed) -> None:
    s = real_backup_seed
    manifest_dir = s.root / "bad_manifests"
    manifest_dir.mkdir()
    bad_file = manifest_dir / "manifest.json"

    with pytest.raises(LocalDbBackupError) as missing_err:
        read_manifest_file(manifest_dir / "missing.json")
    assert missing_err.value.diagnostics[0].code == "backup-manifest-unreadable"

    for raw_text, expected_code in (
        ("{bad", "backup-manifest-unreadable"),
        ('{"a": 1, "a": 2}', "backup-manifest-invalid"),
        ('{"a": NaN}', "backup-manifest-invalid"),
        ("[]", "backup-manifest-invalid"),
    ):
        bad_file.write_text(raw_text, encoding="utf-8")
        with pytest.raises(LocalDbBackupError) as parse_err:
            read_manifest_file(bad_file)
        assert parse_err.value.diagnostics[0].code == expected_code

    for bad_manifest, expected_code, expected_reason in malformed_format2_manifest_cases(s.manifest, s.graph_db):
        bad_file.write_text(json.dumps(bad_manifest), encoding="utf-8")
        with pytest.raises(LocalDbBackupError) as val_err:
            read_manifest_file(bad_file)
        diag = val_err.value.diagnostics[0]
        assert diag.code == expected_code and expected_reason in diag.message
    s.assert_unchanged()
