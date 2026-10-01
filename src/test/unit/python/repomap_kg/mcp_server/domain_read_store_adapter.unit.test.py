"""READSTORE3 adapter authority, host-only policy and error-text contrasts.

All twelve newly migrated tools (five language summaries, six ingested-source
reads, legacy status) are exercised against a setup-owned home with the JSON
readback driver replaced by a recorder, so no database is started.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.storage import StorageSchemaError
from repomap_test_support.host_read_store_config import (
    NO_FALLBACK_GUARDS,
    fail_if_reached,
    patched_guards,
    setup_owned_config,
    setup_owned_home,
)
from repomap_test_support.mcp_server import McpServerTestSupport

ITEM_KEY = "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
MISSING_DB = 'psql failed: FATAL: database "repomap_x" does not exist'
UNRESOLVED = 'could not translate host name "postgres" to address'
TWELVE_TOOL_CALLS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("repomap_python_summary", {"graph_id": "host-one"}, "python summary"),
    ("repomap_terraform_summary", {"graph_id": "host-multi"}, "terraform summary"),
    ("repomap_openapi_summary", {"graph_id": "host-one"}, "openapi summary"),
    ("repomap_js_framework_summary", {"graph_id": "host-multi"}, "js framework summary"),
    ("repomap_nix_summary", {"graph_id": "host-one"}, "nix summary"),
    ("repomap_ingested_sources", {"project": "host-one"}, "ingested source records"),
    ("repomap_source_summary", {"project": "host-multi", "source_id": "feed"}, "source summary"),
    ("repomap_source_runs", {"project": "host-one", "source_id": "feed"}, "source run records"),
    ("repomap_source_feed_items", {"project": "host-one", "source_id": "feed"}, "source feed item records"),
    ("repomap_explain_source_feed_item", {"project": "host-multi", "item_key": ITEM_KEY},
     "source feed item explanation"),
    ("repomap_source_references", {"project": "host-one", "source_id": "feed"}, "source reference records"),
    ("repomap_status", {"project": "host-multi"}, "canonical storage summary"),
)
RECORDED = "recorded readback"


class _Recorder:
    """Record host JSON readbacks, then refuse so no payload shape is needed."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error or StorageSchemaError(RECORDED)

    def __call__(self, sql: str, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise self.error


def _patched_driver(recorder: _Recorder):
    return patch("repomap_kg.storage.readback_driver.execute_json_readback_with_driver", recorder)


class DomainReadStoreAuthorityTests(McpServerTestSupport):
    def _env(self, **env: str):
        return patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()), **env}, clear=True)

    def _run_twelve(self, **env: str) -> list[str]:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        refusals: list[str] = []
        with self._env(**env):
            for name, args, _label in TWELVE_TOOL_CALLS:
                with self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call(name, dict(args))
                refusals.append(str(raised.exception))
        return refusals

    def test_setup_owned_home_reads_all_twelve_as_read_status_role(self) -> None:
        from repomap_kg.runtime.database_role_contract import read_read_status_password

        home = setup_owned_home(self)
        ambient = {"PGPASSWORD": "ambient-admin", "REPOMAP_PG_PASSWORD": "ambient-admin"}
        recorder = _Recorder()
        with _patched_driver(recorder), patched_guards(), \
                patch.dict("os.environ", {"REPOMAP_HOME": str(home), **ambient}, clear=True):
            before = dict(os.environ)
            refusals = self._run_twelve(REPOMAP_HOME=str(home), **ambient)
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(refusals, [RECORDED] * 12)
        self.assertEqual([call["label"] for call in recorder.calls], [label for _n, _a, label in TWELVE_TOOL_CALLS])
        for call, (_name, args, _label) in zip(recorder.calls, TWELVE_TOOL_CALLS):
            graph = args.get("graph_id", args.get("project"))
            args_list = list(call["psql_args"])
            self.assertEqual(args_list, ["-h", "127.0.0.1", "-p", "55439", "-U", "repomap_read_status",
                                         "-d", f"repomap_{str(graph).replace('-', '_')}"])
            self.assertEqual(call["password"], read_read_status_password(home))

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
            with self.subTest(user=user), _patched_driver(recorder):
                self._run_twelve(**env)
            self.assertEqual(len(recorder.calls), 12)
            for call in recorder.calls:
                args = list(call["psql_args"])
                self.assertEqual(args[args.index("-U") + 1], user)
                self.assertEqual(call["password"], password)

    def test_legacy_json_project_keeps_ambient_authority_without_readback_resolution(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        legacy = self.write_mcp_config({"projects": {"legacy": {
            "root_path": "/workspace/legacy", "pg_database": "legacy_db", "pg_host": "db.internal",
            "pg_port": "6543", "pg_user": "reader"}}})
        recorder = _Recorder()
        source_and_status = [(name, {**args, "project": "legacy"}) for name, args, _label in TWELVE_TOOL_CALLS[5:]]
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(legacy), "PGPASSWORD": "ambient"}, clear=True), \
                _patched_driver(recorder), \
                patch("repomap_kg.server.canonical_read_store.readback_postgres_authority", fail_if_reached):
            for name, args in source_and_status:
                with self.assertRaises(RepoMapMcpError):
                    handle_tool_call(name, args)
        self.assertEqual(len(recorder.calls), 7)
        for call in recorder.calls:
            self.assertEqual(list(call["psql_args"]), ["-h", "db.internal", "-p", "6543", "-U", "reader",
                                                       "-d", "legacy_db"])
            self.assertIsNone(call["password"])

    def test_host_failures_are_bounded_without_container_fallback_or_lifecycle(self) -> None:
        home = setup_owned_home(self, setup_owned_config().replace(
            "direct_host_port_enabled = true", "direct_host_port_enabled = false"
        ))
        for error, expected in ((StorageSchemaError(UNRESOLVED), UNRESOLVED), (OSError("psql missing"), "psql missing")):
            recorder = _Recorder(error)
            with self.subTest(error=type(error).__name__), patched_guards(), _patched_driver(recorder):
                refusals = self._run_twelve(REPOMAP_HOME=str(home), REPOMAP_STORAGE_READBACK_DRIVER="psql")
            self.assertEqual(refusals, [expected] * 12)
            self.assertEqual(len(recorder.calls), 12)
            self.assertNotIn("docker", str(refusals))
            self.assertNotIn("Postgres container", str(refusals))

    def test_no_fallback_guard_detects_the_retained_fallback_reader(self) -> None:
        # Canary: the retained CLI ops-psql reader (ops.refresh, outside MCP)
        # still falls back to a container on the same home, and the same guards
        # fire there, so the host-only assertions above would detect a
        # reintroduced fallback.
        from repomap_kg.ops.refresh import run_storage_readback_with_ops_psql
        from repomap_kg.server._ops_records import graph_context
        from repomap_kg.storage import query_python_summary

        home = setup_owned_home(self, setup_owned_config().replace(
            "direct_host_port_enabled = true", "direct_host_port_enabled = false"
        ))
        recorder = _Recorder(StorageSchemaError(UNRESOLVED))
        with self._env(REPOMAP_HOME=str(home), REPOMAP_STORAGE_READBACK_DRIVER="psql"), \
                patch("repomap_kg.storage.readback_driver.run_psql", recorder), \
                patched_guards(), self.assertRaisesRegex(AssertionError, "container, or subprocess path"):
            context = graph_context("host-one")
            run_storage_readback_with_ops_psql(context.config, context.database, query_python_summary,
                                               psql_command=None, root_path=context.root_path)

    def test_configured_summary_privacy_redacts_private_roots(self) -> None:
        from repomap_kg.server.mcp import handle_tool_call

        private_root = str(Path.home() / "private-visible")

        class _PrivateSummary:
            def to_dict(self) -> dict[str, Any]:
                return {"root_path": private_root, "repository_name": "private-visible", "count": 1}

        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env, patch("repomap_kg.server.ops.query_python_summary", lambda *_a, **_k: _PrivateSummary()):
            payload = handle_tool_call("repomap_python_summary", {"graph_id": "private-visible"})["structuredContent"]
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(private_root, serialized)
        self.assertNotIn(Path.home().name, serialized)
        self.assertEqual(payload["summary"]["root_path"], "[private-root]")
        self.assertTrue(payload["graph"]["private"])

    def test_source_seam_import_boundary_and_pure_construction(self) -> None:
        import repomap_kg.server.source_read_store as module
        from repomap_kg.server.canonical_read_store import ConfiguredPostgresConnection
        from repomap_kg.server.mcp import source_read_store, storage_connection

        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertEqual({name for name in imported if name and name.startswith("repomap_kg")},
                         {"repomap_kg.server.canonical_read_store", "repomap_kg.storage.source_rows"})
        forbidden = ("subprocess", "shutil", "psycopg", "repomap_kg.runtime", "repomap_kg.ops",
                     "repomap_kg.storage.staged_ingestion", "repomap_kg.coordinator", "repomap_kg.server.ops",
                     "repomap_kg.server.mcp", "repomap_kg.ingestion")
        self.assertFalse({name for name in imported if name and name.startswith(forbidden)})
        with self._env(REPOMAP_OPS_CONFIG=str(self.write_visible_ops_config())):
            connection: Any = storage_connection(project="repo-map")
        with patched_guards(("repomap_kg.server.canonical_read_store.readback_postgres_authority",
                             "repomap_kg.storage.readback_driver.execute_json_readback_with_driver",
                             *NO_FALLBACK_GUARDS)):
            store: Any = source_read_store(connection)
        self.assertIsInstance(store.connection, ConfiguredPostgresConnection)
        self.assertIs(store.connection.context.graph, connection.selection.graph)
        self.assertEqual(store.connection.context.root_path, connection.root_path)


