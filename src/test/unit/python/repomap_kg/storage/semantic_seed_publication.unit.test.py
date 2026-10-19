"""Pure unit owner for semantic seed portable publication pipeline and MCP config loading.

Tests the real source building, sealing, portable extraction, bundle validation,
and publication binding through maintained APIs, mocking only final DB publication.
Tests that generated MCP ops configuration parses and resolves cleanly via the
supported operations config loader.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest
import repomap_kg

from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability
from repomap_kg.coordinator._portable_semantic_adapter import execute_portable_extraction
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops._portable_retention import _write_retained_result
from repomap_kg.ops.portable_refresh import (
    PortableCapture,
    portable_publication_binding,
    validate_portable_capture,
)
from repomap_kg.ops.resolved_config import (
    configured_repository_identity,
    resolve_ops_config,
)
from repomap_kg.server.graph_selection import configured_graph_root_path
from repomap_kg.storage.authority import GraphRunId
from repomap_kg.storage.publication_readback import RunPublicationRecord
from repomap_kg.storage.staged_ingestion import (
    new_direct_authority,
    stage_id_for_authority,
)
from repomap_test_support.semantic_seed_publication import (
    SEED_KEY,
    SeedPublicationContext,
    build_seed_graph_config,
    build_seed_sources,
    publish_portable_seed_graph,
    run_mcp_stdio_requests,
    write_seed_mcp_config,
)


def test_seed_source_building_and_sealing(tmp_path: Path) -> None:
    source_a, source_b = build_seed_sources(tmp_path)
    assert (source_a / "src" / "common.py").is_file()
    assert (source_a / "src" / "worker_a.py").is_file()
    assert (source_a / "src" / "unindexed.py").is_file()
    assert (source_b / "src" / "common.py").is_file()
    assert (source_b / "src" / "worker_b.py").is_file()
    assert (source_b / "src" / "service_b.py").is_file()

    graph_config, binding_a_id, binding_b_id = build_seed_graph_config(
        "test-graph", "test-repo", source_a, source_b
    )
    assert len(graph_config.effective_source_bindings) == 2
    assert graph_config.effective_source_bindings[0].binding_id == binding_a_id
    assert graph_config.effective_source_bindings[1].binding_id == binding_b_id

    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700, exist_ok=True)
    store = FileSystemArtifactStore(store_root)

    manifest, manifest_ref, candidate_id = seal_configured_sources(
        graph_config,
        store,
        extractor_generation="eg1:test",
        canonicalizer_generation="kg1:test",
    )
    assert candidate_id.startswith("cand1:")
    assert store.verify(manifest_ref)
    assert len(manifest.snapshot_vector) == 2


def test_seed_portable_extraction_validation_and_binding(tmp_path: Path) -> None:
    source_a, source_b = build_seed_sources(tmp_path)
    graph_config, _, _ = build_seed_graph_config(
        "test-graph", "test-repo", source_a, source_b
    )
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700, exist_ok=True)
    store = FileSystemArtifactStore(store_root)

    manifest, manifest_ref, candidate_id = seal_configured_sources(
        graph_config,
        store,
        extractor_generation="eg1:test",
        canonicalizer_generation="kg1:test",
    )

    authority = new_direct_authority(
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
    )
    job_id = str(authority.job_id or authority.operation_id)
    attempt = authority.attempt

    ws = tmp_path / "ws"
    ws.mkdir(mode=0o700, exist_ok=True)
    capability = PortableExecutionCapability(
        schema_version=1,
        job_id=job_id,
        attempt=attempt,
        graph_id="test-graph",
        store_root=store_root,
        workspace_root=ws,
        manifest_reference=manifest_ref,
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=10 * 1024 * 1024,
        max_bundle_bytes=10 * 1024 * 1024,
    )

    result = execute_portable_extraction(
        capability,
        emit_progress=lambda *_: None,
        cancel_event=threading.Event(),
    )
    assert result.receipt.outcome == "completed"
    assert result.candidate_id == candidate_id

    result_path = tmp_path / "result.json"
    _write_retained_result(
        result_path,
        manifest.manifest_id,
        (result.receipt_reference, result.bundle_reference),
    )

    stage_id = str(stage_id_for_authority(authority))
    capture = PortableCapture(
        graph=graph_config,
        store=store,
        manifest=manifest,
        candidate_id=candidate_id,
        authority=authority,
        result_path=result_path,
        workspace_root=ws,
        receipt_reference=result.receipt_reference,
        bundle_reference=result.bundle_reference,
    )
    receipt, validated = validate_portable_capture(capture, stage_id=stage_id)
    binding = portable_publication_binding(capture, receipt, validated, stage_id=stage_id)
    capture.mark_terminal(accepted=True)

    assert binding.candidate_id == candidate_id
    assert binding.publication_bundle_id == validated.bundle_id
    assert binding.snapshot_manifest_id == manifest.manifest_id
    assert binding.stage_id == stage_id


def test_publish_portable_seed_graph_mocks_db_publication(tmp_path: Path) -> None:
    mock_postgres = MagicMock()
    mock_postgres.psql_args = ["-h", "127.0.0.1", "-p", "5432", "-U", "test", "-d", "test"]
    mock_postgres.psql_command = "psql"

    fake_record = MagicMock(spec=RunPublicationRecord)
    fake_record.run_id = GraphRunId(42)
    fake_record.receipt = MagicMock()
    fake_record.receipt.public_mapping.return_value = {"run_id": 42}

    with (
        patch("repomap_test_support.semantic_seed_publication.run_staged_portable_refresh") as mock_refresh,
        patch("repomap_test_support.semantic_seed_publication.read_latest_publication", return_value=fake_record),
    ):
        ctx = publish_portable_seed_graph(
            mock_postgres,
            tmp_path,
            graph_id="unit-seed-graph",
            repository_name="unit-seed-repo",
            revision=1,
        )

    assert mock_refresh.called
    prepared = mock_refresh.call_args.kwargs["prepared_override"]
    evidence = {row["evidence_key"]: row["metadata_json"]
                for row in prepared.family_rows["canonical_evidence"]}
    scopes = {(link["canonical_key"], evidence[link["evidence_key"]]["binding_id"])
              for link in prepared.family_rows["canonical_node_evidence"]}
    assert {(SEED_KEY, ctx.binding_a_id), (SEED_KEY, ctx.binding_b_id),
            ("file:src_a/src/worker_a.py", ctx.binding_a_id),
            ("file:src_b/src/worker_b.py", ctx.binding_b_id),
            ("file:src_b/src/service_b.py", ctx.binding_b_id)} <= scopes
    prepared.close()
    assert ctx.graph_id == "unit-seed-graph"
    assert ctx.repository_identity == "repo1:unit-seed-graph"
    assert len(ctx.snapshots) == 2


def test_write_seed_mcp_config_loads_with_supported_ops_parser(tmp_path: Path) -> None:
    mock_postgres = MagicMock()
    mock_postgres.host = "127.0.0.1"
    mock_postgres.port = 5432
    mock_postgres.database = "repomap_test"
    mock_postgres.user = "repo_map_test"

    source_a, source_b = build_seed_sources(tmp_path)
    graph_config, b_a_id, b_b_id = build_seed_graph_config(
        "unit-seed-graph", "unit-seed-repo", source_a, source_b
    )

    fake_publication = MagicMock()
    context = SeedPublicationContext(
        graph_id="unit-seed-graph",
        repository_name="unit-seed-repo",
        repository_identity="repo1:unit-seed-graph",
        publication=fake_publication,
        graph_config=graph_config,
        binding_a_id=b_a_id,
        binding_b_id=b_b_id,
        snapshots={b_a_id: "snap-a", b_b_id: "snap-b"},
        source_a=source_a,
        source_b=source_b,
        store_root=tmp_path / "store",
    )

    config_path = tmp_path / "mcp-test.local.toml"
    written = write_seed_mcp_config(config_path, mock_postgres, context)
    assert written == config_path
    assert config_path.is_file()

    # Load through the supported operations TOML config parser
    loaded = load_ops_config(config_path)
    error_diags = [d for d in loaded.diagnostics if d.severity == "error"]
    assert not error_diags, f"unexpected error diagnostics: {error_diags}"

    # Verify graph identity and root bindings match publication
    assert len(loaded.graphs) == 1
    graph = loaded.graphs[0]
    assert graph.id == "unit-seed-graph"
    assert str(configured_repository_identity(graph.id)) == context.repository_identity
    assert configured_graph_root_path(graph) == f"graph:{context.graph_id}"
    assert len(graph.effective_source_bindings) == 2
    assert graph.effective_source_bindings[0].binding_id == context.binding_a_id
    assert graph.effective_source_bindings[1].binding_id == context.binding_b_id

    # Verify resolution topology resolves without collision
    resolved = resolve_ops_config(loaded)
    assert len(resolved.graphs) == 1
    assert resolved.graphs[0].repository_identity == context.repository_identity
    assert loaded.server_memory.enabled is False
    assert loaded.service.mode == "local"
    assert loaded.service.mcp_transport == "stdio"


@pytest.mark.parametrize("reader_role", [None, "unit_reader"])
def test_mcp_child_environment_and_real_module_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader_role: str | None,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(("untrusted-a", "untrusted-b")))
    monkeypatch.setenv("PGOPTIONS", "-c application_name=unit")
    monkeypatch.setenv("PGPASSWORD", "inert-auth-marker")
    parent_env = os.environ.copy()
    config = tmp_path / "public-test.toml"
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as launch:
        assert run_mcp_stdio_requests(config, "inert-psql", [], reader_role=reader_role, timeout=9) == []
    launch.assert_called_once()
    assert launch.call_args.args[0] == [sys.executable, "-m", "repomap_kg.server.mcp"]
    kwargs = launch.call_args.kwargs
    env = kwargs["env"]
    root = Path(repomap_kg.__file__).resolve().parent.parent
    assert env["PYTHONPATH"] == str(root)
    assert env["REPOMAP_OPS_CONFIG"] == str(config)
    assert env["REPOMAP_PSQL_COMMAND"] == "inert-psql"
    assert env["PGPASSWORD"] == "inert-auth-marker"
    assert env["PGOPTIONS"] == (f"-c role={reader_role}" if reader_role else parent_env["PGOPTIONS"])
    assert env["PYTHONUNBUFFERED"] == env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert kwargs["timeout"] == 9 and kwargs["check"] is False
    assert kwargs["capture_output"] is True and kwargs["text"] is True and kwargs["input"] == ""
    assert not {key for key in os.environ.keys() | parent_env.keys()
                if os.environ.get(key) != parent_env.get(key)}
    # -S excludes any host installation; find_spec does not execute the MCP module.
    lookup = "import importlib.util; spec = importlib.util.find_spec('repomap_kg.server.mcp'); "
    lookup += f"assert spec is not None and spec.origin == {str(root / 'repomap_kg/server/mcp.py')!r}"
    command = [sys.executable, "-S", "-c", lookup]
    isolated = dict(env)
    isolated.pop("PYTHONPATH")
    failed = subprocess.run(command, env=isolated, capture_output=True, text=True, timeout=9)
    assert failed.returncode == 1 and "ModuleNotFoundError: No module named 'repomap_kg'" in failed.stderr
    assert "inert-auth-marker" not in failed.stdout + failed.stderr
    resolved = subprocess.run(command, env=env, capture_output=True, text=True, timeout=9)
    assert resolved.returncode == 0 and resolved.stdout == resolved.stderr == ""


def _inert_mcp_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str | None,
) -> None:
    root = tmp_path / "import-root"
    server = root / "repomap_kg" / "server"
    server.mkdir(parents=True)
    (server.parent / "__init__.py").write_text("", encoding="utf-8")
    (server / "__init__.py").write_text("", encoding="utf-8")
    if source is not None:
        (server / "mcp.py").write_text(source, encoding="utf-8")
    alias = tmp_path / "import-alias"
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(repomap_kg, "__file__", str(alias / "repomap_kg" / "__init__.py"))
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)


def test_mcp_real_stdio_preserves_requests_ids_and_response_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inert_mcp_module(tmp_path, monkeypatch, """import json, os, sys
requests = [json.loads(line) for line in sys.stdin]
checks = [os.environ['PGOPTIONS'] == '-c role=unit_reader',
          os.environ['REPOMAP_PSQL_COMMAND'] == 'inert-psql',
          os.environ['REPOMAP_OPS_CONFIG'].endswith('public-test.toml'),
          os.environ['PYTHONPATH'] == os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
          os.environ['PGPASSWORD'] == 'inert-auth-marker',
          os.environ['PYTHONUNBUFFERED'] == os.environ['PYTHONDONTWRITEBYTECODE'] == '1']
