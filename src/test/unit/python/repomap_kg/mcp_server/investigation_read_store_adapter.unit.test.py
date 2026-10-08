"""PostgreSQL investigation read-store adapter authority and host-only policy."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.ops.readback import OpsJsonReadbackMode
from repomap_kg.server.investigation_read_store import (
    GraphRefreshStatusQuery,
    InvestigationStorageQueries,
    LanguageSummaryQueries,
    PostgresInvestigationReadStore,
)
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.host_read_store_config import (
    NO_FALLBACK_GUARDS,
    fail_if_reached,
    patched_guards,
    setup_owned_config,
    setup_owned_home,
)
from repomap_test_support.mcp_server import McpServerTestSupport

MISSING_DB = 'psql failed: FATAL: database "repomap_x" does not exist'
UNRESOLVED = 'could not translate host name "postgres" to address'
SEVEN_TOOL_CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("repomap_graph_status", {"graph_id": "host-one"}),
    ("repomap_refresh_status", {"graph_id": "host-multi"}),
    ("repomap_refresh_status", {}),
    ("repomap_search_nodes", {"graph_id": "host-one", "query": "a"}),
    ("repomap_search_files", {"graph_id": "host-multi", "query": "a"}),
    ("repomap_search_observations", {"graph_id": "host-one", "query": "a", "include_raw": True}),
    ("repomap_project_summary", {"graph_id": "host-one"}),
    ("repomap_neighborhood", {"graph_id": "host-multi", "node": "python.module:a"}),
)


class _Recorder:
    """Record host JSON readbacks and answer with minimal valid payloads."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def __call__(self, sql: str, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        label = kwargs["label"]
        if label == "operations postgres status":
            return {"connected": True, "schema_available": True}
        if label == "operations refresh status":
            return {"graphs": []}
        if label == "canonical storage summary":
            return {"root_path": "/public/host-one", "repository_name": "host-one", "latest_run_id": 1,
                    "runs": 1, "files": 1, "raw_observations": 1, "canonical_nodes": 1,
                    "canonical_edges": 0, "canonical_evidence": 0}
        if label == "canonical neighborhood":
            raise StorageSchemaError("fixture has no neighborhood")
        return []


