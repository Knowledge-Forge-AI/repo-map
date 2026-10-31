"""D9-A regression cases for residual post-review authority boundaries."""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from common_lore_index.runtime._backup_observation import (
    observe_client_identities,
    observe_database_provenance,
    parse_and_validate_catalog_observation,
)
from common_lore_index.runtime._backup_operations import acquire_or_reuse_backup_maintenance_window
from common_lore_index.runtime._backup_provenance import CATALOG_OBSERVATION_SQL
from common_lore_index.runtime._backup_support import (
    evaluate_backup_restore_support,
    evaluate_release_cluster_upgrade_artifact,
    load_and_verify_release_cluster_upgrade_artifact,
)
from common_lore_index.runtime.backup_inspection import (
    _run_pg_restore_list_bytes,
    verify_archive_toc_for_restore,
)
from common_lore_index.runtime.backup_manifests import summarize_pg_restore_toc
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import build_local_runtime_plan, setup_local_runtime
from common_lore_index.runtime.maintenance import (
    active_maintenance_custody,
    bind_maintenance_custody,
    held_maintenance_custody_for,
    runtime_maintenance_namespace,
)
from repomap_test_support.local_db_backup import baseline_observation_json_bytes


def _plan(home: Path) -> Any:
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    plan.env_file.parent.mkdir(parents=True, exist_ok=True)
    plan.env_file.write_text("POSTGRES_PASSWORD=unit-only-password\n", encoding="utf-8")
    plan.env_file.chmod(0o600)
    return plan


@pytest.mark.parametrize("version", [1.0, 2.0, True, None, "2", [], {}])
def test_backup_version_requires_an_integer(version: object) -> None:
    with pytest.raises(LocalDbBackupError) as caught:
        evaluate_backup_restore_support({"backup_format_version": version, "restore_supported": True})
    assert caught.value.diagnostics[0].code == "backup-format-unsupported"


@pytest.mark.parametrize("version", [1.0, 2.0, True, None, "2", [], {}])
def test_release_version_requires_an_integer(version: object) -> None:
    with pytest.raises(LocalDbBackupError) as caught:
        evaluate_release_cluster_upgrade_artifact({"schema_version": version, "restore_supported": True})
    assert caught.value.diagnostics[0].code == "backup-format-unsupported"


def test_unscoped_same_database_custody_cannot_skip_acquisition(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "other-runtime")
    with bind_maintenance_custody(
        mode="direct-advisory-lock-window", databases=("repomap_control", "repomap")
    ), patch(
        "common_lore_index.runtime._backup_operations.psycopg.connect",
        side_effect=psycopg.OperationalError("unit-private-driver-marker"),
    ) as connect:
        with pytest.raises(LocalDbBackupError) as caught:
            with acquire_or_reuse_backup_maintenance_window(plan, ("repomap",), command_runner=subprocess.run):
                pytest.fail("a record without matching runtime authority skipped real lock acquisition")
    assert connect.called
    assert caught.value.diagnostics[0].code == "backup-maintenance-window-unavailable"
    assert "unit-private-driver-marker" not in str(caught.value)


def test_operation_error_is_not_reclassified_as_acquisition_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "runtime")
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = [("repomap_control",), ("repomap",)]
    primary = psycopg.OperationalError("unit-operation-marker")
    with patch("common_lore_index.runtime._backup_operations.psycopg.connect", return_value=connection), patch(
        "common_lore_index.runtime._backup_operations.maintenance_window", side_effect=lambda _connect: nullcontext()
    ):
        with pytest.raises(psycopg.OperationalError) as caught:
            with acquire_or_reuse_backup_maintenance_window(plan, ("repomap",), command_runner=subprocess.run):
                raise primary
    assert caught.value is primary


def test_legacy_release_requires_recorded_archive_integrity(tmp_path: Path) -> None:
    (tmp_path / "database.dump").write_bytes(b"unit-only-archive")
    (tmp_path / "schema-upgrade.json").write_text(
        json.dumps({"schema_version": 1, "restore_supported": True}), encoding="utf-8"
    )
    with pytest.raises(LocalDbBackupError) as caught:
        load_and_verify_release_cluster_upgrade_artifact(tmp_path, verify_dump_on_disk=True)
    assert caught.value.diagnostics[0].code == "backup-manifest-invalid"
    with pytest.raises(LocalDbBackupError) as meta_caught:
        evaluate_release_cluster_upgrade_artifact({"schema_version": 1, "restore_supported": True})
    assert meta_caught.value.diagnostics[0].code == "backup-manifest-invalid"
    with pytest.raises(LocalDbBackupError) as zero_caught:
        evaluate_release_cluster_upgrade_artifact(
            {"schema_version": 1, "restore_supported": True, "database": "repomap", "artifact": "database.dump", "sha256": "a" * 64, "size_bytes": 0}
        )
    assert zero_caught.value.diagnostics[0].code == "backup-manifest-invalid"


