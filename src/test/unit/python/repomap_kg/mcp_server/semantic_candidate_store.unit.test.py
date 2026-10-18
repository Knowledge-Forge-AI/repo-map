"""The optional investigation-store surface preserves graph and Local scope."""

from dataclasses import replace
from unittest.mock import patch

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.config_local import LocalSqliteConfig
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.server.investigation_read_store import (
    InvestigationStorageQueries, LanguageSummaryQueries, PostgresInvestigationReadStore,
)
from repomap_kg.storage.semantic_candidates import unavailable
from repomap_kg.storage.semantic_seed import SimilarNodesQuery
from repomap_test_support.semantic_candidate_fixtures import PROFILE
from repomap_kg.server.sqlite_read_binding import SqliteInvestigationReadStore
from repomap_test_support.host_read_store_config import fail_if_reached, patched_guards
from repomap_test_support.mcp_server import McpServerTestSupport
from repomap_test_support.semantic_candidate_fixtures import candidate_query


class SemanticCandidateStoreTests(McpServerTestSupport):
    def _seed(self, *, selected: bool = True) -> SimilarNodesQuery:
        return SimilarNodesQuery("file:src/a.py", "fixture-rebuild", PROFILE.identity,
            PROFILE.dimensions, selected=selected)

    def test_seed_read_dispatch_uses_configured_graph_scope(self) -> None:
        store = self._store()
        query = self._seed()
        with patch("repomap_kg.server.investigation_read_store.read_configured_graph", return_value=unavailable("extension_absent")) as read:
            self.assertEqual(store.similar_nodes("repo-map", query).reason, "extension_absent")
        self.assertIs(read.call_args.kwargs["query"], query)
        self.assertEqual(read.call_args.args[0].repository_identity, str(configured_repository_identity("repo-map")))

    def test_seed_disabled_private_and_hidden_graphs_do_no_io(self) -> None:
        store = self._store()
        with patched_guards(), patch("repomap_kg.server.investigation_read_store.read_configured_graph", fail_if_reached):
            self.assertEqual(store.similar_nodes("repo-map", self._seed(selected=False)).reason, "disabled")
            self.assertEqual(store.similar_nodes("private-visible", self._seed()).reason, "private_graph_unsupported")
            for graph_id in ("hidden", "disabled", "unknown"):
                with self.subTest(graph_id=graph_id), self.assertRaises(ValueError):
                    store.similar_nodes(graph_id, self._seed())

    def test_seed_local_refusal_does_not_open_database(self) -> None:
        config = self._store().config
        local = LocalSqliteConfig(
            config.config_path, config.config_home, config.config_files, config.schema_version,
            config.service, config.graphs, config.server_memory, config.sources,
        )
        with patched_guards(), patch("repomap_kg.server.sqlite_read_binding.read_transaction", fail_if_reached):
            store = SqliteInvestigationReadStore(local)
            self.assertEqual(store.similar_nodes("repo-map", self._seed()).reason, "sqlite_unsupported")
            self.assertEqual(store.similar_nodes("repo-map", self._seed(selected=False)).reason, "disabled")

    def _store(self) -> PostgresInvestigationReadStore:
        config = load_ops_config(self.write_visible_ops_config())
        queries = InvestigationStorageQueries(
            fail_if_reached, fail_if_reached, fail_if_reached, fail_if_reached,
            LanguageSummaryQueries(*(fail_if_reached for _ in range(5))),
        )
        return PostgresInvestigationReadStore(config, "psql", queries)

    def _query(self, graph_id: str = "repo-map"):
        query = candidate_query()
        return replace(query, publication=replace(query.publication,
            repository_identity=str(configured_repository_identity(graph_id))))

    def test_default_selection_has_no_read_authority_or_io(self) -> None:
        store = self._store()
        with patched_guards(), patch("repomap_kg.server.investigation_read_store.read_configured_graph", fail_if_reached):
            result = store.semantic_candidates("repo-map", replace(self._query(), selected=False))
        self.assertEqual(result.reason, "disabled")

    def test_public_query_reaches_existing_read_owner_with_exact_scope(self) -> None:
        store = self._store()
        query = self._query()
        with patch("repomap_kg.server.investigation_read_store.read_configured_graph", return_value=unavailable("extension_absent")) as read:
            result = store.semantic_candidates("repo-map", query)
        self.assertEqual(result.reason, "extension_absent")
        self.assertIs(read.call_args.kwargs["query"], query)
        self.assertEqual(read.call_args.args[0].repository_identity, query.publication.repository_identity)

    def test_foreign_graph_and_private_graph_are_refused_before_io(self) -> None:
        store = self._store()
        with patched_guards(), patch("repomap_kg.server.investigation_read_store.read_configured_graph", fail_if_reached):
            self.assertEqual(store.semantic_candidates("repo-map", candidate_query()).reason, "graph_scope_mismatch")
            self.assertEqual(store.semantic_candidates("private-visible", self._query("private-visible")).reason, "private_graph_unsupported")

    def test_visibility_checks_precede_optional_database_query(self) -> None:
        store = self._store()
        with patched_guards():
            for graph_id in ("hidden", "disabled", "unknown"):
                with self.subTest(graph_id=graph_id), self.assertRaises(ValueError):
                    store.semantic_candidates(graph_id, self._query())

    def test_local_capability_refusal_needs_no_sqlite_or_postgres_io(self) -> None:
        config = self._store().config
        local = LocalSqliteConfig(
            config.config_path, config.config_home, config.config_files, config.schema_version,
            config.service, config.graphs, config.server_memory, config.sources,
        )
        store = SqliteInvestigationReadStore(local)
        with patched_guards(), patch("repomap_kg.server.sqlite_read_binding.read_transaction", fail_if_reached):
            self.assertEqual(store.semantic_candidates("repo-map", self._query()).reason, "sqlite_unsupported")
            self.assertEqual(store.semantic_candidates("repo-map", replace(self._query(), selected=False)).reason, "disabled")