class InvestigationReadStoreAuthorityTests(McpServerTestSupport):
    def _env(self, **env: str):
        return patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()), **env}, clear=True)

    def _run_seven(self, **env: str) -> tuple[list[Any], list[str]]:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        outcomes: list[Any] = []
        refusals: list[str] = []
        with self._env(**env):
            for name, args in SEVEN_TOOL_CALLS:
                try:
                    outcomes.append(handle_tool_call(name, dict(args))["structuredContent"])
                except RepoMapMcpError as error:
                    refusals.append(str(error))
                    outcomes.append(str(error))
        return outcomes, refusals

    def test_setup_owned_home_reads_every_operation_as_read_status_role(self) -> None:
        from repomap_kg.runtime.database_role_contract import read_read_status_password

        home = setup_owned_home(self)
        ambient = {"PGPASSWORD": "ambient-admin", "REPOMAP_PG_PASSWORD": "ambient-admin"}
        recorder = _Recorder()
        with patch("repomap_kg.storage.readback_driver.execute_json_readback_with_driver", recorder), \
                patch("repomap_kg.ops.readback.execute_json_readback_with_driver", recorder), \
                patch.dict("os.environ", {"REPOMAP_HOME": str(home), **ambient}, clear=True):
            before = dict(os.environ)
            outcomes, _ = self._run_seven(REPOMAP_HOME=str(home), **ambient)
            self.assertEqual(dict(os.environ), before)
        labels = [call["label"] for call in recorder.calls]
        self.assertIn("nodes MCP search", labels)
        self.assertIn("canonical storage summary", labels)
        self.assertIn("canonical neighborhood", labels)
        self.assertIn("operations refresh status", labels)
        for call in recorder.calls:
            args = list(call["psql_args"])
            self.assertEqual(args[:6], ["-h", "127.0.0.1", "-p", "55439", "-U", "repomap_read_status"])
            self.assertIn(args[-1], ("repomap_host_one", "repomap_host_multi"))
            self.assertEqual(call["password"], read_read_status_password(home))
        self.assertEqual(outcomes[6]["summary"]["counts"]["files"], 1)
        self.assertEqual(outcomes[7], "fixture has no neighborhood")

    def test_custom_config_and_compose_projection_keep_declared_credentials(self) -> None:
        home = setup_owned_home(self)
        credential = home / "reader.secret"
        credential.write_text("custom-secret\n", encoding="utf-8")
        credential.chmod(0o600)
        custom = home / "custom.toml"
        custom.write_text(setup_owned_config().replace(
            'user = "repomap"\npassword_env = "REPOMAP_PG_PASSWORD"',
            f'user = "custom_reader"\npassword_file = "{credential}"',
        ), encoding="utf-8")
        compose = self.write_ops_config(setup_owned_config())
        cases = (
            ({"REPOMAP_OPS_CONFIG": str(custom)}, "custom_reader", "custom-secret"),
            ({"REPOMAP_OPS_CONFIG": str(home / "repomap.rpl.toml"), "REPOMAP_PG_PASSWORD": "operator-secret"},
             "repomap", "operator-secret"),
            ({"REPOMAP_OPS_CONFIG": str(compose), "REPOMAP_READ_STATUS_PASSWORD": "compose-read-secret"},
             "repomap_read_status", "compose-read-secret"),
        )
        for env, user, password in cases:
            recorder = _Recorder()
            with self.subTest(user=user), \
                    patch("repomap_kg.storage.readback_driver.execute_json_readback_with_driver", recorder), \
                    patch("repomap_kg.ops.readback.execute_json_readback_with_driver", recorder):
                self._run_seven(**env)
            self.assertTrue(recorder.calls)
            for call in recorder.calls:
                args = list(call["psql_args"])
                self.assertEqual(args[args.index("-U") + 1], user)
                self.assertEqual(call["password"], password)

    def test_host_failures_are_bounded_without_container_fallback_or_lifecycle(self) -> None:
        home = setup_owned_home(self, setup_owned_config().replace(
            "direct_host_port_enabled = true", "direct_host_port_enabled = false"
        ))
        for error, expected in ((StorageSchemaError(UNRESOLVED), UNRESOLVED), (OSError("psql missing"), "psql missing")):
            recorder = _Recorder(error)
            with self.subTest(error=type(error).__name__), patched_guards(), \
                    patch("repomap_kg.storage.readback_driver.execute_json_readback_with_driver", recorder), \
                    patch("repomap_kg.ops.readback.execute_json_readback_with_driver", recorder):
                outcomes, refusals = self._run_seven(
                    REPOMAP_HOME=str(home), REPOMAP_STORAGE_READBACK_DRIVER="psql",
                )
            self.assertEqual(refusals, [expected] * 5)
            statuses = (outcomes[0]["storage"], *outcomes[1]["graphs"], *outcomes[2]["graphs"])
            self.assertEqual(len(statuses), 4)
            for status in statuses:
                self.assertEqual(status["error"], expected)
                self.assertFalse(status["repository_exists"])
            self.assertNotIn("docker", str(outcomes))
            self.assertNotIn("Postgres container", str(outcomes))
            self.assertTrue(recorder.calls)

    def test_no_fallback_guard_detects_the_incumbent_container_route(self) -> None:
        # Canary: the same guards fire for the retained CLI default mode, so the
        # host-only assertions above would detect a reintroduced fallback.
        from repomap_kg.ops.readback import execute_ops_json_readback
        from repomap_kg.server._ops_records import load_mcp_ops_config

        home = setup_owned_home(self, setup_owned_config().replace(
            "direct_host_port_enabled = true", "direct_host_port_enabled = false"
        ))
        recorder = _Recorder(StorageSchemaError(UNRESOLVED))
        with self._env(REPOMAP_HOME=str(home), REPOMAP_STORAGE_READBACK_DRIVER="psql"), \
                patch("repomap_kg.ops.readback.execute_json_readback_with_driver", recorder):
            config = load_mcp_ops_config()
            assert isinstance(config, OpsConfig), "a PostgreSQL home loads OpsConfig"
            modes: tuple[tuple[OpsJsonReadbackMode, type[BaseException]], ...] = (
                ("host_only", StorageSchemaError), ("host_then_container", AssertionError))
            for mode, expected in modes:
                with self.subTest(mode=mode), patched_guards(), self.assertRaises(expected):
                    execute_ops_json_readback(config, database="repomap_host_one", sql="select 1",
                                              label="canary", expected_shape="object", mode=mode)

    def test_list_graphs_is_configuration_only(self) -> None:
        from repomap_kg.server.mcp import handle_tool_call

        guards = (*NO_FALLBACK_GUARDS, "repomap_kg.server.ops.investigation_stores",
                  "repomap_kg.server.mcp.graph_stores",
                  "repomap_kg.server.ops.execute_ops_json_readback", "repomap_kg.server.ops.query_refresh_status",
                  "repomap_kg.ops.readback.readback_postgres_authority",
                  "repomap_kg.server.canonical_read_store.readback_postgres_authority",
                  "repomap_kg.storage.readback_driver.execute_json_readback_with_driver",
                  "repomap_kg.storage.readback_driver.run_psql")
        home = setup_owned_home(self)
        with self._env(REPOMAP_HOME=str(home)), patched_guards(guards):
            payload = handle_tool_call("repomap_list_graphs", {})["structuredContent"]
        self.assertEqual([graph["graph_id"] for graph in payload["graphs"]], ["host-one", "host-multi"])
        self.assertFalse(any(graph["root_path_checked"] for graph in payload["graphs"]))
        self.assertFalse(Path("/public/host-one").exists())

    def test_seam_import_boundary_and_pure_construction(self) -> None:
        import repomap_kg.server.investigation_read_store as module
        from repomap_kg.server.ops import investigation_stores, load_mcp_ops_config

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        forbidden = ("subprocess", "shutil", "psycopg", "repomap_kg.runtime", "repomap_kg.ops.refresh",
                     "repomap_kg.ops._refresh", "repomap_kg.ops.readback", "repomap_kg.storage.staged_ingestion",
                     "repomap_kg.ops.direct_publication", "repomap_kg.graph.multi_source_pipeline",
                     "repomap_kg.coordinator", "repomap_kg.server.ops", "repomap_kg.server.mcp")
        self.assertFalse({name for name in imported if name and name.startswith(forbidden)})
        with self._env(REPOMAP_OPS_CONFIG=str(self.write_visible_ops_config())):
            config = load_mcp_ops_config()
            assert isinstance(config, OpsConfig), "a PostgreSQL home loads OpsConfig"
        with patched_guards(("repomap_kg.server.canonical_read_store.readback_postgres_authority",
                             "repomap_kg.ops.readback.readback_postgres_authority", *NO_FALLBACK_GUARDS)):
            store: Any = investigation_stores(config).investigation_store()
            PostgresInvestigationReadStore(config, None, InvestigationStorageQueries(
                refresh_status=fail_if_reached, search=fail_if_reached,
                storage_summary=fail_if_reached, neighborhood=fail_if_reached,
                language_summaries=LanguageSummaryQueries(*(fail_if_reached,) * 5),
            ))
        self.assertIs(store.config, config)