def test_release_archive_path_cannot_escape_its_directory(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    outside = tmp_path / "outside.dump"
    content = b"unit-only-archive"
    outside.write_bytes(content)
    payload = {
        "schema_version": 1, "restore_supported": True, "database": "repomap",
        "artifact": "../outside.dump", "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
    }
    (backup / "schema-upgrade.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LocalDbBackupError) as caught:
        load_and_verify_release_cluster_upgrade_artifact(backup, verify_dump_on_disk=True)
    assert caught.value.diagnostics[0].code == "backup-manifest-invalid"
    assert outside.read_bytes() == content


def test_injected_archive_transport_streams_large_archives(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "runtime")
    archive = tmp_path / "large.pgcustom"
    with archive.open("wb") as handle:
        handle.write(b"PGDMP")
        handle.truncate(64 * 1024 * 1024 + 1)
    streams: list[Any] = []
    toc = b"; unit-only TOC\n1; 3079 1 EXTENSION - plpgsql\n"

    def runner(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert kwargs.get("input") is None
        stream = kwargs.get("stdin")
        assert stream is not None
        assert stream.tell() == 0
        assert stream.read(5) == b"PGDMP"
        streams.append(stream)
        return subprocess.CompletedProcess(command, 0, stdout=toc, stderr=b"")

    assert _run_pg_restore_list_bytes(plan, archive, ("unit-pg-restore", "-l"), runner) == toc
    assert len(streams) == 1 and streams[0].closed


def test_different_runtime_home_custody_cannot_satisfy_other_home_window(tmp_path: Path) -> None:
    plan_a = _plan(tmp_path / "home_a")
    plan_b = _plan(tmp_path / "home_b")
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = [("repomap_control",), ("repomap",)]
    with patch("common_lore_index.runtime._backup_operations.psycopg.connect", return_value=connection), patch(
        "common_lore_index.runtime._backup_operations.maintenance_window", side_effect=lambda _connect: nullcontext()
    ):
        with acquire_or_reuse_backup_maintenance_window(plan_a, ("repomap",), command_runner=subprocess.run) as ns_a:
            assert active_maintenance_custody() is not None
            assert held_maintenance_custody_for("repomap_control", "repomap", authority_namespace=ns_a) is not None
            with patch(
                "common_lore_index.runtime._backup_operations.psycopg.connect",
                side_effect=psycopg.OperationalError("plan-b-private-driver-error"),
            ) as connect_b:
                with pytest.raises(LocalDbBackupError) as caught:
                    with acquire_or_reuse_backup_maintenance_window(
                        plan_b, ("repomap",), command_runner=subprocess.run
                    ):
                        pytest.fail("custody for home_a must not satisfy lock acquisition for home_b")
            assert connect_b.called
            assert caught.value.diagnostics[0].code == "backup-maintenance-window-unavailable"
            assert "plan-b-private-driver-error" not in str(caught.value)
            assert isinstance(caught.value.__cause__, psycopg.OperationalError)
            with patch(
                "common_lore_index.runtime._backup_operations.execution_postgres", return_value=MagicMock(host="127.0.0.1", port=55433)
            ), patch(
                "common_lore_index.runtime._backup_operations.psycopg.connect", side_effect=psycopg.OperationalError("port-mismatch")
            ) as connect_ep:
                with pytest.raises(LocalDbBackupError) as ep_caught:
                    with acquire_or_reuse_backup_maintenance_window(plan_a, ("repomap",), command_runner=subprocess.run):
                        pytest.fail("same home with different endpoint port must not reuse custody")
            assert connect_ep.called and ep_caught.value.diagnostics[0].code == "backup-maintenance-window-unavailable"
    assert active_maintenance_custody() is None
    assert held_maintenance_custody_for("repomap_control", "repomap", authority_namespace=ns_a) is None

    ns_only_graph = runtime_maintenance_namespace(plan_a.repo_map_home, host="127.0.0.1", port=5432)
    with bind_maintenance_custody(
        mode="direct-advisory-lock-window", control_database=None, databases=("repomap",), authority_namespace=ns_only_graph
    ), patch("common_lore_index.runtime._backup_operations.psycopg.connect", side_effect=psycopg.OperationalError("missing-ctrl")) as connect_ctrl:
        with pytest.raises(LocalDbBackupError):
            with acquire_or_reuse_backup_maintenance_window(plan_a, ("repomap",), command_runner=subprocess.run):
                pytest.fail("outer custody missing control_db must not be reused")
    assert connect_ctrl.called


def test_release_verify_on_disk_rejects_mapping_symlinks_and_untrusted_client(tmp_path: Path) -> None:
    content = b"PGDMP-unit-archive"
    digest = hashlib.sha256(content).hexdigest()
    valid_v1 = {
        "schema_version": 1,
        "restore_supported": True,
        "database": "repomap",
        "artifact": "database.dump",
        "sha256": digest,
        "size_bytes": len(content),
    }
    with pytest.raises(LocalDbBackupError) as map_err:
        load_and_verify_release_cluster_upgrade_artifact(valid_v1, verify_dump_on_disk=True)
    assert map_err.value.diagnostics[0].code == "backup-manifest-invalid"

    sym_dir = tmp_path / "sym_backup"
    sym_dir.mkdir()
    outside = tmp_path / "outside_target.dump"
    outside.write_bytes(content)
    (sym_dir / "database.dump").symlink_to(outside)
    (sym_dir / "schema-upgrade.json").write_text(json.dumps(valid_v1), encoding="utf-8")
    with pytest.raises(LocalDbBackupError) as sym_err:
        load_and_verify_release_cluster_upgrade_artifact(sym_dir, verify_dump_on_disk=True)
    assert sym_err.value.diagnostics[0].code == "backup-manifest-invalid"

    ext_dir = tmp_path / "ext_backup"
    ext_dir.mkdir()
    (ext_dir / "database.dump").write_bytes(content)
    untrusted = dict(valid_v1, restore_client="/untrusted/evil/pg_restore")
    (ext_dir / "schema-upgrade.json").write_text(json.dumps(untrusted), encoding="utf-8")
    seen_cmds: list[tuple[str, ...]] = []

    def toc_runner(command: Any, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen_cmds.append(tuple(str(c) for c in command))
        return subprocess.CompletedProcess(
            command, 0, stdout=b"1; 3079 16385 EXTENSION - vector \n", stderr=b""
        )

    with patch("common_lore_index.runtime._backup_support.subprocess.run", side_effect=toc_runner):
        with pytest.raises(LocalDbBackupError) as ext_err:
            load_and_verify_release_cluster_upgrade_artifact(
                ext_dir, database="repomap", verify_dump_on_disk=True
            )
    assert ext_err.value.diagnostics[0].code == "backup-extension-restore-unsupported"
    assert seen_cmds and seen_cmds[0][0] == "/usr/bin/pg_restore"
    with patch("common_lore_index.runtime._backup_support.subprocess.run", return_value=subprocess.CompletedProcess(("pg_restore",), 0, stdout=b"; comment only\n", stderr=b"")):
        with pytest.raises(LocalDbBackupError) as empty_toc_err:
            load_and_verify_release_cluster_upgrade_artifact(ext_dir, database="repomap", verify_dump_on_disk=True)
    assert empty_toc_err.value.diagnostics[0].code == "backup-toc-inconsistent"


def test_provenance_does_not_conflate_baseline_or_role_or_default_missing_fields(tmp_path: Path) -> None:
    assert "NOT LIKE 'pg\\_temp\\_%' ESCAPE '\\'" in CATALOG_OBSERVATION_SQL
    assert "NOT LIKE 'pg\\_toast\\_temp\\_%' ESCAPE '\\'" in CATALOG_OBSERVATION_SQL
    raw_bytes = baseline_observation_json_bytes("analytics_control")
    obs = parse_and_validate_catalog_observation(raw_bytes, database="analytics_control")
    cat = obs.database_catalog
    assert cat["database_role"] == "graph"
    ext = cat["installed_extensions"][0]
    assert ext["name"] == "plpgsql"
    assert ext["is_baseline"] is True
    assert ext["baseline_origin"] == "unavailable"
    assert ext["ownership_classification"] == "unclassified"
    assert ext["declaration_identity"] == "unavailable"
    assert ext["experimental_context"] == "unavailable"
    plan = _plan(tmp_path / "role_home")
    with pytest.raises(LocalDbBackupError) as unowned_err:
        observe_database_provenance(plan, "unowned_db", subprocess.run)
    assert unowned_err.value.diagnostics[0].code == "database-not-owned"
    clients = observe_client_identities(
        plan=plan, psql_bin=None,
        command_runner=lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, stdout=b"pg_tool (PostgreSQL) 16.4\n", stderr=b""),
    )
    assert clients == {"pg_dump_version": "pg_tool (PostgreSQL) 16.4", "pg_restore_version": "pg_tool (PostgreSQL) 16.4", "psql_version": "unused"}

    payload = json.loads(raw_bytes.decode("utf-8"))
    del payload["database_catalog"]["installed_extensions"][0]["declaration_identity"]
    with pytest.raises(LocalDbBackupError) as missing_err:
        parse_and_validate_catalog_observation(
            json.dumps(payload).encode("utf-8"),
            database="analytics_control",
        )
    assert missing_err.value.diagnostics[0].code == "backup-observation-incomplete"

    cond_payload = json.loads(raw_bytes.decode("utf-8"))
    cond_payload["database_catalog"]["installed_extensions"][0]["extconfig_tables"] = [
        "public.cfg_a",
        "public.cfg_b",
    ]
    cond_payload["database_catalog"]["installed_extensions"][0]["extcondition"] = [
        " WHERE k = ' a  b ' ",
        " WHERE k = 'c' ",
    ]
    cond_payload["database_catalog"]["extension_config_tables"] = [
        {
            "extension": "plpgsql",
            "schema": "public",
            "table": "cfg_a",
            "qualified_table": "public.cfg_a",
            "relkind": "r",
            "condition": " WHERE k = 'c' ",
        },
        {
            "extension": "plpgsql",
            "schema": "public",
            "table": "cfg_b",
            "qualified_table": "public.cfg_b",
            "relkind": "r",
            "condition": " WHERE k = ' a  b ' ",
        },
    ]
    with pytest.raises(LocalDbBackupError) as pos_err:
        parse_and_validate_catalog_observation(
            json.dumps(cond_payload).encode("utf-8"),
            database="analytics_control",
        )
    assert pos_err.value.diagnostics[0].code == "backup-observation-incomplete"


def test_legacy_toc_extension_with_plpgsql_prefix_or_quote_refused(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "home")
    archive = tmp_path / "dump.pgcustom"
    archive.write_bytes(b"PGDMP-legacy")
    summary = summarize_pg_restore_toc(
        "1; 3079 16385 EXTENSION - plpgsql x \n",
        dump_file="dump.pgcustom",
        dump_format="pgcustom",
    )
    assert summary.extensions == ("plpgsql x",)
    v1_manifest = {"backup_format_version": 1, "restore_supported": True, "database": "repomap"}
    with patch(
        "common_lore_index.runtime.backup_inspection._run_pg_restore_list_bytes",
        return_value=b"1; 3079 16385 EXTENSION - plpgsql x \n",
    ):
        with pytest.raises(LocalDbBackupError) as prefix_err:
            verify_archive_toc_for_restore(
                plan=plan,
                manifest=v1_manifest,
                database="repomap",
                dump_path=archive,
                command_runner=subprocess.run,
            )
    assert prefix_err.value.diagnostics[0].code == "backup-extension-restore-unsupported"

    with patch(
        "common_lore_index.runtime.backup_inspection._run_pg_restore_list_bytes",
        return_value=b'1; 3079 16385 EXTENSION - "plpgsql\n',
    ):
        # PG16 emits raw extension tags; a quote is part of the name, not SQL.
        with pytest.raises(LocalDbBackupError) as quoted_err:
            verify_archive_toc_for_restore(
                plan=plan,
                manifest=v1_manifest,
                database="repomap",
                dump_path=archive,
                command_runner=subprocess.run,
            )
    assert quoted_err.value.diagnostics[0].code == "backup-extension-restore-unsupported"
