"""Slice15 repair & Order 4: load real layered configuration and consume resolved ops/readback/baseline/source records."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import threading
from typing import Any, cast

import pytest

from repomap_kg.ops.baseline_operations import (
    BaselineOperationDependencies,
    prune_graph_baselines,
    query_drift_check,
    save_graph_baselines,
)
from repomap_kg.ops.config import (
    OpsConfigError,
    check_ops_graph_storage_status,
    load_ops_config,
    load_ops_config_home,
)
from repomap_kg.ops.config_status import (
    format_ops_graph_registry_table,
    ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable,
)
from repomap_kg.ops.graph_files import GraphFileFilters, query_graph_files
from repomap_kg.ops.reports import (
    OpsGraphSummary,
    OpsRefreshError,
    format_baseline_prune_table,
    format_baseline_save_table,
    format_drift_check_table,
    format_refresh_status_table,
)
from repomap_kg.ops.source_generation import (
    SourceGenerationLimits,
    scan_source_generation,
)
from repomap_kg.storage.authority import RefreshResult
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


def test_s15_b07_ops_config_payload_merging_matrix(tmp_path: Path) -> None:
    (tmp_path / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private")
    )
    (tmp_path / "overlay.rpl.toml").write_text(
        'schema_version = 1\n[service]\nlog_level = "debug"\n'
        '[postgres]\nport = 5433\n'
    )
    config = load_ops_config_home(tmp_path)
    assert config.service.mode == "local"
    assert config.service.log_level == "debug"
    assert config.postgres.port == 5433
    assert config.config_files == ("base.rp.toml", "overlay.rpl.toml")
    codes = {diagnostic.code for diagnostic in config.diagnostics}
    assert {"service-overlay", "postgres-overlay"} <= codes
    payload = ops_config_status_to_jsonable(config)
    assert payload["service"]["log_level"] == "debug"
    assert payload["postgres"]["port"] == 5433
    (tmp_path / "overlay.rpl.toml").unlink()
    restored = load_ops_config_home(tmp_path)
    assert restored.service.log_level == "info"
    assert restored.postgres.port == 5432
    assert not {"service-overlay", "postgres-overlay"} & {
        diagnostic.code for diagnostic in restored.diagnostics
    }


def test_config_storage_graphs_loading_records_status_and_file_records(tmp_path: Path) -> None:
    """Layered config homes, graph storage readback, and file readback compose over TOML files and psql."""
    sqlite_home = tmp_path / "sqlite_home"
    sqlite_home.mkdir()
    (sqlite_home / "base.rp.toml").write_text(
        'schema_version = 1\n[storage]\nbackend = "sqlite"\nextra = 1\n'
        f'[[graphs]]\nid = "g1"\nname = "G1"\nroot_path = "{tmp_path}"\nrepository_name = "g1"\n',
        encoding="utf-8",
    )
    with pytest.raises(OpsConfigError) as sq_err:
        load_ops_config_home(sqlite_home)
    assert any(d.code == "unknown-storage-field" for d in sq_err.value.diagnostics)

    conflict_home = tmp_path / "conflict_home"
    conflict_home.mkdir()
    (conflict_home / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private"),
        encoding="utf-8",
    )
    (conflict_home / "overlay.rpl.toml").write_text(
        'schema_version = 1\n[storage]\nbackend = "sqlite"\n',
        encoding="utf-8",
    )
    with pytest.raises(OpsConfigError) as conf_err:
        load_ops_config_home(conflict_home)
    assert any(d.code == "storage-backend-conflict" for d in conf_err.value.diagnostics)

    diag_file = tmp_path / "diag_single.rp.toml"
    diag_file.write_text(
        'schema_version = 1\n'
        '[storage]\nbackend = "other"\n'
        '[runtime.postgres]\nhost = "127.0.0.1"\nport = 5432\n'
        '[sources]\nfeed = "not-a-list"\n'
        '[[graphs]]\nid = "BAD ID!"\nroot_path = "/tmp/a"\nsource_bindings = []\n'
        'database = "1bad_db"\nrefresh_policy = "bad-policy"\n'
        '[[graphs]]\nid = "g_bad1"\nroot_path = "/tmp/a"\ndatabase = "repomap_g1"\n'
        'privacy = "bad-privacy"\nrefresh_policy = "manual"\nexclude_paths = "not-a-list"\n'
        '[[graphs]]\nid = "g_dup"\nroot_path = "/tmp/b"\ndatabase = "repomap_g2"\n'
        'privacy = "public-dev"\nrefresh_policy = "manual"\nexclude_paths = [""]\n'
        '[[graphs]]\nid = "g_dup"\nroot_path = "/tmp/c"\ndatabase = "repomap_g3"\n'
        'privacy = "public-dev"\nrefresh_policy = "manual"\n',
        encoding="utf-8",
    )
    with pytest.raises(OpsConfigError) as diag_err:
        load_ops_config(diag_file)
    diag_codes = {d.code for d in diag_err.value.diagnostics}
    assert {
        "unsupported-storage-backend", "ambiguous-graph-source-syntax", "invalid-graph-id",
        "invalid-graph-database", "unsupported-graph-privacy", "unsupported-refresh-policy",
        "invalid-graph-exclude-paths", "invalid-graph-exclude-path", "duplicate-graph-id",
    } <= diag_codes

    warn_home = tmp_path / "warn_home"
    warn_home.mkdir()
    (warn_home / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private")
        + '\n[runtime.postgres]\nport = 5432\n'
        + '[[sources.github]]\nid = "s1"\ngraph_id = "repo-map_dev"\nenabled = true\nurl = "https://example.invalid/a"\n'
        + '[[sources.github]]\nid = "s1"\ngraph_id = "repo-map_dev"\nenabled = true\nurl = "https://example.invalid/b"\n',
        encoding="utf-8",
    )
    (warn_home / "over.rpl.toml").write_text(
        'schema_version = 1\n'
        '[runtime.postgres]\nport = 5433\n'
        '[[sources.github]]\nid = "s1"\ngraph_id = "repo-map_dev"\nenabled = true\nurl = "https://example.invalid/c"\n',
        encoding="utf-8",
    )
    warn_cfg = load_ops_config_home(warn_home)
    codes = {d.code for d in warn_cfg.diagnostics}
    assert {"duplicate-source-id", "source-overlay", "runtime-overlay"} <= codes, codes

    pg_home = tmp_path / "pg_home"
    pg_home.mkdir()
    (pg_home / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private"),
        encoding="utf-8",
    )
    pg_cfg = load_ops_config_home(pg_home)
    assert "unchecked" in format_ops_graph_registry_table(pg_cfg)

    fake_status_psql = tmp_path / "fake-psql-status"
    fake_status_psql.write_text(
        '#!/bin/sh\n'
        'query=$(cat)\ncase "$query" in\n'
        '  *required_tables*) printf \'%s\\n\' \'{"connected":true,"schema_available":true,"required_tables":{"repositories":true}}\' ;;\n'
        '  *) printf \'%s\\n\' \'{"graphs":[{"repository_name":"repo-map","repository_exists":true,"repository_id":1,"raw_observations":5,"raw_observations_total":5,"latest_run_raw_observations":5,"canonical_nodes":3,"canonical_edges":2}]}\' ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    fake_status_psql.chmod(0o700)
    statuses = check_ops_graph_storage_status(pg_cfg, psql_command=str(fake_status_psql))
    reg_table = format_ops_graph_registry_table(pg_cfg, graph_storage_status=statuses)
    reg_json = ops_graph_registry_status_to_jsonable(pg_cfg, graph_storage_status=statuses)
    assert "ready(" in reg_table, reg_table
    assert reg_json["graphs"][0]["storage_status"]["repository_exists"] is True

    # query_graph_files via real fake-psql readback subprocess
    base_rec: dict[str, Any] = {
        "canonical_key": "file:src/a.py", "graph_key_version": 1,
        "metadata": {"language": "python", "generated": False, "executable": [False]},
        "link_kinds": ["defines"], "evidence_count": 2, "file_observation_count": 1,
        "confidence": "high", "conflict": False,
    }
    fake_psql = tmp_path / "fake-psql-files"
    fake_psql.write_text(f"#!/bin/sh\nprintf '%s\\n' '{json.dumps([base_rec])}'\n", encoding="utf-8")
    fake_psql.chmod(0o700)
    page = query_graph_files(pg_cfg, pg_cfg.graphs[0].id, filters=GraphFileFilters(path_prefix="."), psql_command=str(fake_psql))
    assert page.records[0].path == "src/a.py"

    for bad_payload in (
        '["not-an-object"]',
        json.dumps([{**base_rec, "canonical_key": "bad:key"}]),
        json.dumps([{**base_rec, "file_observation_count": 5}]),
    ):
        fake_psql.write_text(f"#!/bin/sh\nprintf '%s\\n' '{bad_payload}'\n", encoding="utf-8")
        with pytest.raises(OpsRefreshError, match="file readback failed"):
            query_graph_files(pg_cfg, pg_cfg.graphs[0].id, filters=GraphFileFilters(), psql_command=str(fake_psql))


def test_baselines_reports_and_source_generation_edge_contracts(tmp_path: Path) -> None:
    """Baselines save/prune/drift, reports formatting, and source generation enforce filesystem and scan limits."""
    (tmp_path / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private")
    )
    config = load_ops_config_home(tmp_path)
    gid = config.graphs[0].id

    b_root = tmp_path / "status" / "baselines"
    b_root.mkdir(parents=True)
    g_root = b_root / gid
    os.symlink(tmp_path, g_root)
    with pytest.raises(OpsRefreshError, match="outside REPOMAP_HOME"):
        prune_graph_baselines(config, gid, kind="stored", keep=1)
    g_root.unlink()

    bad_dir = g_root / "stored"
    bad_dir.parent.mkdir(parents=True, exist_ok=True)
    bad_dir.write_text("file", encoding="utf-8")
    with pytest.raises(OpsRefreshError, match="not a directory"):
        prune_graph_baselines(config, gid, kind="stored", keep=1, dry_run=False)
    bad_dir.unlink()

    ok_summary = OpsGraphSummary(
        graph_id=gid, repository_name="repo", database="repomap_g1", privacy="public-dev",
        enabled=True, mcp_visible=True, root_path_display="repo", root_path_expanded=str(tmp_path),
        result=RefreshResult.SUCCESS, files=1, raw_observations=2, canonical_nodes=1, canonical_edges=1,
        language_counts={"python": 1},
    )
    ok_deps = BaselineOperationDependencies(
        query_graph_summary=lambda *_a, **_kw: ok_summary,
        preflight_graph=lambda *_a, **_kw: cast(Any, type("P", (), {"result": "success", "warnings": (), "diagnostics": ()})()),
        preflight_to_jsonable=lambda *_a, **_kw: {
            "graph": {
                "graph_id": gid, "files_considered": 1, "path_examples_included": False,
                "language_counts": {"python": 1},
            },
            "safety": {"storage_written": False},
        },
    )
    save_graph_baselines(config, gid, kind="both", timestamp="20260101T000000Z", dependencies=ok_deps)
    save_r2 = save_graph_baselines(config, gid, kind="both", timestamp="20260102T000000Z", dependencies=ok_deps)
    assert "saved: kind=stored" in format_baseline_save_table(config, save_r2)
    with pytest.raises(OpsRefreshError, match="already exists"):
        save_graph_baselines(config, gid, kind="stored", timestamp="20260101T000000Z", dependencies=ok_deps)

    (g_root / "stored" / "ignored.txt").write_text("{}", encoding="utf-8")
    prune_res = prune_graph_baselines(config, gid, kind="both", keep=1, dry_run=False)
    assert prune_res.processed[0].deleted_count == 1 and prune_res.processed[0].ignored_count == 1
    assert "processed: kind=stored" in format_baseline_prune_table(config, prune_res)

    stored_baseline = json.loads((g_root / "stored" / "latest.json").read_text(encoding="utf-8"))
    preflight_baseline = json.loads((g_root / "preflight" / "latest.json").read_text(encoding="utf-8"))
    drifted_summary = replace(ok_summary, files=2, language_counts={"python": 2})
    drifted_deps = BaselineOperationDependencies(
        query_graph_summary=lambda *_a, **_kw: drifted_summary,
        preflight_graph=ok_deps.preflight_graph,
        preflight_to_jsonable=lambda *_a, **_kw: {
            "graph": {
                "graph_id": gid, "files_considered": 2, "path_examples_included": True,
                "language_counts": {"python": 2},
            },
            "safety": {"storage_written": True},
        },
    )
    drift_ok = query_drift_check(
        config, gid, baseline=stored_baseline, include_preflight=True,
        preflight_baseline=preflight_baseline, dependencies=drifted_deps,
    )
    assert drift_ok.drift_detected is True and drift_ok.preflight_drift_detected is True
    assert "preflight_safety_drift: storage_written" in format_drift_check_table(config, drift_ok)

    disabled_graph = replace(config.graphs[0], enabled=False)
    cfg_disabled = replace(config, graphs=(disabled_graph,))
    failed_summary = replace(ok_summary, result=RefreshResult.FAILURE)
    fail_deps = BaselineOperationDependencies(
        query_graph_summary=lambda *_a, **_kw: failed_summary,
        preflight_graph=lambda *_a, **_kw: cast(Any, type("P", (), {"result": "failed"})()),
        preflight_to_jsonable=lambda *_a, **_kw: {},
    )
    with pytest.raises(OpsRefreshError, match="is disabled"):
        save_graph_baselines(cfg_disabled, disabled_graph.id, kind="stored", dependencies=fail_deps)
    with pytest.raises(OpsRefreshError, match="requires --repo-map-home"):
        save_graph_baselines(replace(config, config_home=None), gid, kind="stored", dependencies=fail_deps)
    with pytest.raises(OpsRefreshError, match="failed; baseline was not saved"):
        save_graph_baselines(config, gid, kind="preflight", dependencies=fail_deps)
    with pytest.raises(OpsRefreshError, match="is disabled"):
        prune_graph_baselines(cfg_disabled, disabled_graph.id, kind="stored", keep=1)
    with pytest.raises(OpsRefreshError, match="keep N where N >= 1"):
        prune_graph_baselines(config, gid, kind="stored", keep=0)
    with pytest.raises(OpsRefreshError, match="unknown graph id"):
        format_refresh_status_table(config, {}, graph_ids=(gid, gid, "missing_g"))
    assert query_drift_check(config, gid, baseline=stored_baseline, dependencies=fail_deps).result == "failure"

    # source_generation.py
    with pytest.raises(ValueError, match="source generation limits are invalid"):
        SourceGenerationLimits(max_files=0).validate()

    scan_dir = tmp_path / "scan_src"
    (scan_dir / "pkg" / "sub").mkdir(parents=True)
    (scan_dir / "pkg" / "sub" / "file.py").write_text("z = 0\n", encoding="utf-8")
    (scan_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
    (scan_dir / "b.py").write_text("y = 2\n", encoding="utf-8")
    excl_scan = scan_source_generation(scan_dir, exclude_paths=("pkg/*", "pkg/sub"))
    assert excl_scan.category == "ready" and excl_scan.file_count == 2
    assert scan_source_generation(scan_dir, limits=SourceGenerationLimits(max_path_chars=2)).category == "source_limit_exceeded"
    assert scan_source_generation(scan_dir, limits=SourceGenerationLimits(max_files=1)).category == "source_limit_exceeded"
    ev = threading.Event()
    ev.set()
    assert scan_source_generation(scan_dir, cancel_event=ev).category == "cancelled"
    ticks = iter([0.0, 10.0, 20.0])
    assert scan_source_generation(scan_dir, monotonic=lambda: next(ticks, 20.0), limits=SourceGenerationLimits(timeout_seconds=1.0)).category == "source_timeout"
    os.symlink(scan_dir / "a.py", scan_dir / "link.py")
    assert scan_source_generation(scan_dir).category == "source_invalid"