for request in reversed(requests):
    if 'id' in request:
        response = {'jsonrpc': '2.0', 'id': request['id'],
                    'result': {'request': request, 'checks': checks}}
        if request['id'] == 7:
            response = {'jsonrpc': '2.0', 'id': 7,
                        'error': {'code': -32602, 'message': 'public error', 'data': request}}
        print('  ' + json.dumps(response))
        print()
""")
    monkeypatch.setenv("PYTHONPATH", "untrusted-host-root")
    monkeypatch.setenv("PGPASSWORD", "inert-auth-marker")
    requests: list[dict[str, object]] = [{"jsonrpc": "2.0", "id": "public-id", "method": "tools/call",
                 "params": {"name": "public-tool", "arguments": {"value": "unicode-λ"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}]
    with patch("subprocess.run", wraps=subprocess.run) as launch:
        responses = run_mcp_stdio_requests(tmp_path / "public-test.toml", "inert-psql", requests,
                                           reader_role="unit_reader", timeout=9)
    launch.assert_called_once()
    assert launch.call_args.kwargs["input"] == "".join(json.dumps(r) + "\n" for r in requests)
    assert responses == [{"jsonrpc": "2.0", "id": 7,
                          "error": {"code": -32602, "message": "public error", "data": requests[2]}},
                         {"jsonrpc": "2.0", "id": "public-id",
                          "result": {"request": requests[0], "checks": [True] * 6}}]
    assert "inert-auth-marker" not in json.dumps(responses)


@pytest.mark.parametrize(("source", "error", "message", "timeout"), [
    ("import sys; sys.stderr.write('inert failure'); sys.exit(7)", RuntimeError, "code 7: inert failure", 9),
    (None, RuntimeError, "code 1:.*No module named repomap_kg.server.mcp", 9),
    ("import time; time.sleep(30)", subprocess.TimeoutExpired, "timed out", 0.2),
])
def test_mcp_real_child_failures_do_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str | None,
    error: type[Exception], message: str, timeout: float,
) -> None:
    _inert_mcp_module(tmp_path, monkeypatch, source)
    monkeypatch.setenv("PGPASSWORD", "inert-auth-marker")
    with patch("subprocess.run", wraps=subprocess.run) as launch:
        with pytest.raises(error, match=message) as raised:
            run_mcp_stdio_requests(tmp_path / "public-test.toml", "inert-psql", [], timeout=timeout)
    assert "inert-auth-marker" not in str(raised.value)
    launch.assert_called_once()


def test_mcp_launch_failure_does_not_retry(tmp_path: Path) -> None:
    failure = OSError("inert launch failure")
    with patch("subprocess.run", side_effect=failure) as launch:
        with pytest.raises(OSError, match="inert launch failure") as raised:
            run_mcp_stdio_requests(tmp_path / "public-test.toml", "inert-psql", [])
    assert raised.value is failure
    launch.assert_called_once()
