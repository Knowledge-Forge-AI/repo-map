"""Unit tests for ADR 0084 D9-A backup manifest format 2 and provenance guards."""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from repomap_kg.runtime._backup_observation import parse_and_validate_catalog_observation, verify_provenance_fingerprints
from repomap_kg.runtime._backup_operations import acquire_or_reuse_backup_maintenance_window
from repomap_kg.runtime._backup_provenance import (
    BACKUP_FORMAT_VERSION, CORE_V1_RESTORE_PROTOCOL, EXTENSION_V2_RESTORE_PROTOCOL,
    MAX_CONFIG_ENTRIES_PER_DATABASE, MAX_DATABASES_PER_MANIFEST, MAX_DEPENDENCY_EDGES_PER_DATABASE,
    MAX_EXTENSIONS_PER_DATABASE, MAX_MANIFEST_UTF8_BYTES, MAX_OBSERVATION_JSON_BYTES,
    MAX_QUERY_OBSERVED_OUTPUT_BYTES, MAX_SCHEMAS_PER_DATABASE, MAX_TOC_OUTPUT_BYTES,
    SUPPORTED_BACKUP_FORMAT_VERSIONS, parse_and_verify_toc_provenance, run_bounded_popen,
)
from repomap_kg.runtime._backup_support import (
    derive_database_blockers, evaluate_backup_restore_support, evaluate_release_cluster_upgrade_artifact,
    load_and_verify_release_cluster_upgrade_artifact, require_verified_backup_inspection_supported,
)
from repomap_kg.runtime.backup import (
    drop_database, dump_database, init_database_from_dump, inspect_backup, read_backup_info,
)
from repomap_kg.runtime.backup_inspection import verify_archive_toc_for_restore
from repomap_kg.runtime.backup_manifests import read_manifest_file
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import (
    COORDINATED_SCOPE, STABLE_RECOVERY_POINT, restore_coordinated_backup,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, build_local_runtime_plan, setup_local_runtime
from repomap_test_support.local_db_backup import (
    baseline_toc_bytes, default_baseline_database_catalog,
    default_baseline_server_provenance, maybe_provenance_runner_result,
)


@pytest.fixture(autouse=True)
def _unit_custody() -> Iterator[None]:
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    def _exec(_sql: Any, params: Any = None) -> Any:
        requested = set(params[0]) if params else {"repomap_control", "repomap"}
        res = MagicMock()
        res.fetchall.return_value = [(db,) for db in ("repomap_control", "repomap") if db in requested]
        return res

    mock_conn.execute.side_effect = _exec
    with (
        patch("repomap_kg.runtime._backup_operations.psycopg.connect", return_value=mock_conn),
        patch("repomap_kg.runtime._backup_operations.maintenance_window", side_effect=lambda *a, **kw: contextlib.nullcontext()),
    ):
        yield


def _ext(
    name: str,
    *,
    version: str = "1.0",
    schema: str = "public",
    relocatable: bool = True,
    prereqs: list[str] | None = None,
    cfg: list[str] | None = None,
    cond: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name, "version": version, "schema": schema, "owner": "repomap",
        "relocatable": relocatable, "trusted": None, "is_baseline": False,
        "baseline_origin": "unavailable", "ownership_classification": "unclassified",
        "declaration_identity": "unavailable", "experimental_context": "unavailable",
        "prerequisite_extensions": prereqs or [],
        "extconfig_tables": cfg or [], "extcondition": cond or [],
    }


def _obs_bytes(
    *,
    extensions: list[dict[str, Any]] | None = None,
    schemas: list[dict[str, str]] | None = None,
    config_tables: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> bytes:
    cat = default_baseline_database_catalog(owner="repomap")
    if extensions is not None:
        cat["installed_extensions"] = extensions
    if schemas is not None:
        cat["non_system_schemas"] = schemas
    if config_tables is not None:
        cat["extension_config_tables"] = [{"relkind": "r", **c} for c in config_tables]
    if edges is not None:
        norm_edges = [{"identity_portable": not str(e.get("object_identity", "")).startswith("unidentified:"), **e} for e in edges]
        cat["extension_dependency_summary"] = {"by_class": {"pg_class": len(norm_edges)}, "edge_count": len(norm_edges), "edges": norm_edges}
    return json.dumps({"server_provenance": default_baseline_server_provenance(), "database_catalog": cat}, sort_keys=True).encode("utf-8")


def _owned_container_json(identity: LocalRuntimeIdentity) -> str:
    return json.dumps([{"Id": "c-d9a", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])


def test_frozen_d9a_constants_and_ceilings() -> None:
    assert (BACKUP_FORMAT_VERSION, SUPPORTED_BACKUP_FORMAT_VERSIONS) == (2, (1, 2))
    assert (CORE_V1_RESTORE_PROTOCOL, EXTENSION_V2_RESTORE_PROTOCOL) == ("core_v1", "extension_v2")
    assert MAX_MANIFEST_UTF8_BYTES == 8 * 1024 * 1024
    assert MAX_QUERY_OBSERVED_OUTPUT_BYTES == 2 * 1024 * 1024
    assert MAX_TOC_OUTPUT_BYTES == 4 * 1024 * 1024
    assert MAX_OBSERVATION_JSON_BYTES == 8 * 1024 * 1024
    assert (MAX_DATABASES_PER_MANIFEST, MAX_EXTENSIONS_PER_DATABASE) == (256, 256)
    assert (MAX_SCHEMAS_PER_DATABASE, MAX_DEPENDENCY_EDGES_PER_DATABASE) == (4096, 8192)
    assert MAX_CONFIG_ENTRIES_PER_DATABASE == 1024


def test_manifest_reader_version_gate_and_json_strictness(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    dump_bytes = b"sample-dump"
    base_v1 = {
        "backup_format_version": 1, "backup_id": "b1", "database": "repomap", "databases": ["repomap"],
        "dump_files": [{"name": "dump.pgcustom", "size_bytes": len(dump_bytes), "sha256": hashlib.sha256(dump_bytes).hexdigest()}],
    }
    manifest_path.write_text(json.dumps(base_v1), encoding="utf-8")
    parsed_v1 = read_manifest_file(manifest_path)
    assert parsed_v1["backup_format_version"] == 1
    eval_v1 = evaluate_backup_restore_support(parsed_v1, database="repomap")
    assert (eval_v1.extension_census_state, eval_v1.restore_supported, eval_v1.restore_protocol) == ("unknown", True, "core_v1")

    for bad_ver in (0, 3, 99, "2", True, None):
        manifest_path.write_text(json.dumps(dict(base_v1, backup_format_version=bad_ver)), encoding="utf-8")
        with pytest.raises(LocalDbBackupError) as exc:
            read_manifest_file(manifest_path)
        assert exc.value.diagnostics[0].code == "backup-format-unsupported"

    for invalid_json in ('{"backup_format_version": 1, "dup": 1, "dup": 2}', '{"backup_format_version": 1, "x": NaN}'):
        manifest_path.write_text(invalid_json, encoding="utf-8")
        with pytest.raises(LocalDbBackupError) as j_exc:
            read_manifest_file(manifest_path)
        assert j_exc.value.diagnostics[0].code == "backup-manifest-invalid"

    with patch("repomap_kg.runtime._backup_manifest_records.MAX_MANIFEST_UTF8_BYTES", 64):
        manifest_path.write_text(json.dumps(base_v1), encoding="utf-8")
        with pytest.raises(LocalDbBackupError) as size_exc:
            read_manifest_file(manifest_path)
        assert size_exc.value.diagnostics[0].code == "backup-manifest-invalid"

    with pytest.raises(LocalDbBackupError) as eval_ver_exc:
        evaluate_backup_restore_support({"database": "repomap", "restore_supported": True}, database="repomap")
    assert eval_ver_exc.value.diagnostics[0].code == "backup-format-unsupported"

    with pytest.raises(LocalDbBackupError) as rc_ver_exc:
        evaluate_release_cluster_upgrade_artifact({"restore_supported": True}, database="repomap")
    assert rc_ver_exc.value.diagnostics[0].code == "backup-format-unsupported"

    upg_path = tmp_path / "schema-upgrade.json"
    upg_path.write_text(json.dumps({"schema_version": 1, "artifact": "database.dump"}), encoding="utf-8")
    with pytest.raises(LocalDbBackupError) as rc_missing_sup:
        load_and_verify_release_cluster_upgrade_artifact(upg_path, database="repomap")
    assert rc_missing_sup.value.diagnostics[0].code == "backup-manifest-invalid"


def test_catalog_observation_ceilings_fingerprints_and_toc_verification() -> None:
    obs1 = parse_and_validate_catalog_observation(_obs_bytes(), database="repomap")
    obs2 = parse_and_validate_catalog_observation(_obs_bytes(), database="repomap")
    assert verify_provenance_fingerprints(obs1, obs2).fingerprint == obs1.fingerprint
    obs1_exts: Any = obs1.database_catalog["installed_extensions"]
    assert obs1_exts[0]["trusted"] is True
    assert obs1_exts[0]["baseline_origin"] == "unavailable"

    pol_obs = parse_and_validate_catalog_observation(
        _obs_bytes(extensions=[_ext("citext", version="1.6"), _ext("vector", version="0.8.7")]),
        database="repomap",
        extension_policy={
            "citext": {"ownership_classification": "permitted-foreign", "declaration_identity": "d3:foreign:citext", "experimental_context": "none"},
            "vector": {"ownership_classification": "unclassified", "experimental_context": "adr0077-disposable-pgvector"},
        },
    )
    pol_exts: Any = pol_obs.database_catalog["installed_extensions"]
    exts_by_name = {e["name"]: e for e in pol_exts}
    assert (exts_by_name["citext"]["ownership_classification"], exts_by_name["citext"]["declaration_identity"]) == ("permitted-foreign", "d3:foreign:citext")
    assert exts_by_name["vector"]["experimental_context"] == "adr0077-disposable-pgvector"

    custom_schema_obs = parse_and_validate_catalog_observation(
        _obs_bytes(schemas=[{"name": "app space_α", "owner": "repomap"}, {"name": "app_core", "owner": "repomap"}, {"name": "public", "owner": "repomap"}]),
        database="repomap",
    )
    assert derive_database_blockers(custom_schema_obs.database_catalog) == set()
    assert "extension-catalog-incomplete" in derive_database_blockers(dict(custom_schema_obs.database_catalog, extension_dependency_summary={"edges": []}))
    with pytest.raises(LocalDbBackupError) as drift_exc:
        verify_provenance_fingerprints(obs1, custom_schema_obs)
    assert drift_exc.value.diagnostics[0].code == "backup-observation-drift"

    toc_ok = ("1; 2615 16384 SCHEMA - app space_α repomap\n2; 2615 16385 SCHEMA - app_core repomap\n3; 1259 16390 TABLE app space_α my items repomap\n").encode("utf-8")
    toc_res = parse_and_verify_toc_provenance(toc_ok, database="repomap", database_catalog=custom_schema_obs.database_catalog)
    assert toc_res.schemas == ("app space_α", "app_core")

    prereq_obs = parse_and_validate_catalog_observation(
        _obs_bytes(
            extensions=[_ext("ext_c", prereqs=["ext_b"], cfg=['public."cfg seq"', 'app_α."select"'], cond=["", "WHERE 1=1"]), _ext("ext_b", prereqs=["ext_a"]), _ext("ext_a")],
            config_tables=[
                {"extension": "ext_c", "schema": "public", "table": "cfg seq", "qualified_table": 'public."cfg seq"', "relkind": "S", "condition": ""},
                {"extension": "ext_c", "schema": "app_α", "table": "select", "qualified_table": 'app_α."select"', "relkind": "r", "condition": "WHERE 1=1"},
            ],
        ),
        database="repomap",
    )
    prereq_exts: Any = prereq_obs.database_catalog["installed_extensions"]
    assert [e["name"] for e in prereq_exts] == ["ext_a", "ext_b", "ext_c"]
    assert prereq_exts[0]["trusted"] is None
    assert prereq_exts[2]["prerequisite_extensions"] == ["ext_a", "ext_b"]
    seq_toc = "1; 3079 16385 EXTENSION - ext_a \n2; 3079 16386 EXTENSION - ext_b \n3; 3079 16387 EXTENSION - ext_c \n4; 0 16399 SEQUENCE SET public cfg seq repomap\n5; 0 16400 TABLE DATA app_α select repomap\n".encode("utf-8")
    verified_seq = parse_and_verify_toc_provenance(seq_toc, database="repomap", database_catalog=prereq_obs.database_catalog)
    assert verified_seq.sequence_set == ("public cfg seq",) and verified_seq.table_data == ("app_α select",)

    for bad_obs in (
        b"OVERFLOW:2097153\n",
        _obs_bytes(extensions=[_ext("a", prereqs=["b"]), _ext("b", prereqs=["a"])]),
        json.dumps({"server_provenance": default_baseline_server_provenance(), "database_catalog": dict(default_baseline_database_catalog(owner="repomap"), extension_dependency_summary={"by_class": {}, "edge_count": 5, "edges": []})}).encode("utf-8"),
        b"x" * (MAX_QUERY_OBSERVED_OUTPUT_BYTES + 1),
        _obs_bytes(extensions=[_ext(f"ext_{i}") for i in range(MAX_EXTENSIONS_PER_DATABASE + 1)]),
    ):
        with pytest.raises(LocalDbBackupError) as bad_obs_exc:
            parse_and_validate_catalog_observation(bad_obs, database="repomap")
        assert bad_obs_exc.value.diagnostics[0].code == "backup-observation-incomplete"

    with pytest.raises(LocalDbBackupError) as toc_exc:
        parse_and_verify_toc_provenance(b"1; 3079 16385 EXTENSION - vector \n", database="repomap", database_catalog=obs1.database_catalog)
    assert toc_exc.value.diagnostics[0].code == "backup-toc-inconsistent"


def test_run_bounded_popen_enforces_streaming_cap_and_redacts_secrets() -> None:
    with pytest.raises(LocalDbBackupError) as cap_exc:
        run_bounded_popen(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'A' * (4 * 1024 * 1024))"],
            max_output_bytes=512, timeout_seconds=10.0, error_code="backup-toc-inconsistent", field="repomap", secret="super-secret-pw",
        )
    assert cap_exc.value.diagnostics[0].code == "backup-toc-inconsistent"

    with pytest.raises(LocalDbBackupError) as red_exc:
        run_bounded_popen(
            [sys.executable, "-c", "import sys; sys.stderr.write('pw=super-secret-pw\\n'); sys.exit(1)"],
            max_output_bytes=1024, timeout_seconds=10.0, error_code="backup-observation-incomplete", field="repomap", secret="super-secret-pw",
        )
    assert "super-secret-pw" not in red_exc.value.diagnostics[0].message and "[REDACTED]" in red_exc.value.diagnostics[0].message


def test_extension_blockers_gate_dump_init_drop_and_upgrades(tmp_path: Path) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    identity = plan.identity
    with pytest.raises(LocalDbBackupError) as mw_exc:
        with acquire_or_reuse_backup_maintenance_window(plan, ("unheld_db",), command_runner=subprocess.run, require_window=True):
            pass
    assert mw_exc.value.diagnostics[0].code == "backup-maintenance-window-unavailable"

    vector_obs = _obs_bytes(
        extensions=[_ext("vector", version="0.8.7", schema="custom_ext", relocatable=False, cfg=["custom_ext.vec_cfg"], cond=["WHERE active"])],
        schemas=[{"name": "custom_ext", "owner": "repomap"}, {"name": "public", "owner": "repomap"}],
        config_tables=[{"extension": "vector", "schema": "custom_ext", "table": "vec_cfg", "qualified_table": "custom_ext.vec_cfg", "condition": "WHERE active"}],
        edges=[{"extension": "vector", "object_class": "pg_class", "object_schema": "public", "object_identity": "public.items", "deptype": "n"}],
    )
    vector_toc = b"1; 2615 16384 SCHEMA - custom_ext repomap\n2; 3079 16385 EXTENSION - vector \n3; 0 16390 TABLE DATA custom_ext vec_cfg repomap\n"

    def ext_runner(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        cmd_str = " ".join(str(x) for x in cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=_owned_container_json(identity), stderr="")
        if "repomap_d9_catalog_observation" in cmd_str:
            return subprocess.CompletedProcess(cmd, 0, stdout=vector_obs, stderr=b"")
        if "/usr/bin/pg_dump" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"PGDMP-vector-dump-bytes", stderr=b"")
        if "/usr/bin/pg_restore" in cmd and "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=vector_toc, stderr=b"")
        if "-tAc" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"1\n", stderr=b"")
        if "CREATE DATABASE" in cmd_str or "DROP DATABASE" in cmd_str:
            raise AssertionError(f"destructive SQL executed despite blocker: {cmd_str}")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    dump_res = dump_database(home, database="repomap", timestamp="20261020T120001Z", command_runner=ext_runner)
    assert dump_res.restore_supported is False
    assert set(dump_res.restore_blockers) >= {
        "extension-not-allowlisted", "extension-restore-protocol-unimplemented",
        "extension-schema-unsupported", "extension-config-table-unsupported", "extension-dependency-unsupported",
    }
    info = read_backup_info(home, dump_res.plan.backup_id).to_jsonable()
    for private_key in ("server_provenance", "artifact_provenance", "database_catalogs", "quiescence"):
        assert private_key not in info["manifest"]
    restore_md = dump_res.plan.restore_path.read_text(encoding="utf-8")
    assert "restore_supported=false" in restore_md and "extension-not-allowlisted" in restore_md

    with pytest.raises(LocalDbBackupError) as init_exc:
        init_database_from_dump(home, database="repomap", backup=dump_res.plan.backup_path, command_runner=ext_runner)
    assert "backup-extension-restore-unsupported" in [d.code for d in init_exc.value.diagnostics]

    with pytest.raises(LocalDbBackupError) as drop_exc:
        drop_database(home, database="repomap", backup_first=True, confirmed=True, timestamp="20261020T120002Z", command_runner=ext_runner)
    assert "backup-extension-restore-unsupported" in [d.code for d in drop_exc.value.diagnostics]


def test_coordinated_restore_single_graph_extraction_and_control_upgrade_refusal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    identity = plan.identity
    cat_graph = parse_and_validate_catalog_observation(_obs_bytes(), database="repomap").database_catalog
    cat_ctrl = parse_and_validate_catalog_observation(_obs_bytes(extensions=[_ext("vector", version="0.8.7")]), database="repomap_control").database_catalog

    def runner(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        cmd_str = " ".join(str(x) for x in cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=_owned_container_json(identity), stderr="")
        if "CREATE DATABASE" in cmd_str:
            raise AssertionError("CREATE DATABASE must not run when coordinated set is blocked")
        prov = maybe_provenance_runner_result(cmd)
        return prov if prov is not None else subprocess.CompletedProcess(cmd, 0, stdout=b"0\n", stderr=b"")

    coord_dir = home / "backups" / "all-databases" / "20261020T120000Z"
    coord_dir.mkdir(parents=True)
    dump_files = []
    for db in plan.owned_databases:
        p = coord_dir / f"{db}.pgcustom"
        p.write_bytes(f"PGDMP-dump-{db}".encode("utf-8"))
        dump_files.append({"name": p.name, "size_bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    toc_sha = hashlib.sha256(baseline_toc_bytes()).hexdigest()
    coord_manifest = {
        "backup_format_version": 2, "backup_id": "coord-mixed", "scope": COORDINATED_SCOPE,
        "databases": list(plan.owned_databases), "recovery_point": dict(STABLE_RECOVERY_POINT),
        "dump_files": dump_files, "dump_format": "pgcustom", "restore_protocol": "core_v1",
        "restore_supported": True, "restore_blockers": [],
        "server_provenance": default_baseline_server_provenance(),
        "artifact_provenance": {
            "archive_bindings": [
                {"database": str(d["name"]).removesuffix(".pgcustom"), "dump_file": d["name"], "sha256": d["sha256"], "size_bytes": d["size_bytes"], "toc_sha256": toc_sha}
                for d in dump_files
            ],
            "dump_format": "pgcustom",
        },
        "database_catalogs": {"repomap": cat_graph, "repomap_control": cat_ctrl},
        "quiescence": {"verified": True, "before_after_fingerprint_matched": True, "mode": "coordinated-maintenance-window"},
    }
    (coord_dir / "manifest.json").write_text(json.dumps(coord_manifest), encoding="utf-8")

    with pytest.raises(LocalDbBackupError) as coord_exc:
        restore_coordinated_backup(home, backup=coord_dir, command_runner=runner)
    assert "backup-extension-restore-unsupported" in [d.code for d in coord_exc.value.diagnostics]

    dry_single = init_database_from_dump(home, database="repomap", backup=coord_dir, dry_run=True, command_runner=runner)
    assert dry_single.result == "dry_run"

    bad_toc_manifest = json.loads(json.dumps(coord_manifest))
    bad_toc_manifest["artifact_provenance"]["archive_bindings"][0]["toc_sha256"] = "0" * 64
    with pytest.raises(LocalDbBackupError) as toc_sha_exc:
        verify_archive_toc_for_restore(plan, bad_toc_manifest, database="repomap", dump_path=coord_dir / "repomap.pgcustom", command_runner=runner)
    assert toc_sha_exc.value.diagnostics[0].code == "backup-toc-inconsistent"
    (coord_dir / "manifest.json").write_text(json.dumps(bad_toc_manifest), encoding="utf-8")
    insp_bad_toc = inspect_backup(home, coord_dir, command_runner=runner)
    assert "backup-toc-inconsistent" in [d.code for d in insp_bad_toc.diagnostics]

    bad_inspect = SimpleNamespace(
        manifest={"backup_format_version": 2, "restore_supported": False, "restore_blockers": ["extension-not-allowlisted"]},
        checksum_verified=True, dump_contents_read=True, toc_entry_count=1, diagnostics=(),
    )
    with pytest.raises(LocalDbBackupError) as upg_exc:
        require_verified_backup_inspection_supported(bad_inspect, database="repomap_control")
    assert "backup-extension-restore-unsupported" in [d.code for d in upg_exc.value.diagnostics]

    with pytest.raises(LocalDbBackupError) as art_exc:
        evaluate_release_cluster_upgrade_artifact(
            {"schema_version": 2, "restore_supported": False, "restore_blockers": ["extension-not-allowlisted"], "database_catalog": cat_ctrl},
            database="repomap_control",
        )
    assert "backup-extension-restore-unsupported" in [d.code for d in art_exc.value.diagnostics]
