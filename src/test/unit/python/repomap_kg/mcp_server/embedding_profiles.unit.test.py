"""MCP catalog, dispatch, configured privacy and no-I/O discovery refusals."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.config_local import LocalSqliteConfig
from repomap_kg.server._mcp_dispatch import TOOL_FUNCTIONS
from repomap_kg.server._mcp_similar import _profiles_need_redaction, embedding_profiles_payload
from repomap_kg.server.investigation_read_store import (
    InvestigationStorageQueries, LanguageSummaryQueries, PostgresInvestigationReadStore,
)
from repomap_kg.server.mcp import handle_jsonrpc_message, tool_definitions
from repomap_kg.server.sqlite_read_binding import SqliteInvestigationReadStore, SqliteInvestigationStores
from repomap_kg.storage.semantic_candidates import (
    EmbeddingProfilesQuery, EmbeddingProfilesResult, profiles_unavailable, validated_profile_entry,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_test_support.host_read_store_config import fail_if_reached, patched_guards
from repomap_test_support.mcp_server import McpServerTestSupport
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, SNAPSHOT, candidate_query


class EmbeddingProfilesMcpTests(McpServerTestSupport):
    def _call(self, arguments):
        response = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "repomap_embedding_profiles", "arguments": arguments}})
        assert response is not None
        return response["result"]

    def _store(self):
        config = load_ops_config(self.write_visible_ops_config())
        queries = InvestigationStorageQueries(fail_if_reached, fail_if_reached, fail_if_reached, fail_if_reached,
                                             LanguageSummaryQueries(*(fail_if_reached for _ in range(5))))
        return PostgresInvestigationReadStore(config, "psql", queries)

    def _local(self):
        config = self._store().config
        return LocalSqliteConfig(config.config_path, config.config_home, config.config_files,
                                config.schema_version, config.service, config.graphs,
                                config.server_memory, config.sources)

    def _env(self):
        return self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())

    def test_catalog_advertises_one_strict_bounded_read_operation(self):
        tools = tool_definitions()
        self.assertEqual(len(tools), 31)
        tool, = [item for item in tools if item["name"] == "repomap_embedding_profiles"]
        schema = tool["inputSchema"]
        self.assertEqual(schema["required"], ["graph_id"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"graph_id", "selected", "limit"})
        self.assertEqual(schema["properties"]["selected"], {"type": "boolean", "default": False})
        self.assertEqual(schema["properties"]["limit"]["maximum"], 100)
        self.assertEqual(TOOL_FUNCTIONS[tool["name"]], tool["name"])
        self.assert_tool_schema_omits_unsafe_arguments(schema)

    def test_disabled_mcp_never_calls_an_investigation_store(self):
        with self._env(), patched_guards(), patch(
            "repomap_kg.server.postgres_read_binding.PostgresInvestigationStores.investigation_store",
            fail_if_reached,
        ):
            result = self._call({"graph_id": "repo-map"})
        payload = result["structuredContent"]
        self.assertEqual(payload["reason"], "disabled")
        self.assert_read_only_payload(payload)
        self.assert_public_graph_payload(payload["graph"])

    def test_strict_input_and_negative_rpc_paths(self):
        arguments = [{}, {"graph_id": "repo-map", "vector": [1]},
                     {"graph_id": "repo-map", "selected": "true"},
                     {"graph_id": "repo-map", "selected": 1},
                     {"graph_id": "repo-map", "limit": True},
                     {"graph_id": "repo-map", "limit": 0},
                     {"graph_id": "repo-map", "limit": 101},
                     *({"graph_id": graph} for graph in ("unknown", "hidden", "disabled"))]
        with self._env(), patched_guards():
            for args in arguments:
                with self.subTest(args=args):
                    self.assertTrue(self._call(args)["isError"])

    def test_store_disabled_private_binding_hidden_and_local_refuse_without_io(self):
        store = self._store()
        public = next(graph for graph in store.config.graphs if graph.id == "repo-map")
        # A public graph cannot override a private source binding's policy.
        private_binding = replace(public.effective_source_bindings[0], privacy="private-ops")
        mixed_graph = replace(public, source_bindings=(private_binding,), explicit_source_bindings=True)
        mixed = replace(store, config=replace(store.config, graphs=(mixed_graph,)))
        query = EmbeddingProfilesQuery(selected=True)
        with patched_guards(), patch("repomap_kg.server.investigation_read_store.read_configured_graph", fail_if_reached):
            self.assertEqual(store.embedding_profiles("repo-map", EmbeddingProfilesQuery()).reason, "disabled")
            self.assertEqual(store.embedding_profiles("private-visible", query).reason, "private_graph_unsupported")
            self.assertEqual(mixed.embedding_profiles("repo-map", query).reason, "private_graph_unsupported")
            for graph_id in ("hidden", "disabled", "unknown"):
                with self.assertRaises(ValueError):
                    store.embedding_profiles(graph_id, query)
        with patched_guards(), patch("repomap_kg.server.sqlite_read_binding.read_transaction", fail_if_reached):
            local = SqliteInvestigationReadStore(self._local())
            self.assertEqual(local.embedding_profiles("repo-map", query).reason, "sqlite_unsupported")
            self.assertEqual(local.embedding_profiles("repo-map", EmbeddingProfilesQuery()).reason, "disabled")

    def test_public_adapter_binds_only_configured_repository_and_read_owner(self):
        store = self._store()
        query = EmbeddingProfilesQuery(selected=True)
        with patch("repomap_kg.server.investigation_read_store.read_configured_graph",
                   return_value=profiles_unavailable("extension_absent")) as read:
            self.assertEqual(store.embedding_profiles("repo-map", query).reason, "extension_absent")
        self.assertEqual(read.call_args.args[0].repository_identity, "repo1:repo-map")
        self.assertEqual(read.call_args.args[1].__name__, "query_embedding_profiles")
        self.assertIs(read.call_args.kwargs["query"], query)

    def test_local_rpc_remains_available_without_postgres(self):
        with self._env(), patch("repomap_kg.server.ops.investigation_stores",
                               return_value=SqliteInvestigationStores(self._local())), patched_guards():
            payload = self._call({"graph_id": "repo-map", "selected": True})["structuredContent"]
        self.assertEqual(payload["reason"], "sqlite_unsupported")
        self.assertEqual(payload["graph"]["database_source"], "sqlite-graph-file")

    def test_public_rpc_output_and_error_redaction(self):
        entry = {"rebuild_id": "fixture", "profile_identity": PROFILE.identity, **PROFILE.__dict__, "row_count": 5}
        result = EmbeddingProfilesResult("ok", profiles=(entry,))
        owner = "repomap_kg.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        with self._env(), patch(owner, return_value=result):
            response = self._call({"graph_id": "repo-map", "selected": True})
        self.assertEqual(response["structuredContent"]["profiles"][0]["profile_identity"], PROFILE.identity)
        self.assert_read_only_payload(response["structuredContent"])
        unsafe = replace(result, profiles=({**entry, "model": str(Path.home()) + "/model"},))
        with self._env(), patch(owner, return_value=unsafe):
            payload = self._call({"graph_id": "repo-map", "selected": True})["structuredContent"]
        self.assertEqual(payload["profiles"], [])
        self.assertEqual(payload["reason"], "privacy_refused")
        with self._env(), patch(owner, side_effect=StorageSchemaError("embedding profile query failed")):
            response = self._call({"graph_id": "repo-map", "selected": True})
        self.assertTrue(response["isError"])
        self.assertIn("embedding profile query failed", response["structuredContent"]["error"])

    def test_payload_facade_dispatch_is_reachable(self):
        with patched_guards():
            payload = embedding_profiles_payload("repo-map", config_path=self.write_visible_ops_config())
        self.assertEqual(payload["reason"], "disabled")

    def test_username_substrings_in_opaque_digests_do_not_refuse_public_profiles(self):
        entry = {"rebuild_id": "fixture", "profile_identity": PROFILE.identity, **PROFILE.__dict__, "row_count": 5}
        result = EmbeddingProfilesResult("ok", profiles=(entry,))
        owner = "repomap_kg.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        for username in ("a", PROFILE.identity[7:11]):
            with self.subTest(username=username), self._env(), patch(owner, return_value=result), patch(
                "pathlib.Path.home", return_value=Path("/private/fixture-home") / username,
            ):
                payload = self._call({"graph_id": "repo-map", "selected": True})["structuredContent"]
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["profiles"][0]["profile_identity"], PROFILE.identity)

    def test_private_username_in_model_metadata_refuses_the_whole_tuple(self):
        entry = {"rebuild_id": "fixture", "profile_identity": PROFILE.identity,
                 **PROFILE.__dict__, "model": "fixture-privateuser-model", "row_count": 5}
        owner = "repomap_kg.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        with self._env(), patch(owner, return_value=EmbeddingProfilesResult("ok", profiles=(entry,))), patch(
            "pathlib.Path.home", return_value=Path("/private/fixture-home/privateuser"),
        ):
            payload = self._call({"graph_id": "repo-map", "selected": True})["structuredContent"]
        self.assertEqual(payload["reason"], "privacy_refused")
        self.assertEqual(payload["profiles"], [])

    def test_digest_shaped_metadata_and_nested_provenance_refuse_whole_rpc_response(self):
        username = "privateuser"
        private_digest = username + ":" + "a" * 64
        public_entry = {"rebuild_id": "fixture", "profile_identity": PROFILE.identity,
                        **PROFILE.__dict__, "row_count": 5}
        cases = []
        for field, profile in (
            ("model", replace(PROFILE, model=private_digest)),
            ("generator", replace(PROFILE, generator=private_digest)),
            ("model_version", replace(PROFILE, model_version=private_digest)),
            ("generator_version", replace(PROFILE, generator_version=private_digest)),
        ):
            entry = {**public_entry, **profile.__dict__, "profile_identity": profile.identity}
            cases.append((field, EmbeddingProfilesResult("ok", profiles=(entry,))))
        for field in ("claim", "profile_identity", "representation_version", "privacy_class"):
            provenance = {"nested": [{field: private_digest}]}
            cases.append(("provenance-" + field, EmbeddingProfilesResult(
                "ok", profiles=(public_entry,), provenance=provenance)))
        owner = "repomap_kg.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        for label, result in cases:
            with self.subTest(case=label), self._env(), patch(owner, return_value=result), patch(
                "pathlib.Path.home", return_value=Path("/private/fixture-home") / username,
            ):
                self.assertTrue(_profiles_need_redaction(result.to_jsonable(), ()))
                response = self._call({"graph_id": "repo-map", "selected": True})
            payload = response["structuredContent"]
            self.assertEqual(payload["reason"], "privacy_refused")
            self.assertEqual(payload["profiles"], [])
            self.assertIsNone(payload["provenance"])

    def test_username_and_private_paths_are_checked_outside_opaque_identity_fields(self):
        digest = "a" * 64
        cases = (
            ("privateuser", {"profiles": [{"generator": "fixture-privateuser-model"}]}, ()),
            ("privateuser", {"provenance": {"nested": [{"claim": "privateuser"}]}}, ()),
            ("privateuser", {"profiles": [{"model": "/private/fixture-data/model"}]},
             ("/private/fixture-data",)),
            ("privateuser", {"provenance": {"nested": [{"claim": "/private/fixture-data/model"}]}},
             ("/private/fixture-data",)),
            ("privateuser", {"profiles": [{"profile_identity": "privateuser:" + digest}]}, ()),
            ("privateuser", {"profiles": [{"profile_identity": "sha256:privateuser"}]}, ()),
            ("privateuser", {"provenance": {"receipt_identity": "privateuser:" + digest}}, ()),
            ("sha256", {"profiles": [{"model": "sha256:" + digest}]}, ()),
            ("sha256", {"profiles": {"*": {"profile_identity": "sha256:" + digest}}}, ()),
            ("sha256", {"provenance": {"nested": [{"profile_identity": "sha256:" + digest}]}}, ()),
            ("sha256", {"provenance": {"receipt_identity": ["sha256:" + digest]}}, ()),
            ("privateuser", {"profiles": [{"metric": "privateuser"}]}, ()),
            ("privateuser", {"provenance": {"snapshot_contract": "privateuser"}}, ()),
            ("privateuser", {"provenance": {"nested": [{"privacy_class": "privateuser"}]}}, ()),
            ("bind1", {"provenance": {"nested": {"source_binding_id": "bind1:" + digest}}}, ()),
            ("sg1", {"provenance": {"nested": {"source_generation": "sg1:" + digest}}}, ()),
        )
        for username, payload, markers in cases:
            with self.subTest(username=username, payload=payload), patch(
                "pathlib.Path.home", return_value=Path("/private/fixture-home") / username,
            ):
                self.assertTrue(_profiles_need_redaction(payload, markers))

    def test_validated_opaque_profile_and_publication_identities_allow_username_collisions(self):
        publication = candidate_query().publication.validate()
        generations = replace(publication.publication.receipt.generations,
                              source_generation="sg1:" + "a" * 64, config_generation="cg1:" + "b" * 64,
                              extractor_generation="eg1:" + "c" * 64, canonicalizer_generation="kg1:" + "d" * 64)
        receipt = replace(publication.publication.receipt, generations=generations)
        publication = replace(publication, publication=replace(publication.publication, receipt=receipt)).validate()
        entry = validated_profile_entry({"rebuild_id": "fixture", "profile_identity": PROFILE.identity,
                 **PROFILE.__dict__, "row_count": 5,
                 "source_scope": [{"source_binding_id": BINDING, "snapshot_id": SNAPSHOT}]}, publication)
        provenance = {"receipt_identity": publication.receipt_identity,
                      "publication": publication.publication.receipt.public_mapping(),
                      "generations": dict(zip(generations.field_names(), generations.values(), strict=True)),
                      "privacy_class": "public", "pgvector_version": "0.8.7"}
        result = EmbeddingProfilesResult("ok", profiles=(entry,), provenance=provenance)
        owner = "repomap_kg.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        usernames = (PROFILE.identity.split(":")[1], "sha256", "snapmanifest1", "receipt1", "bundle1", "cand1",
                     "bind1", "snap1", "sg1", "cg1", "eg1", "kg1", "3" * 64, "4" * 64, "a" * 64)
        for username in usernames:
            with self.subTest(username=username), self._env(), patch(owner, return_value=result), patch(
                "pathlib.Path.home", return_value=Path("/private/fixture-home") / username,
            ):
                self.assertFalse(_profiles_need_redaction(result.to_jsonable(), (username,)))
                response = self._call({"graph_id": "repo-map", "selected": True})
            payload = response["structuredContent"]
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["profiles"], [entry])
            self.assertEqual(payload["provenance"], provenance)
