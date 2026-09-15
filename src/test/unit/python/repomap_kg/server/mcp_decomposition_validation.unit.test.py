"""Focused negative, error, and boundary tests for server MCP decompositions."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from repomap_kg.server._mcp_core_validation import (
    RepoMapMcpError,
    validate_canonical_limit,
    validate_feed_item_key,
    validate_limit,
    validate_offset,
    validate_optional_text_filter,
    validate_psql_command,
    validate_read_schema_version,
    validate_source_id_arg,
)
from repomap_kg.server._mcp_dispatch import (
    handle_jsonrpc_message,
    handle_tool_call,
    jsonrpc_error,
    jsonrpc_result,
    tool_input_schema,
    validate_tool_call_arguments,
)
from repomap_kg.server._ops_search import (
    like_escape,
    validate_limit as validate_ops_limit,
    validate_offset as validate_ops_offset,
    validate_query as validate_ops_query,
)
from repomap_kg.server._server_memory_parsing import (
    validate_server_memory_limit,
    validate_server_memory_offset,
    validate_server_memory_query,
)
from repomap_kg.server.ops import McpOpsError


def test_core_validation_source_id_errors() -> None:
    with pytest.raises(RepoMapMcpError, match="source_id must not be a URL"):
        validate_source_id_arg("https://example.com/source")
    with pytest.raises(RepoMapMcpError, match="source_id must not contain whitespace"):
        validate_source_id_arg("source id with space")
    with pytest.raises(RepoMapMcpError, match="source_id is required"):
        validate_source_id_arg("")


def test_core_validation_feed_item_key_errors() -> None:
    with pytest.raises(RepoMapMcpError, match="item_key must use the feed.item namespace"):
        validate_feed_item_key("tool:my_tool")
    with pytest.raises(RepoMapMcpError, match="item_key is required"):
        validate_feed_item_key("")


def test_core_validation_limit_boundaries() -> None:
    assert validate_canonical_limit(1) == 1
    assert validate_canonical_limit(50) == 50
    assert validate_canonical_limit(200) == 200
    assert validate_canonical_limit(cast(int, "200")) == 200
    assert validate_canonical_limit(cast(int, True)) == 1
    for out_of_bounds in (0, 201, 500, 501, 999, -1):
        with pytest.raises(RepoMapMcpError, match="limit must be between 1 and 200"):
            validate_canonical_limit(out_of_bounds)
    for malformed in ("invalid", None, object()):
        with pytest.raises(RepoMapMcpError, match="limit must be a positive integer"):
            validate_canonical_limit(cast(int, malformed))

    assert validate_limit(1) == 1
    assert validate_limit(200) == 200
    assert validate_limit(500) == 500
    assert validate_limit(cast(int, "500")) == 500
    assert validate_limit(cast(int, True)) == 1
    for out_of_bounds in (0, 501, 999, -1):
        with pytest.raises(RepoMapMcpError, match="limit must be between 1 and 500"):
            validate_limit(out_of_bounds)
    for malformed in ("invalid", None, object()):
        with pytest.raises(RepoMapMcpError, match="limit must be a positive integer"):
            validate_limit(cast(int, malformed))


def test_core_validation_read_schema_version() -> None:
    assert validate_read_schema_version(0) == 0
    assert validate_read_schema_version(1) == 1
    with pytest.raises(RepoMapMcpError, match="schema version must be 0 or 1"):
        validate_read_schema_version(2)
    with pytest.raises(RepoMapMcpError, match="schema version must be 0 or 1"):
        validate_read_schema_version(cast(int, "invalid"))




def test_core_validation_offset_and_text_filter() -> None:
    assert validate_offset(0) == 0
    with pytest.raises(RepoMapMcpError, match="non-negative integer"):
        validate_offset(-1)
    with pytest.raises(RepoMapMcpError, match="must not be a URL"):
        validate_optional_text_filter("http://evil.com", "filter_label")


def test_core_validation_psql_command() -> None:
    validate_psql_command("psql")
    validate_psql_command("/usr/local/bin/psql")
    with pytest.raises(RepoMapMcpError, match="must not contain whitespace"):
        validate_psql_command("psql -h localhost")
    with pytest.raises(RepoMapMcpError, match="must name a psql executable"):
        validate_psql_command("pg_dump")


def test_mcp_dispatch_tool_errors() -> None:
    with pytest.raises(RepoMapMcpError, match="unknown RepoMap MCP tool: unknown_tool"):
        tool_input_schema("unknown_tool")

    with pytest.raises(RepoMapMcpError, match="unknown RepoMap MCP tool: fake_tool"):
        handle_tool_call("fake_tool", {})

    with pytest.raises(RepoMapMcpError, match="unexpected argument"):
        validate_tool_call_arguments(
            "repomap_status",
            {"nonexistent_arg": 123},
        )


def test_mcp_dispatch_jsonrpc_handling() -> None:
    assert handle_jsonrpc_message({"method": "notifications/initialized"}) is None
    init_res = handle_jsonrpc_message({"id": 1, "method": "initialize"})
    assert init_res is not None
    assert init_res["result"]["serverInfo"]["name"] == "repomap-kg"

    unknown_res = handle_jsonrpc_message({"id": 2, "method": "unknown_method"})
    assert unknown_res is not None
    assert "error" in unknown_res
    assert unknown_res["error"]["code"] == -32601

    res = jsonrpc_result("msg1", {"key": "val"})
    assert res == {"jsonrpc": "2.0", "id": "msg1", "result": {"key": "val"}}

    err = jsonrpc_error("msg2", -32600, "Invalid Request")
    assert err == {
        "jsonrpc": "2.0",
        "id": "msg2",
        "error": {"code": -32600, "message": "Invalid Request"},
    }


def test_ops_search_validation_boundaries() -> None:
    assert validate_ops_query("find something") == "find something"
    with pytest.raises(McpOpsError, match="query is required"):
        validate_ops_query("")
    with pytest.raises(McpOpsError, match="query is required"):
        validate_ops_query("   ")
    with pytest.raises(McpOpsError, match="at most 200 characters"):
        validate_ops_query("a" * 201)

    assert validate_ops_limit(50) == 50
    assert validate_ops_limit(200) == 100  # capped at MAX_SEARCH_LIMIT
    with pytest.raises(McpOpsError, match="positive integer"):
        validate_ops_limit(0)

    assert validate_ops_offset(10) == 10
    with pytest.raises(McpOpsError, match="non-negative integer"):
        validate_ops_offset(-1)

    assert like_escape("test%_") == r"test\%\_"


def test_server_memory_validation_boundaries() -> None:
    assert validate_server_memory_query("test query") == "test query"
    with pytest.raises(ValueError, match="query is required"):
        validate_server_memory_query("")
    with pytest.raises(ValueError, match="at most 500 characters"):
        validate_server_memory_query("x" * 501)

    assert validate_server_memory_limit(20) == 20
    assert validate_server_memory_limit(150) == 100  # capped at MAX_SERVER_MEMORY_LIMIT
    with pytest.raises(ValueError, match="positive integer"):
        validate_server_memory_limit(-5)

    assert validate_server_memory_offset(5) == 5
    with pytest.raises(ValueError, match="non-negative integer"):
        validate_server_memory_offset(-1)


def test_mcp_projects_decomposition() -> None:
    from repomap_kg.server._mcp_projects import (
        ProjectDependencies,
        graph_registry_projects_hint,
        repomap_projects,
    )

    # Test error handling fallback in graph_registry_projects_hint
    broken_deps = ProjectDependencies(
        load_mcp_ops_config=lambda *args: (_ for _ in ()).throw(OSError("missing")),
    )
    hint = graph_registry_projects_hint(dependencies=broken_deps)
    assert hint["graph_registry_available"] is False
    assert hint["graph_count"] == 0
    assert "legacy project config is active" in hint["message"]

    # Test repomap_projects with mock config
    from unittest.mock import MagicMock
    mock_config = MagicMock()
    mock_config.default_project = "demo"
    mock_config.allow_project_overrides = True
    mock_config.projects = {}
    mock_deps = ProjectDependencies(
        load_mcp_config=lambda: mock_config,
        load_mcp_ops_config=lambda *args: (_ for _ in ()).throw(ValueError("bad")),
    )
    payload = repomap_projects(dependencies=mock_deps)
    assert payload["default_project"] == "demo"
    assert payload["allow_project_overrides"] is True


def _server_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src/main/python/repomap_kg/server"
        if candidate.is_dir():
            return candidate
    raise AssertionError("server dir unavailable")


def test_server_modules_physical_lines_under_400() -> None:
    server_dir = _server_dir()
    for py_file in server_dir.glob("*.py"):
        line_count = len(py_file.read_text(encoding="utf-8").splitlines())
        assert line_count <= 400, f"Module {py_file.name} has {line_count} lines (> 400)"


def test_server_modules_have_zero_masked_backedges() -> None:
    import re
    server_dir = _server_dir()
    forbidden_pattern = re.compile(r"(_mcp_attr|_bridge_attr|_ops_attr|sys\.modules\.get)")
    for py_file in server_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        matches = forbidden_pattern.findall(content)
        assert not matches, f"Module {py_file.name} contains masked backedge patterns: {matches}"


def test_server_import_graph_is_strictly_acyclic() -> None:
    from src.test.unit.python.repomap_kg.architecture.import_graph_support import (
        _import_graph, _strongly_connected_components,
    )

    graph, _ = _import_graph()
    server_sccs = [
        sorted(component)
        for component in _strongly_connected_components(graph)
        if any("repomap_kg.server." in mod for mod in component)
    ]
    assert server_sccs == [], f"Server import graph contains cycles: {server_sccs}"

