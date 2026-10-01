"""RESOLVE1: the PostgreSQL binding is the only production store factory.

The facades bind configured graphs through ``ops.investigation_stores`` and
``mcp.graph_stores``, both PostgreSQL. These tests pin that the binding keeps
the PostgreSQL context, database naming and client command the incumbent path
used, and that every tripwire category used by the neutral fake-store proof
really fires on the production path (canaries).
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.server.canonical_read_store import (
    ConfiguredPostgresConnection,
    PostgresCanonicalReadStore,
)
from repomap_kg.server.graph_selection import select_graph
from repomap_kg.server.investigation_read_store import PostgresInvestigationReadStore
from repomap_kg.server.postgres_read_binding import PostgresGraphStores, PostgresInvestigationStores
from repomap_kg.server.source_read_store import PostgresSourceReadStore
from repomap_test_support.host_read_store_config import (
    INVALID_PSQL_COMMAND,
    NO_FALLBACK_GUARDS,
    PG_BINDING_TRIPWIRES,
    patched_guards,
)
from repomap_test_support.mcp_server import McpServerTestSupport

PSQL = "/opt/pg/bin/psql"
FAMILY_TOOLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("repomap_project_summary", {"graph_id": "repo-map"}),
    ("repomap_search_files", {"graph_id": "repo-map", "query": "a"}),
    ("repomap_canonical_nodes", {"project": "repo-map"}),
    ("repomap_source_runs", {"project": "repo-map", "source_id": "feed"}),
)
CONTEXT_TRIPWIRES = ("repomap_kg.server._ops_records.McpOpsGraphContext.__init__",)
DATABASE_TRIPWIRES = tuple(target for target in PG_BINDING_TRIPWIRES if target.endswith(".graph_database"))
AUTHORITY_TRIPWIRES = tuple(target for target in PG_BINDING_TRIPWIRES if "readback_postgres_authority" in target)
SECRET_TRIPWIRES = tuple(target for target in PG_BINDING_TRIPWIRES if "_password" in target)
DRIVER_TRIPWIRES = tuple(target for target in PG_BINDING_TRIPWIRES if "readback_driver" in target
                         or target.endswith("execute_json_readback_with_driver"))


class PostgresBindingPreservationTests(McpServerTestSupport):
    def _env(self, **env: str) -> Any:
        return patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
                                         "REPOMAP_OPS_CONFIG": str(self.write_visible_ops_config()), **env},
                          clear=True)

    def test_investigation_binding_keeps_database_command_and_second_resolution(self) -> None:
        from repomap_kg.ops.config import graph_database
        from repomap_kg.server._ops_records import graph_context
        from repomap_kg.server.ops import investigation_stores, load_mcp_ops_config

        with self._env(REPOMAP_PSQL_COMMAND=PSQL):
            config = load_mcp_ops_config()
            assert isinstance(config, OpsConfig), "a PostgreSQL home loads OpsConfig"
            binding: Any = investigation_stores(config)
            contexts = {graph_id: graph_context(graph_id) for graph_id in ("repo-map", "private-visible")}
        self.assertIsInstance(binding, PostgresInvestigationStores)
        self.assertEqual((binding.config, binding.psql_command), (config, PSQL))
        store = binding.investigation_store()
        self.assertIsInstance(store, PostgresInvestigationReadStore)
        self.assertEqual((store.config, store.psql_command, store.queries), (config, PSQL, binding.queries))
        for graph_id, context in contexts.items():
            selection = select_graph(config, graph_id)
            with self.subTest(graph_id=graph_id):
                self.assertEqual(binding.storage_label(selection), graph_database(config, selection.graph))
                self.assertEqual(binding.storage_label(selection), context.database)
                # The adapter re-resolves by graph id; it must reach the same context.
                self.assertEqual(store._context(graph_id), context)

    def test_graph_binding_builds_the_incumbent_context_and_facade_owners(self) -> None:
        from repomap_kg.server._ops_records import graph_context
        from repomap_kg.server.mcp import graph_stores, storage_connection

        with self._env(REPOMAP_PSQL_COMMAND=PSQL), \
                patch("repomap_kg.server.mcp.query_canonical_node_records") as nodes_owner, \
                patch("repomap_kg.server.mcp.query_source_run_records") as runs_owner:
            target: Any = storage_connection(project="repo-map")
            context = graph_context("repo-map")
            canonical = target.stores.canonical_store(target.selection)
            source = target.stores.source_store(target.selection)
            direct: Any = graph_stores(context.config)
        self.assertIsInstance(target.stores, PostgresGraphStores)
        self.assertIsInstance(direct, PostgresGraphStores)
        self.assertIsInstance(canonical, PostgresCanonicalReadStore)
        self.assertIsInstance(source, PostgresSourceReadStore)
        for store in (canonical, source):
            self.assertIsInstance(store.connection, ConfiguredPostgresConnection)
            self.assertEqual(store.connection.context, context)
            self.assertEqual(store.connection.context.psql_command, PSQL)
            self.assertEqual(store.connection.context.database, "repomap_repo_map")
        self.assertIs(canonical.queries.nodes, nodes_owner)
        self.assertIs(source.queries.runs, runs_owner)

    def test_client_command_refusal_keeps_its_text_and_position(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        for tool, args in FAMILY_TOOLS:
            with self.subTest(tool=tool), self._env(REPOMAP_PSQL_COMMAND=INVALID_PSQL_COMMAND), \
                    patched_guards(NO_FALLBACK_GUARDS), self.assertRaises(RepoMapMcpError) as raised:
                handle_tool_call(tool, dict(args))
            self.assertEqual(str(raised.exception), "psql command must not contain whitespace")
        # Selection refusals still come first, before the command is read.
        with self._env(REPOMAP_PSQL_COMMAND=INVALID_PSQL_COMMAND), self.assertRaises(RepoMapMcpError) as raised:
            handle_tool_call("repomap_canonical_nodes", {"project": "hidden"})
        self.assertEqual(str(raised.exception), "graph 'hidden' is not MCP-visible")


class PostgresBindingTripwireCanaryTests(McpServerTestSupport):
    """Each tripwire category fires on the real PostgreSQL path (no fakes)."""

    def _run(self, label: str, tripwires: tuple[str, ...], tool: str, args: dict[str, Any]) -> None:
        from repomap_kg.server.mcp import handle_tool_call
        from repomap_kg.server.ops import load_mcp_ops_config

        ops_path = self.write_visible_ops_config()
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(ops_path)}, clear=True):
            config = load_mcp_ops_config()
            assert isinstance(config, OpsConfig), "a PostgreSQL home loads OpsConfig"
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
                                                      "REPOMAP_PG_PASSWORD": "synthetic"}, clear=True))
        stack.enter_context(patch("repomap_kg.server.ops.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patch("repomap_kg.server.mcp_core.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patched_guards(NO_FALLBACK_GUARDS))

        def tripped(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(f"tripwire {label}")

        for target in tripwires:
            stack.enter_context(patch(target, tripped))
        # The named category, not a generic guard, must be what stops the read.
        with stack, self.assertRaisesRegex(AssertionError, f"^tripwire {label}$"):
            handle_tool_call(tool, dict(args))

    def test_every_tripwire_category_fires_without_injected_fakes(self) -> None:
        psql = ("repomap_kg.server._ops_records.psql_command_from_environment",
                "repomap_kg.server.postgres_read_binding.psql_command_from_environment")
        categories: tuple[tuple[str, tuple[str, ...], tuple[int, ...]], ...] = (
            ("client command", psql, (0, 1, 2, 3)),
            ("postgres context", CONTEXT_TRIPWIRES, (0, 1, 2, 3)),
            ("database naming", DATABASE_TRIPWIRES, (0, 1, 2, 3)),
            ("readback authority", AUTHORITY_TRIPWIRES, (0, 1, 2, 3)),
            ("secret reader", SECRET_TRIPWIRES, (0, 1, 2, 3)),
            ("json driver", DRIVER_TRIPWIRES, (1,)),
        )
        for label, tripwires, tool_indexes in categories:
            self.assertTrue(tripwires, label)
            for index in tool_indexes:
                tool, args = FAMILY_TOOLS[index]
                with self.subTest(category=label, tool=tool):
                    self._run(label, tripwires, tool, args)