class DomainReadDriverRefusalTextContrastTests(McpServerTestSupport):
    """Configured reads use read_configured_graph: bounded generic driver text."""

    def _refusal(self, tool: str, args: dict[str, Any], env: dict[str, str], run_psql=None, psycopg=None) -> str:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        env = {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
               "REPOMAP_OPS_CONFIG": str(self.write_visible_ops_config()), **env}
        with patch.dict("os.environ", env, clear=True), patched_guards(), \
                patch("repomap_kg.storage.readback_driver.run_psql", run_psql or fail_if_reached), \
                patch("repomap_kg.storage.readback_driver._import_psycopg", psycopg or fail_if_reached), \
                self.assertRaises(RepoMapMcpError) as raised:
            handle_tool_call(tool, args)
        return str(raised.exception)

    def test_missing_database_text_is_operation_and_driver_specific(self) -> None:
        def missing(*_args, **_kwargs):
            raise StorageSchemaError(MISSING_DB)

        class OperationalError(Exception):
            sqlstate = "3D000"

        OperationalError.__module__ = "psycopg.errors"

        class FakePsycopg:
            @staticmethod
            def connect(**_kwargs):
                raise OperationalError("database does not exist")

        psql = {"REPOMAP_STORAGE_READBACK_DRIVER": "psql"}
        password = {"REPOMAP_PG_PASSWORD": "synthetic-secret"}
        for tool, args, label in (
            ("repomap_python_summary", {"graph_id": "repo-map"}, "python summary"),
            ("repomap_source_summary", {"project": "repo-map", "source_id": "feed"}, "source summary"),
            ("repomap_status", {"project": "repo-map"}, "canonical storage summary"),
        ):
            with self.subTest(tool=tool):
                self.assertIn("missing or not initialized", self._refusal(tool, args, psql, missing))
                self.assertEqual(self._refusal(tool, args, {**psql, **password}, missing),
                                 f"psql readback failed for {label}")
                message = self._refusal(tool, args, password, psycopg=lambda: FakePsycopg)
                self.assertEqual(message, f"psycopg readback failed for {label}")
                self.assertNotIn("synthetic-secret", message)
        # Contrast: configured search maps Psycopg SQLSTATE 3D000 (unchanged).
        search = self._refusal("repomap_search_files", {"graph_id": "repo-map", "query": "a"}, password,
                               psycopg=lambda: FakePsycopg)
        self.assertIn("missing or not initialized", search)
