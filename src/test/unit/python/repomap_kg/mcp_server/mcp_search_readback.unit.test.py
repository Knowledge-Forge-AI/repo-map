from __future__ import annotations

import subprocess
from typing import Any, Callable
from unittest.mock import patch

import repomap_kg.graph.multi_source_pipeline as multi_source_pipeline
import repomap_kg.ops.direct_publication as direct_publication
import repomap_kg.ops.refresh as ops_refresh
from repomap_kg.ops.config import load_ops_config
from repomap_kg.server.ops import (
    build_mcp_search_sql,
    query_mcp_search,
)
from repomap_kg.storage import StorageSchemaError

from repomap_test_support.host_read_store_config import patched_guards, setup_owned_home
from repomap_test_support.mcp_server import McpServerTestSupport

ROWS = [{"path": "src/main.py"}, {"path": "src/other.py"}]
# Lifecycle, source-traversal and container attempts that NO_FALLBACK_GUARDS
# must intercept if any configured-search binding ever made them.
# Attributes are looked up at call time, so the patched guards are what run;
# the untyped module handles let a synthetic argument stand in for real inputs.
_refresh: Any = ops_refresh
_capture: Any = multi_source_pipeline
_publication: Any = direct_publication
SIDE_EFFECT_ATTEMPTS: tuple[tuple[str, Callable[[], Any]], ...] = (
    ("refresh", lambda: _refresh.refresh_graph("synthetic")),
    ("source capture", lambda: _capture.capture_multi_source_candidate("synthetic")),
    ("publication", lambda: _publication.publish_observation_generation("synthetic")),
    ("container exec", lambda: subprocess.run(["docker", "exec", "synthetic"], check=False)),
)


class _DriverRecorder:
    """Answer the host JSON driver with fixed rows, recording its arguments."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, sql: str, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return list(ROWS)


class McpSearchReadbackUnitTests(McpServerTestSupport):
    def test_psycopg108_query_uses_exact_operational_array_adapter(self):
        config_path = self.write_ops_config(self.visible_ops_config())
        config = load_ops_config(config_path)
        rows = [{"path": "one"}, {"path": "two"}]

        with patch(
            "repomap_kg.server.ops.execute_ops_json_readback",
            return_value=rows,
            create=True,
        ) as execute:
            payload = query_mcp_search(
                config,
                database="repomap_repo_map",
                root_path="/tmp/fixture",
                target="files",
                query="path",
                limit=1,
                offset=5,
                psql_command="/usr/local/bin/psql",
            )

        self.assertEqual(payload["results"], [{"path": "one"}])
        self.assertEqual(payload["total"], 6)
        self.assertTrue(payload["has_more"])
        execute.assert_called_once_with(
            config,
            database="repomap_repo_map",
            sql=build_mcp_search_sql(
                root_path="/tmp/fixture",
                target="files",
                query="path",
                kind=None,
                path=None,
                limit=1,
                offset=5,
                include_raw=False,
            ),
            label="files MCP search",
            expected_shape="array",
            mode="host_only",
            psql_command="/usr/local/bin/psql",
        )

    def test_psycopg108_search_payload_reaches_the_bound_search_owner(self):
        from repomap_kg.server.mcp import repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value={
                    "results": [{"path": "src/main.py"}],
                    "total": 1,
                    "has_more": False,
                },
            ) as query,
        ):
            payload = repomap_search_files(graph_id="repo-map", query="main")

        self.assertEqual(payload["results"], [{"path": "src/main.py"}])
        self.assertEqual(query.call_args.args[0].config_path, str(config_path))
        self.assertEqual(query.call_args.kwargs["database"], "repomap_repo_map")
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertIsNone(query.call_args.kwargs["psql_command"])

    def test_psycopg108_validation_precedes_search_database_access(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.query_mcp_search",
                side_effect=AssertionError("database accessed"),
            ) as query,
        ):
            with self.assertRaises(RepoMapMcpError):
                repomap_search_files(graph_id="missing", query="main")
            with self.assertRaises(RepoMapMcpError):
                repomap_search_files(graph_id="repo-map", query=" ")

        query.assert_not_called()

    def test_psycopg108_adapter_failure_remains_public_mcp_error(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.execute_ops_json_readback",
                side_effect=StorageSchemaError("bounded search failure"),
                create=True,
            ),
        ):
            with self.assertRaisesRegex(RepoMapMcpError, "bounded search failure"):
                repomap_search_files(graph_id="repo-map", query="main")

    def test_psycopg108_query_uses_the_operational_readback_owner(self):
        import inspect

        from repomap_kg.server import ops

        query_source = inspect.getsource(ops.query_mcp_search)
        self.assertIn("execute_ops_json_readback", query_source)
        self.assertNotIn("run_psql", query_source)
        self.assertNotIn("parse_psql_json", query_source)


class McpSearchSideEffectGuardTests(McpServerTestSupport):
    """RESOLVE1 advisory B: guard the real factory-to-driver search boundary."""

    def _env(self, home: Any):
        return patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
                                         "REPOMAP_HOME": str(home)}, clear=True)

    def test_configured_search_reads_host_only_through_real_binding_without_side_effects(self):
        from repomap_kg.runtime.database_role_contract import read_read_status_password
        from repomap_kg.server.mcp import repomap_search_files

        home = setup_owned_home(self)
        recorder = _DriverRecorder()
        with self._env(home), patched_guards(), \
                patch("repomap_kg.ops.readback.execute_json_readback_with_driver", recorder):
            payload = repomap_search_files(graph_id="host-one", query="main", limit=1)

        self.assertEqual(payload["results"], ROWS[:1])
        self.assertTrue(payload["has_more"])
        self.assertEqual(len(recorder.calls), 1)
        call = recorder.calls[0]
        self.assertEqual(call["label"], "files MCP search")
        self.assertEqual(list(call["psql_args"]), ["-h", "127.0.0.1", "-p", "55439", "-U", "repomap_read_status",
                                                   "-d", "repomap_host_one"])
        self.assertEqual(call["password"], read_read_status_password(home))

    def test_guard_canary_detects_a_binding_that_attempts_a_side_effect(self):
        # Synthetic canary: a store bound through the real factory seam tries
        # one lifecycle/source/container action; the same guards must fire and
        # the refusal must escape the tool rather than become a read result.
        from repomap_kg.server.mcp import repomap_search_files

        home = setup_owned_home(self)
        for label, attempt in SIDE_EFFECT_ATTEMPTS:

            class _SideEffectStore:
                def search(self, _query: Any, _attempt: Callable[[], Any] = attempt) -> Any:
                    return _attempt()

            class _Binding:
                def storage_label(self, _selection: Any) -> str:
                    return "synthetic"

                def investigation_store(self) -> Any:
                    return _SideEffectStore()

            with self.subTest(attempt=label), self._env(home), patched_guards(), \
                    patch("repomap_kg.server.ops.investigation_stores", lambda _config: _Binding()), \
                    self.assertRaisesRegex(AssertionError, "container, or subprocess path"):
                repomap_search_files(graph_id="host-one", query="main")