class PsqlDriverRefusalTextContrastTests(McpServerTestSupport):
    """Advisory A: the non-default password-bearing psql driver sanitizes text."""

    def _refusal(self, tool: str, args: dict[str, Any], env: dict[str, str], run_psql=None, psycopg=None) -> str:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        env = {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
               "REPOMAP_OPS_CONFIG": str(self.write_visible_ops_config()), **env}
        with patch.dict("os.environ", env, clear=True), patched_guards(), \
                patch("repomap_kg.storage.readback_driver.run_psql", run_psql or fail_if_reached), \
                patch("repomap_kg.storage.readback_driver._import_psycopg", psycopg or fail_if_reached), \
                self.assertRaises(RepoMapMcpError) as raised:
            handle_tool_call(tool, {"graph_id": "repo-map", **args})
        return str(raised.exception)

    def test_psql_driver_password_changes_missing_database_text(self) -> None:
        def missing(*_args, **_kwargs):
            raise StorageSchemaError(MISSING_DB)

        psql = {"REPOMAP_STORAGE_READBACK_DRIVER": "psql"}
        password = {"REPOMAP_PG_PASSWORD": "synthetic-secret"}
        for tool, args, label in (("repomap_search_files", {"query": "a"}, "files MCP search"),
                                  ("repomap_project_summary", {}, "canonical storage summary")):
            with self.subTest(tool=tool):
                self.assertIn("missing or not initialized", self._refusal(tool, args, psql, missing))
                self.assertEqual(self._refusal(tool, args, {**psql, **password}, missing),
                                 f"psql readback failed for {label}")

    def test_psycopg_default_keeps_missing_database_mapping_for_search(self) -> None:
        class OperationalError(Exception):
            sqlstate = "3D000"

        OperationalError.__module__ = "psycopg.errors"

        class FakePsycopg:
            @staticmethod
            def connect(**_kwargs):
                raise OperationalError("database does not exist")

        message = self._refusal("repomap_search_files", {"query": "a"},
                                {"REPOMAP_PG_PASSWORD": "synthetic-secret"}, psycopg=lambda: FakePsycopg)
        self.assertIn("missing or not initialized", message)
        self.assertNotIn("synthetic-secret", message)

    def test_seam_queries_do_not_read_hidden_graph_ids(self) -> None:
        from repomap_kg.ops.config import load_ops_config

        calls: list[dict[str, Any]] = []

        def refresh_status(*_args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {}

        config = load_ops_config(self.write_visible_ops_config())
        store = PostgresInvestigationReadStore(config, None, InvestigationStorageQueries(
            refresh_status=refresh_status, search=fail_if_reached,
            storage_summary=fail_if_reached, neighborhood=fail_if_reached,
            language_summaries=LanguageSummaryQueries(*(fail_if_reached,) * 5),
        ))
        store.refresh_statuses(GraphRefreshStatusQuery(("repo-map", "private-visible")))
        self.assertNotIn("hidden", calls[0]["graph_ids"])
        self.assertNotIn("disabled", calls[0]["graph_ids"])
        self.assertEqual(calls[0]["readback_mode"], "host_only")
