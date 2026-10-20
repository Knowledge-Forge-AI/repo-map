"""Order 4 integration contracts for portable retention, portable refresh, SQLite local ops, and readback error classification."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket

import pytest

from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.ops._portable_retention import (
    EXPIRED_TERMINAL,
    INCOMPLETE,
    RETAINED_TERMINAL,
    UNSAFE,
    UNSETTLED,
    PortableRefreshError,
    _annotate_retained_attempt,
    _classify_attempt,
    _local_attempt_directory,
    _mark_retained_terminal,
    _prune_expired_terminal_attempts,
    _read_retention_payload,
    _retained_result,
    _unsettled_retained_attempts,
    _write_retained_result,
    remove_expired_terminal_attempt,
)
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.config_helpers import OpsConfigDiagnostic
from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    build_local_sqlite_config_from_payload,
)
from repomap_kg.ops.local_cleanup import (
    LocalCleanupError,
    cleanup_local_graph,
)
from repomap_kg.ops.local_ops_status import (
    format_local_config_status_table,
    format_local_graph_registry_table,
)
from repomap_kg.ops.local_refresh import (
    ATTEMPT_BLOCK,
    LocalRefreshError,
    initialize_local_graph,
    refresh_local_graph,
)
from repomap_kg.ops.portable_refresh import _attempt_root, _worker_references
from repomap_kg.ops.readback import (
    MissingDatabaseReadbackError,
    execute_ops_json_readback,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


def _sample_refs() -> tuple[ArtifactReference, ArtifactReference]:
    return (
        ArtifactReference(
            content_digest="sha256:" + "a" * 64, size_bytes=32,
            media_type="application/octet-stream", record_format="json-v1",
            privacy=PrivacyClassification.PUBLIC,
            locator=ArtifactLocator("filesystem", "sha256/aa/" + "a" * 64),
        ),
        ArtifactReference(
            content_digest="sha256:" + "b" * 64, size_bytes=64,
            media_type="application/octet-stream", record_format="jsonl-v1",
            privacy=PrivacyClassification.PUBLIC,
            locator=ArtifactLocator("filesystem", "sha256/bb/" + "b" * 64),
        ),
    )


def _local_sqlite_config(root: Path, src_dir: Path) -> LocalSqliteConfig:
    src_dir.mkdir(parents=True, exist_ok=True)
    return build_local_sqlite_config_from_payload(
        {
            "schema_version": 1,
            "storage": {"backend": "sqlite"},
            "service": {"mode": "local", "mcp_transport": "stdio", "log_level": "info"},
            "graphs": [{
                "id": "g-local", "name": "Local Graph", "root_path": str(src_dir),
                "repository_name": "g-local", "privacy": "public-dev", "enabled": True,
                "mcp_visible": True, "extractor_profile": "default", "refresh_policy": "manual",
            }],
            "server_memory": {"enabled": False, "path": str(root / "mem"), "mode": "read_only"},
        },
        config_path=str(root), config_home=str(root), config_files=("base.rp.toml",),
        diagnostics=(OpsConfigDiagnostic("warning", "w1", "service", "warn"),),
    )


def test_portable_retention_read_write_annotate_classify_and_prune(tmp_path: Path) -> None:
    """Portable retention records enforce owner permissions, schema fields, classification, and expiry pruning."""
    refs = _sample_refs()
    missing_path = tmp_path / "missing.json"
    assert _retained_result(missing_path, "m" * 64) is None

    rec_path = tmp_path / "portable-result.json"
    _write_retained_result(rec_path, "e" * 64, refs)
    loaded_refs = _retained_result(rec_path, "e" * 64)
    assert loaded_refs == refs

    with pytest.raises(PortableRefreshError, match="retained portable result is invalid"):
        _retained_result(rec_path, "f" * 64)

    # _annotate_retained_attempt valid and duplicate/terminal refusal
    _annotate_retained_attempt(rec_path, "extra_block", {"k": "v"})
    with pytest.raises(PortableRefreshError, match="cannot be annotated"):
        _annotate_retained_attempt(rec_path, "extra_block", {"k": "v2"})

    with pytest.raises(ValueError, match="invalid portable retention class"):
        _mark_retained_terminal(rec_path, "bad-class")

    _mark_retained_terminal(rec_path, "terminal-accepted")
    with pytest.raises(PortableRefreshError, match="cannot be annotated"):
        _annotate_retained_attempt(rec_path, "new_block", {"k": "v"})

    # Invalid payload cases for _retained_result and _read_retention_payload
    for bad_payload in (
        {"manifest_id": "e" * 64, "retention_class": "bad-class", "receipt": {}, "bundle": {}},
        {"manifest_id": "e" * 64, "retention_class": "publication-reconciliation", "receipt": "bad", "bundle": {}},
    ):
        rec_path.write_text(json.dumps(bad_payload), encoding="utf-8")
        rec_path.chmod(0o600)
        with pytest.raises(PortableRefreshError, match="retained portable result is invalid"):
            _retained_result(rec_path, "e" * 64)

    rec_path.write_text("[1, 2, 3]", encoding="utf-8")
    rec_path.chmod(0o600)
    with pytest.raises(ValueError):
        _read_retention_payload(rec_path)

    rec_path.chmod(0o644)
    with pytest.raises(ValueError):
        _read_retention_payload(rec_path)

    # _local_attempt_directory refusal outside Local retention namespace
    with pytest.raises(PortableRefreshError, match="outside the Local retention namespace"):
        _local_attempt_directory(rec_path)

    # _unsettled_retained_attempts & _prune_expired_terminal_attempts & _classify_attempt
    attempts_dir = tmp_path / "attempts"
    attempts_dir.mkdir(mode=0o700)
    inc_dir = attempts_dir / "01_incomplete"
    inc_dir.mkdir(mode=0o700)
    unsettled_dir = attempts_dir / "02_unsettled"
    unsettled_dir.mkdir(mode=0o700)
    _write_retained_result(unsettled_dir / "portable-result.json", "e" * 64, refs)
    expired_dir = attempts_dir / "03_expired"
    expired_dir.mkdir(mode=0o700)
    _write_retained_result(expired_dir / "portable-result.json", "e" * 64, refs)
    _mark_retained_terminal(expired_dir / "portable-result.json", "terminal-failed")
    exp_payload = _read_retention_payload(expired_dir / "portable-result.json")
    exp_payload["expires_at_epoch"] = 10
    (expired_dir / "portable-result.json").write_text(json.dumps(exp_payload), encoding="utf-8")
    (expired_dir / "portable-result.json").chmod(0o600)

    unsettled_list = _unsettled_retained_attempts(attempts_dir)
    assert len(unsettled_list) == 1 and unsettled_list[0][0] == unsettled_dir / "portable-result.json"

    assert _classify_attempt(inc_dir, 100)[0] == INCOMPLETE
    assert _classify_attempt(unsettled_dir, 100)[0] == UNSETTLED
    assert _classify_attempt(expired_dir, 5)[0] == RETAINED_TERMINAL
    exp_status, exp_id = _classify_attempt(expired_dir, 100)
    assert exp_status == EXPIRED_TERMINAL and exp_id is not None

    with pytest.raises(ValueError, match="retained portable attempt changed"):
        remove_expired_terminal_attempt(expired_dir, None, now=100)
    with pytest.raises(ValueError, match="retained portable attempt changed"):
        remove_expired_terminal_attempt(expired_dir, exp_id, now=5)

    # Non-removable hardlink inside expired_dir makes it UNSAFE
    sub_dir = expired_dir / "sub"
    sub_dir.mkdir(mode=0o700)
    f_orig = sub_dir / "a.txt"
    f_orig.write_text("hi", encoding="utf-8")
    f_link = sub_dir / "b.txt"
    os.link(f_orig, f_link)
    assert _classify_attempt(expired_dir, 100)[0] == UNSAFE
    f_link.unlink()

    # Invalid expires_at_epoch makes it UNSAFE
    exp_payload["expires_at_epoch"] = True
    (expired_dir / "portable-result.json").write_text(json.dumps(exp_payload), encoding="utf-8")
    (expired_dir / "portable-result.json").chmod(0o600)
    assert _classify_attempt(expired_dir, 100)[0] == UNSAFE

    # Restore integer expires_at_epoch and prune
    exp_payload["expires_at_epoch"] = 10
    (expired_dir / "portable-result.json").write_text(json.dumps(exp_payload), encoding="utf-8")
    (expired_dir / "portable-result.json").chmod(0o600)
    _prune_expired_terminal_attempts(attempts_dir, exclude=unsettled_dir)
    assert not expired_dir.exists()
    assert unsettled_dir.exists()

    # Non-directory entry in attempts_dir causes _unsettled_retained_attempts to refuse
    (attempts_dir / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PortableRefreshError, match="retained portable attempt is invalid"):
        _unsettled_retained_attempts(attempts_dir)


def test_portable_refresh_worker_references_and_overlap_refusals(tmp_path: Path) -> None:
    """_worker_references classifies failure categories and _attempt_root refuses overlapping source paths."""
    for terminal, expected_cat in (
        ({"status": "failed", "error_category": "contract_validation"}, "contract_validation"),
        ({"status": "failed", "error_category": "worker_execution"}, "worker_crash"),
        ({"status": "failed", "error_category": "worker_crash", "reason": "process_timeout"}, "worker_timeout"),
        ({"status": "failed", "error_category": "worker_crash", "reason": "protocol"}, "protocol"),
    ):
        with pytest.raises(PortableRefreshError) as exc_info:
            _worker_references(terminal)
        assert exc_info.value.category == expected_cat

    (tmp_path / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private")
    )
    config = load_ops_config_home(tmp_path)
    with pytest.raises(PortableRefreshError, match="portable artifact root overlaps source"):
        _attempt_root(config, config.graphs[0], "op1", 1)


def test_local_refresh_cleanup_and_status_formatting_contracts(tmp_path: Path) -> None:
    """SQLite local refresh, cleanup, and status formatting enforce graph state and safety boundaries."""
    home, src_dir = tmp_path / "home", tmp_path / "src"
    cfg = _local_sqlite_config(home, src_dir)
    graph, refs = cfg.graphs[0], _sample_refs()

    with pytest.raises(LocalRefreshError, match="unknown graph_id"):
        refresh_local_graph(cfg, "missing")
    with pytest.raises(LocalCleanupError, match="unknown graph_id"):
        cleanup_local_graph(cfg, "missing", execute=False)

    cfg_disabled = replace(cfg, graphs=(replace(graph, enabled=False),))
    with pytest.raises(LocalRefreshError, match="is disabled"):
        refresh_local_graph(cfg_disabled, graph.id)

    disabled_binding = replace(graph.effective_source_bindings[0], enabled=False)
    cfg_unsup = replace(cfg, graphs=(replace(graph, source_bindings=(disabled_binding,), explicit_source_bindings=True),))
    with pytest.raises(LocalRefreshError, match="unsupported"):
        refresh_local_graph(cfg_unsup, graph.id)

    with pytest.raises(LocalStoreError, match="local-state-layout-invalid"):
        refresh_local_graph(cfg, graph.id)

    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    with pytest.raises(LocalStoreError, match="sqlite-init"):
        refresh_local_graph(cfg, graph.id)

    res_dry = cleanup_local_graph(cfg, graph.id, execute=False)
    assert res_dry["result"] == "dry-run"
    res_exec = cleanup_local_graph(cfg, graph.id, execute=True)
    assert res_exec["result"] == "cleaned" and res_exec["durability"] == "not-applicable"

    init_res = initialize_local_graph(cfg, graph.id)
    assert init_res["result"] == "initialized"

    graph_attempts_dir = home / "state" / "portable-publication" / "sqlite-local" / graph.id / "attempts"
    for level in (
        home / "state" / "portable-publication",
        home / "state" / "portable-publication" / "sqlite-local",
        home / "state" / "portable-publication" / "sqlite-local" / graph.id,
        graph_attempts_dir,
    ):
        level.mkdir(mode=0o700, exist_ok=True)

    armed_dir = graph_attempts_dir / "02_armed"
    armed_dir.mkdir(mode=0o700)
    armed_rec = armed_dir / "portable-result.json"
    _write_retained_result(armed_rec, "e" * 64, refs)
    _annotate_retained_attempt(
        armed_rec, ATTEMPT_BLOCK,
        {"graph_id": graph.id, "expected_generation": -1, "publication_bundle_id": "b1", "publication_job_id": "j1", "publication_attempt": 1},
        sync_directory=True,
    )
    with pytest.raises(LocalStoreError, match="attempt-record-invalid"):
        refresh_local_graph(cfg, graph.id)

    unarmed_dir = graph_attempts_dir / "01_unarmed"
    unarmed_dir.mkdir(mode=0o700)
    unarmed_rec = unarmed_dir / "portable-result.json"
    _write_retained_result(unarmed_rec, "e" * 64, refs)

    armed_rec.unlink()
    _write_retained_result(armed_rec, "e" * 64, refs)
    _annotate_retained_attempt(
        armed_rec, ATTEMPT_BLOCK,
        {"graph_id": graph.id, "expected_generation": 0, "publication_bundle_id": "b1", "publication_job_id": "j1", "publication_attempt": 1},
        sync_directory=True,
    )
    shutil.rmtree(src_dir)
    with pytest.raises(LocalRefreshError, match="source root is unavailable"):
        refresh_local_graph(cfg, graph.id)
    assert _read_retention_payload(unarmed_rec)["retention_class"] == "terminal-failed"
    assert _read_retention_payload(armed_rec)["retention_class"] == "terminal-failed"

    legacy_attempts_dir = home / "state" / "portable-publication" / "attempts"
    legacy_attempts_dir.mkdir(mode=0o700, exist_ok=True)
    bad_graph_entry = graph_attempts_dir / "unsafe-entry.txt"
    bad_graph_entry.write_text("x", encoding="utf-8")
    bad_legacy_entry = legacy_attempts_dir / "unsafe-legacy.txt"
    bad_legacy_entry.write_text("x", encoding="utf-8")
    orphan_path = home / "state" / "sqlite-local" / "graphs" / f".{graph.id}.sqlite3.init-0123456789abcdef"
    orphan_path.write_text("stale", encoding="utf-8")
    orphan_path.chmod(0o644)

    refused_payload = cleanup_local_graph(cfg, graph.id, execute=True)
    assert refused_payload["result"] == "refused"
    assert {"unsafe-graph-attempt", "unsafe-legacy-attempt", "unsafe-orphan"} <= set(refused_payload["refusals"])

    bad_graph_entry.unlink()
    bad_legacy_entry.unlink()
    orphan_path.chmod(0o600)
    for settled_rec in (unarmed_rec, armed_rec):
        payload = _read_retention_payload(settled_rec)
        payload["expires_at_epoch"] = 10
        settled_rec.write_text(json.dumps(payload), encoding="utf-8")
        settled_rec.chmod(0o600)

    cleaned_payload = cleanup_local_graph(cfg, graph.id, execute=True)
    assert cleaned_payload["result"] == "cleaned" and cleaned_payload["durability"] == "established"
    assert cleaned_payload["orphans"]["stale_removed"] == 1
    assert cleaned_payload["graph_attempts"]["expired_terminal_removed"] == 2
    assert not orphan_path.exists()

    assert "RepoMap ops config status" in format_local_config_status_table(cfg)
    assert "g-local" in format_local_graph_registry_table(cfg)


def test_readback_container_hints_and_host_error_augmentation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """execute_ops_json_readback classifies missing binaries, container hints, missing databases, and psycopg errors."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    (tmp_path / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private").replace("port = 5432", f"port = {closed_port}")
    )
    monkeypatch.setenv("PATH", str(tmp_path))
    config = load_ops_config_home(tmp_path)
    cfg_no_home = replace(config, config_home=None)

    with pytest.raises(StorageSchemaError, match="psycopg connection failed for db1.*Direct DB host-port exposure is disabled"):
        execute_ops_json_readback(
            config, database="repomap_g1", sql="SELECT 1", label="db1",
            expected_shape="object", mode="host_only",
        )

    monkeypatch.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psql")
    with pytest.raises(StorageSchemaError, match="unable to launch psql command"):
        execute_ops_json_readback(
            config, database="repomap_g1", sql="SELECT 1", label="db1",
            expected_shape="object", mode="host_then_container",
        )

    fake_psql = tmp_path / "psql"
    fake_psql.write_text(
        '#!/bin/sh\necho \'FATAL: database "repomap_g1" does not exist\' >&2\nexit 2\n',
        encoding="utf-8",
    )
    fake_psql.chmod(0o700)
    with pytest.raises(MissingDatabaseReadbackError):
        execute_ops_json_readback(
            config, database="repomap_g1", sql="SELECT 1", label="db1",
            expected_shape="object", mode="host_only", psql_command=str(fake_psql),
        )

    fake_psql.write_text('#!/bin/sh\necho "could not connect to server: Connection refused" >&2\nexit 2\n', encoding="utf-8")
    with pytest.raises(StorageSchemaError, match="Direct DB host-port exposure is disabled"):
        execute_ops_json_readback(
            config, database="repomap_g1", sql="SELECT 1", label="db1",
            expected_shape="object", mode="host_then_container",
        )
    with pytest.raises(StorageSchemaError) as no_home_exc:
        execute_ops_json_readback(
            cfg_no_home, database="repomap_g1", sql="SELECT 1", label="db1",
            expected_shape="object", mode="host_then_container",
        )
    assert "Direct DB host-port exposure is disabled" not in str(no_home_exc.value)

    fake_psql.write_text('#!/bin/sh\nprintf \'{"ok": 1}\\n\'\n', encoding="utf-8")
    assert execute_ops_json_readback(
        config, database="repomap_g1", sql="SELECT 1", label="db1",
        expected_shape="object", mode="host_only", psql_command=str(fake_psql),
    ) == {"ok": 1}
