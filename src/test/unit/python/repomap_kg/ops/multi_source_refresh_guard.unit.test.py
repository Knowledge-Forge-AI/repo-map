from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch

from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from repomap_kg.coordinator._refresh_generation import GenerationClaim

from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator._refresh_generation import validate_configured_generations
from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.graph import multi_source_pipeline
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.generations import source_generation
from repomap_kg.ops.refresh import preflight_graph, refresh_enabled_graphs, refresh_graph
from repomap_kg.ops.reports import refresh_result_to_jsonable
from repomap_kg.server.ops import graph_context


def _config_text(first_root: Path, second_root: Path) -> str:
    def binding(alias: str, root: Path) -> str:
        return f"""
[[graphs.source_bindings]]
schema_version = 1
binding_id = "{graph_source_binding_id('fixture-graph', alias)}"
source_definition_id = "src1:{alias}"
alias = "{alias}"
revision = 1
kind = "folder"
root_path = "{root}"
repository_name = "fixture-{alias}"
logical_root = "."
privacy = "public-dev"
evidence_retention = "inherit"
extractor_profile = "default"
resolution_policy = "isolated"
"""

    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap_fixture"
user = "fixture"
password_file = "fixture-password"

[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
enabled = true
mcp_visible = true
refresh_policy = "manual"
{binding('root', first_root)}
{binding('security', second_root)}

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _config(tmp_path: Path):
    first = tmp_path / "private-first"
    second = tmp_path / "private-second"
    first.mkdir()
    second.mkdir()
    (first / "flake.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (second / "flake.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    path = tmp_path / "repomap.toml"
    password = tmp_path / "fixture-password"
    password.write_text("public-test-placeholder\n", encoding="utf-8")
    password.chmod(0o600)
    path.write_text(_config_text(first, second), encoding="utf-8")
    path.chmod(0o600)
    return path, load_ops_config(path)


def _request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "fixture-graph",
        "request_id": "fixture-request",
        "idempotency_key": "fixture-key",
        "priority": "manual",
        "operation_options": {"reason": "fixture"},
    }


def test_direct_refresh_captures_all_bindings_before_one_database_call(tmp_path):
    _, config = _config(tmp_path)
    with (
        patch("repomap_kg.ops.refresh.discover_observations") as discover,
        patch(
            "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
            return_value=SimpleNamespace(repository_id=1, run_id=2, files=2),
        ) as publish,
    ):
        result = refresh_graph(config, "fixture-graph")
    discover.assert_not_called()
    publish.assert_called_once()
    assert result.result == "success"
    bundle = publish.call_args.args[1]
    raw_obs = bundle.families["raw_observations"]
    assert {
        item["payload_json"]["metadata"]["binding_alias"]
        for item in raw_obs
        if item.get("kind") == "file"
    } == {
        "root",
        "security",
    }


def test_preflight_and_refresh_enabled_use_complete_public_safe_capture(tmp_path):
    _, config = _config(tmp_path)
    preflight = preflight_graph(config, "fixture-graph")
    assert preflight.result == "success"
    assert preflight.files_included == 2
    assert preflight.root_path_display == "[multi-source]"

    with patch(
        "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
        return_value=SimpleNamespace(repository_id=1, run_id=2, files=2),
    ):
        result = refresh_enabled_graphs(config)[0]
    assert result.result == "success"
    assert "private-first" not in str(result.to_jsonable())
    payload = refresh_result_to_jsonable(config, (result,), command="refresh")
    assert payload["graphs"][0]["root_path_display"] == ""
    assert payload["graphs"][0]["repository_name"] == "[multi-source]"
    assert "private-first" not in str(payload)
    assert "private-second" not in str(payload)
    assert payload["config_path"] == config.config_path


def test_coordinator_resolution_uses_complete_candidate_generation(tmp_path):
    path, _ = _config(tmp_path)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    resolver = ConfiguredRefreshResolver(path, psql)
    with patch("repomap_kg.coordinator.configured_refresh._source_token") as source:
        request = resolver.resolve_request(_request())
    source.assert_not_called()
    assert request.source_generation.startswith("sg1:")
    assert request.config_generation.startswith("cg1:")


def test_coordinator_generation_scan_does_not_capture_semantics(tmp_path):
    path, _ = _config(tmp_path)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    resolver = ConfiguredRefreshResolver(path, psql)
    with patch(
        "repomap_kg.graph.multi_source_pipeline.capture_multi_source_candidate",
        side_effect=AssertionError("coordinator performed semantic capture"),
    ) as capture:
        request = resolver.resolve_request(_request())
    capture.assert_not_called()
    assert request.source_generation.startswith("sg1:")
    assert request.config_generation.startswith("cg1:")


def test_worker_generation_validation_accepts_same_complete_candidate(tmp_path):
    path, config = _config(tmp_path)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    request = ConfiguredRefreshResolver(path, psql).resolve_request(_request())
    validate_configured_generations(config, cast("GenerationClaim", request))


def test_worker_generation_validation_does_not_capture_semantics(tmp_path):
    path, config = _config(tmp_path)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    request = ConfiguredRefreshResolver(path, psql).resolve_request(_request())
    with patch(
        "repomap_kg.graph.multi_source_pipeline.capture_multi_source_candidate",
        side_effect=AssertionError("worker performed semantic capture"),
    ) as capture:
        validate_configured_generations(config, cast("GenerationClaim", request))
    capture.assert_not_called()


def test_multi_source_scan_generation_matches_full_capture_inventory(tmp_path):
    path, config = _config(tmp_path)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    request = ConfiguredRefreshResolver(path, psql).resolve_request(_request())
    bundle = capture_multi_source_candidate(config.graphs[0])

    assert request.source_generation == source_generation(bundle.observations)


@pytest.mark.parametrize(
    ("field", "value"),
    (("role", "analysis"), ("input_name", "analysis_input")),
)
def test_multi_source_config_generation_binds_role_and_input_name(
    tmp_path, field, value
):
    path, _ = _config(tmp_path)
    original = path.read_text(encoding="utf-8")
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    baseline = ConfiguredRefreshResolver(path, psql).resolve_request(_request())

    path.write_text(
        original.replace(
            'alias = "root"\n',
            f'alias = "root"\n{field} = "{value}"\n',
            1,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    changed = ConfiguredRefreshResolver(path, psql).resolve_request(_request())

    assert changed.config_generation != baseline.config_generation


def test_multi_source_config_generation_ignores_physical_runtime_context(tmp_path):
    path, _ = _config(tmp_path)
    original = path.read_text(encoding="utf-8")
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    baseline = ConfiguredRefreshResolver(path, psql).resolve_request(_request())

    relocated_first = tmp_path / "relocated-first"
    relocated_second = tmp_path / "relocated-second"
    shutil.copytree(tmp_path / "private-first", relocated_first)
    shutil.copytree(tmp_path / "private-second", relocated_second)
    relocated_config = tmp_path / "relocated.toml"
    relocated_config.write_text(
        original
        .replace(str(tmp_path / "private-first"), str(relocated_first))
        .replace(str(tmp_path / "private-second"), str(relocated_second))
        .replace('database = "repomap_fixture"', 'database = "relocated_fixture"'),
        encoding="utf-8",
    )
    relocated_config.chmod(0o600)
    relocated_psql = tmp_path / "relocated-psql"
    relocated_psql.write_text("fixture", encoding="utf-8")
    relocated_psql.chmod(0o700)
    relocated = ConfiguredRefreshResolver(relocated_config, relocated_psql).resolve_request(
        _request()
    )

    assert relocated.source_generation == baseline.source_generation
    assert relocated.config_generation == baseline.config_generation


def test_multi_source_fence_binds_snapshot_resolver_and_semantic_identities(tmp_path):
    _, config = _config(tmp_path)
    graph = config.graphs[0]
    baseline = multi_source_pipeline.scan_multi_source_generations(graph)

    (tmp_path / "private-first" / "flake.nix").write_text(
        "{ changed = true; }: {}\n", encoding="utf-8"
    )
    snapshot_changed = multi_source_pipeline.scan_multi_source_generations(graph)
    assert snapshot_changed.source_generation != baseline.source_generation
    assert snapshot_changed.config_generation == baseline.config_generation

    with patch.object(
        multi_source_pipeline,
        "_MULTI_SOURCE_RESOLVER_VERSION",
        "nix-static-v2-fixture",
    ):
        resolver_changed = multi_source_pipeline.scan_multi_source_generations(graph)
    with patch.object(
        multi_source_pipeline,
        "_MULTI_SOURCE_SEMANTIC_IDENTITY",
        "semantic1:multi-source-fixture",
    ):
        semantic_changed = multi_source_pipeline.scan_multi_source_generations(graph)
    assert resolver_changed.config_generation != baseline.config_generation
    assert semantic_changed.config_generation != baseline.config_generation
    assert resolver_changed.source_generation == snapshot_changed.source_generation
    assert semantic_changed.source_generation == snapshot_changed.source_generation


def test_direct_multi_source_receipt_authority_uses_bound_bundle_generations(tmp_path):
    _, config = _config(tmp_path)
    expected = capture_multi_source_candidate(config.graphs[0])
    with patch(
        "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
        return_value=SimpleNamespace(repository_id=1, run_id=2, files=2),
    ) as publish:
        result = refresh_graph(config, "fixture-graph")

    assert result.result == "success"
    authority = publish.call_args.kwargs["authority"]
    assert authority.source_generation == expected.source_generation
    assert authority.config_generation == expected.config_generation


def test_multi_source_capture_source_unavailable_has_typed_classification(tmp_path):
    _, config = _config(tmp_path)
    shutil.rmtree(tmp_path / "private-second")

    with pytest.raises(ValueError) as raised:
        capture_multi_source_candidate(config.graphs[0])

    assert getattr(raised.value, "category", None) == "source_unavailable"
    assert str(raised.value) == "source unavailable"


def test_multi_source_capture_failure_has_typed_classification(tmp_path):
    _, config = _config(tmp_path)
    with patch(
        "repomap_kg.graph.multi_source_pipeline.discover_repository",
        side_effect=OSError("synthetic unreadable source"),
    ):
        with pytest.raises(ValueError) as raised:
            capture_multi_source_candidate(config.graphs[0])

    assert getattr(raised.value, "category", None) == "source_capture"
    assert str(raised.value) == "source capture failed"


def test_multi_source_readback_is_admitted_for_supported_bindings(tmp_path):
    _, config = _config(tmp_path)
    graph = config.graphs[0]
    assert graph.refresh_unsupported_classification is None
    assert graph.readback_unsupported_classification is None
    assert graph.repository_name_display == "[multi-source]"


def test_mcp_graph_context_admits_supported_multi_binding_readback(tmp_path):
    _, config = _config(tmp_path)
    with (
        patch("repomap_kg.server.ops.load_mcp_ops_config", return_value=config),
        patch("repomap_kg.server._ops_records.load_mcp_ops_config", return_value=config),
    ):
        context = graph_context("fixture-graph")
    assert context.graph.id == "fixture-graph"


@pytest.mark.parametrize("policy", ("polling", "continuous"))
def test_polling_snapshot_and_polling_graphs_refuse_explicit_multi_source(
    tmp_path, policy
):
    path, _ = _config(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'refresh_policy = "manual"', f'refresh_policy = "{policy}"'
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    psql = tmp_path / "psql"
    psql.write_text("fixture", encoding="utf-8")
    psql.chmod(0o700)
    resolver = ConfiguredRefreshResolver(path, psql)
    assert resolver.polling_graphs() == ()
    with pytest.raises(ValueError, match="multi-source graph polling refresh is unsupported"):
        resolver.polling_snapshot("fixture-graph")


def test_multi_source_empty_graph_root_never_reads_process_cwd(tmp_path, monkeypatch):
    path, config = _config(tmp_path)
    cwd = tmp_path / "process-cwd"
    cwd.mkdir()
    (cwd / "flake.nix").write_text("{ cwd = true; }: {}\n", encoding="utf-8")
    monkeypatch.chdir(cwd)

    bundle = capture_multi_source_candidate(config.graphs[0])

    assert {item.path for item in bundle.observations if item.kind == "file"} == {
        "root/flake.nix",
        "security/flake.nix",
    }
