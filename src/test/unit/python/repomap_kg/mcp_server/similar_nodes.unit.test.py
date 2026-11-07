"""Unit tests for the repomap_similar_nodes MCP tool and dispatch surface."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from common_lore_index.ops.config_local import LocalSqliteConfig
from common_lore_index.server._mcp_dispatch import TOOL_FUNCTIONS
from common_lore_index.server._mcp_similar import SimilarNodesQuery, similar_nodes_payload
from common_lore_index.server.mcp import (
    handle_jsonrpc_message, handle_tool_call,
    repomap_similar_nodes as facade_similar_nodes,
    similar_nodes_payload as facade_similar_nodes_payload,
)
from common_lore_index.server.sqlite_read_binding import SqliteInvestigationStores
from common_lore_index.storage.semantic_candidate_readback import candidate_provenance
from common_lore_index.storage.semantic_candidates import CandidateResult, EmbeddingProfilesResult, validated_profile_entry
from repomap_test_support.mcp_server import McpServerTestSupport
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, SNAPSHOT, candidate_query


class SimilarNodesUnitTest(McpServerTestSupport):
    """Test suite for repomap_similar_nodes tool reachability and validation."""

    def _call_rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            message["params"] = params
        response = handle_jsonrpc_message(message)
        self.assertIsNotNone(response)
        assert response is not None
        return response

    def _call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call_rpc("tools/call", {"name": "repomap_similar_nodes", "arguments": arguments})

    def _valid_args(self, **overrides: Any) -> dict[str, Any]:
        args: dict[str, Any] = {
            "graph_id": "repo-map",
            "canonical_key": "symbol:main",
            "rebuild_id": "rebuild-20261008-01",
            "profile_identity": "sha256:" + "0" * 64,
            "dimensions": 128,
        }
        args.update(overrides)
        return args

    def test_tools_list_advertises_repomap_similar_nodes_contract(self) -> None:
        response = self._call_rpc("tools/list")
        tools = response["result"]["tools"]
        tool = next((t for t in tools if t["name"] == "repomap_similar_nodes"), None)
        self.assertIsNotNone(tool)
        assert tool is not None
        schema = tool["inputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(
            schema["required"],
            ["graph_id", "canonical_key", "rebuild_id", "profile_identity", "dimensions"],
        )
        self.assertNotIn("vector", schema["properties"])
        self.assertIn("selected", schema["properties"])
        self.assertIn("limit", schema["properties"])
        self.assertIn("evidence_limit", schema["properties"])
        self.assertIn("source_binding_id", schema["properties"])
        self.assertIn("kind", schema["properties"])
        self.assertIn("path", schema["properties"])

    def test_similar_nodes_baseline_disabled_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args())
        self.assertNotIn("error", response)
        result = response["result"]
        self.assertFalse(result.get("isError", False))
        payload = result["structuredContent"]
        self.assert_read_only_payload(payload)
        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["capability"], "pgvector-candidates-v1")
        self.assertEqual(payload["status"], "capability_unavailable")
        self.assertEqual(payload["reason"], "disabled")
        self.assertEqual(payload["candidates"], [])

    def test_similar_nodes_sqlite_unsupported_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())

        def sqlite_factory(config: Any) -> SqliteInvestigationStores:
            local = LocalSqliteConfig(
                config.config_path,
                config.config_home,
                config.config_files,
                config.schema_version,
                config.service,
                config.graphs,
                config.server_memory,
                config.sources,
            )
            return SqliteInvestigationStores(local)

        with env, patch("common_lore_index.server.ops.investigation_stores", sqlite_factory):
            disabled_resp = self._call_tool(self._valid_args(selected=False))
            unsupported_resp = self._call_tool(self._valid_args(selected=True))

        disabled_payload = disabled_resp["result"]["structuredContent"]
        self.assertEqual(disabled_payload["status"], "capability_unavailable")
        self.assertEqual(disabled_payload["reason"], "disabled")
        self.assertEqual(disabled_payload["graph"]["database_source"], "sqlite-graph-file")

        unsupported_payload = unsupported_resp["result"]["structuredContent"]
        self.assertEqual(unsupported_payload["status"], "capability_unavailable")
        self.assertEqual(unsupported_payload["reason"], "sqlite_unsupported")
        self.assertEqual(unsupported_payload["graph"]["database_source"], "sqlite-graph-file")

    def test_similar_nodes_hidden_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="hidden"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("graph 'hidden' is not MCP-visible", result["content"][0]["text"])

    def test_similar_nodes_disabled_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="disabled"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("graph 'disabled' is not enabled", result["content"][0]["text"])

    def test_similar_nodes_unknown_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="unknown-graph-id"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("unknown graph_id: unknown-graph-id", result["content"][0]["text"])

    def test_similar_nodes_private_graph_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="private-visible", selected=True))
        self.assertNotIn("error", response)
        result = response["result"]
        payload = result["structuredContent"]
        self.assert_private_graph_payload(payload["graph"])
        self.assertEqual(payload["status"], "capability_unavailable")
        self.assertEqual(payload["reason"], "private_graph_unsupported")

    def test_similar_nodes_rejects_booleans_as_ints(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_dim = self._call_tool(self._valid_args(dimensions=True))
            self.assertTrue(resp_dim["result"]["isError"])
            self.assertIn(
                "embedding dimensions must be between 1 and 2000",
                resp_dim["result"]["content"][0]["text"],
            )

            resp_lim = self._call_tool(self._valid_args(limit=True))
            self.assertTrue(resp_lim["result"]["isError"])
            self.assertIn(
                "candidate limit must be between 1 and 100",
                resp_lim["result"]["content"][0]["text"],
            )

            resp_ev = self._call_tool(self._valid_args(evidence_limit=False))
            self.assertTrue(resp_ev["result"]["isError"])
            self.assertIn(
                "evidence limit must be between 1 and 20",
                resp_ev["result"]["content"][0]["text"],
            )

            resp_sel = self._call_tool(self._valid_args(selected=1))
            self.assertTrue(resp_sel["result"]["isError"])
            self.assertIn(
                "candidate selection must be explicit boolean",
                resp_sel["result"]["content"][0]["text"],
            )

    def test_similar_nodes_rejects_out_of_bound_ranges(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_dim_zero = self._call_tool(self._valid_args(dimensions=0))
            self.assertTrue(resp_dim_zero["result"]["isError"])
            resp_dim_large = self._call_tool(self._valid_args(dimensions=2500))
            self.assertTrue(resp_dim_large["result"]["isError"])

            resp_lim_zero = self._call_tool(self._valid_args(limit=0))
            self.assertTrue(resp_lim_zero["result"]["isError"])
            resp_lim_large = self._call_tool(self._valid_args(limit=150))
            self.assertTrue(resp_lim_large["result"]["isError"])

            resp_ev_zero = self._call_tool(self._valid_args(evidence_limit=0))
            self.assertTrue(resp_ev_zero["result"]["isError"])
            resp_ev_large = self._call_tool(self._valid_args(evidence_limit=25))
            self.assertTrue(resp_ev_large["result"]["isError"])

    def test_similar_nodes_rejects_unsafe_identities_and_keys(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_rebuild = self._call_tool(self._valid_args(rebuild_id="../etc/passwd"))
            self.assertTrue(resp_rebuild["result"]["isError"])
            self.assertIn("invalid enrichment identity", resp_rebuild["result"]["content"][0]["text"])

            resp_space = self._call_tool(self._valid_args(rebuild_id="bad id"))
            self.assertTrue(resp_space["result"]["isError"])
            self.assertIn("invalid enrichment identity", resp_space["result"]["content"][0]["text"])

            resp_profile = self._call_tool(self._valid_args(profile_identity="invalid-profile"))
            self.assertTrue(resp_profile["result"]["isError"])
            self.assertIn("invalid embedding profile identity", resp_profile["result"]["content"][0]["text"])

            resp_key_empty = self._call_tool(self._valid_args(canonical_key=""))
            self.assertTrue(resp_key_empty["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_key_empty["result"]["content"][0]["text"])

            resp_key_null = self._call_tool(self._valid_args(canonical_key="bad\x00key"))
            self.assertTrue(resp_key_null["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_key_null["result"]["content"][0]["text"])

            resp_filter = self._call_tool(self._valid_args(kind="bad\x00kind"))
            self.assertTrue(resp_filter["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_filter["result"]["content"][0]["text"])

    def test_similar_nodes_rejects_vector_and_unexpected_args(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp = self._call_tool(self._valid_args(vector=[0.1, 0.2, 0.3]))
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("unexpected argument(s): vector", resp["result"]["content"][0]["text"])

    def test_similar_nodes_rejects_missing_required_args(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            args = self._valid_args()
            del args["dimensions"]
            resp = self._call_tool(args)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("missing required argument(s): dimensions", resp["result"]["content"][0]["text"])

    def test_similar_nodes_dispatches_to_investigation_store_when_implemented(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        received_queries: list[SimilarNodesQuery] = []

        class FakeStore:
            def similar_nodes(self, graph_id: str, query: SimilarNodesQuery) -> CandidateResult:
                received_queries.append(query)
                return CandidateResult(
                    status="candidate_discovery",
                    reason=None,
                    candidates=({"canonical_key": "symbol:helper", "score": 0.92},),
                    provenance={"run_id": 42},
                )

        class FakeBinding:
            def storage_label(self, selection: Any) -> str:
                return "fake-storage"

            def investigation_store(self) -> FakeStore:
                return FakeStore()

        with env, patch("common_lore_index.server.ops.investigation_stores", lambda cfg: FakeBinding()):
            response = self._call_tool(
                self._valid_args(
                    selected=True,
                    limit=10,
                    evidence_limit=3,
                    kind="function",
                    path="src/main.py",
                    source_binding_id="src-1",
                )
            )

        self.assertNotIn("error", response)
        result = response["result"]
        self.assertFalse(result.get("isError", False))
        payload = result["structuredContent"]
        self.assertEqual(payload["status"], "candidate_discovery")
        self.assertIsNone(payload["reason"])
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["canonical_key"], "symbol:helper")
        self.assertEqual(payload["provenance"], {"run_id": 42})
        self.assertEqual(len(received_queries), 1)
        q = received_queries[0]
        self.assertEqual(q.canonical_key, "symbol:main")
        self.assertEqual(q.rebuild_id, "rebuild-20261008-01")
        self.assertEqual(q.profile_identity, "sha256:" + "0" * 64)
        self.assertEqual(q.dimensions, 128)
        self.assertTrue(q.selected)
        self.assertEqual(q.limit, 10)
        self.assertEqual(q.evidence_limit, 3)
        self.assertEqual(q.kind, "function")
        self.assertEqual(q.path, "src/main.py")
        self.assertEqual(q.source_binding_id, "src-1")

    def test_facade_and_direct_tool_call_reachability(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            direct = handle_tool_call("repomap_similar_nodes", self._valid_args())
            self.assertEqual(direct["structuredContent"]["status"], "capability_unavailable")

            facade = facade_similar_nodes(**self._valid_args())
            self.assertEqual(facade["status"], "capability_unavailable")

            payload = similar_nodes_payload(**self._valid_args())
            self.assertEqual(payload["status"], "capability_unavailable")

            facade_payload = facade_similar_nodes_payload(**self._valid_args())
            self.assertEqual(facade_payload["status"], "capability_unavailable")

        self.assertEqual(TOOL_FUNCTIONS["repomap_similar_nodes"], "repomap_similar_nodes")

    def _fixture_results(self, profile: Any = None) -> tuple[EmbeddingProfilesResult, CandidateResult]:
        prof = replace(PROFILE, generator="synthetic-fixture-author") if profile is None else profile
        pub = candidate_query().publication.validate()
        gens = replace(pub.publication.receipt.generations, source_generation="sg1:" + "a" * 64,
                       config_generation="cg1:" + "b" * 64, extractor_generation="eg1:" + "c" * 64,
                       canonicalizer_generation="kg1:" + "d" * 64)
        pub = replace(pub, publication=replace(pub.publication, receipt=replace(pub.publication.receipt, generations=gens))).validate()
        scope = [{"source_binding_id": BINDING, "snapshot_id": SNAPSHOT}]
        entry = validated_profile_entry({"rebuild_id": "fixture", "profile_identity": prof.identity,
                                         **prof.__dict__, "row_count": 5, "source_scope": scope}, pub)
        prof_prov = {"receipt_identity": pub.receipt_identity, "publication": pub.publication.receipt.public_mapping(),
                     "generations": dict(zip(gens.field_names(), gens.values(), strict=True)), "privacy_class": "public",
                     "pgvector_version": "0.8.7", "snapshot_contract": "receipt-fenced metadata and source evidence in one SQL statement"}
        seed = {"canonical_key": "file:tools/runner_arguments.py", "source_binding_id": BINDING, "snapshot_id": SNAPSHOT}
        sim_prov = {**candidate_provenance(pub, prof, "fixture"), "seed": seed,
                    "snapshot_contract": "receipt-fenced seed and candidates in one SQL statement"}
        cands = ({"canonical_key": "file:tools/runner_arguments.py", "display_name": "runner_arguments.py",
                  "source_binding_id": BINDING, "snapshot_id": SNAPSHOT, "input_digest": "sha256:" + "1" * 64,
                  "distance": 0.0, "evidence": [{"evidence_key": "evidence:1:tools/runner_arguments.py:1-5:src:s1", "path": "tools/runner_arguments.py", "raw_kind": "file", "extractor": "src"}]},
                 {"canonical_key": "file:src/app/test_service.py", "display_name": "test_service.py",
                  "source_binding_id": BINDING, "snapshot_id": SNAPSHOT, "input_digest": "sha256:" + "2" * 64,
                  "distance": 0.5, "evidence": [{"evidence_key": "evidence:2:src/app/test_service.py:1-5:test:s1", "path": "src/app/test_service.py", "raw_kind": "file", "extractor": "test"}]})
        return EmbeddingProfilesResult("ok", profiles=(entry,), provenance=prof_prov), CandidateResult("ok", None, cands, sim_prov)

    def test_similar_nodes_refuses_private_paths_and_provenance_usernames(self) -> None:
        _, clean = self._fixture_results()
        assert clean.provenance is not None
        home, digest = Path("/private/fixture-home/privateuser"), "a" * 64
        bad_cand = ({**clean.candidates[0], "evidence": [{"evidence_key": "evidence:1:a.py:1-2:src:s1", "path": f"{home}/secret.py"}]},)
        bad_ev_key = ({**clean.candidates[0], "evidence": [{"evidence_key": f"evidence:1:{home}/secret.py:1-2:src:s1", "path": "src/a.py"}]},)
        bad_ev_url = ({**clean.candidates[0], "evidence": [{"evidence_key": "https://u:p@example.com/a", "path": "src/a.py"}]},)
        long_key = ({**clean.candidates[0], "canonical_key": "file:" + "x" * 500},)
        cases: list[tuple[str, str, CandidateResult]] = [
            ("cand-path", "privateuser", replace(clean, candidates=bad_cand)),
            ("ev-key-path", "privateuser", replace(clean, candidates=bad_ev_key)),
            ("ev-key-url", "privateuser", replace(clean, candidates=bad_ev_url)),
            ("long-key", "privateuser", replace(clean, candidates=long_key)),
            ("seed-path", "privateuser", replace(clean, provenance={**clean.provenance, "seed": {**clean.provenance["seed"], "canonical_key": f"file:{home}/a.py"}})),
            ("prof-path", "privateuser", replace(clean, provenance={**clean.provenance, "profile": {**clean.provenance["profile"], "model": f"{home}/m"}})),
            ("model-user", "privateuser", self._fixture_results(replace(PROFILE, model="fixture-privateuser-model"))[1]),
            ("gen-user", "privateuser", self._fixture_results(replace(PROFILE, generator="privateuser:" + digest))[1]),
            ("mver-user", "privateuser", self._fixture_results(replace(PROFILE, model_version="privateuser"))[1]),
            ("gver-user", "privateuser", self._fixture_results(replace(PROFILE, generator_version="privateuser"))[1]),
            ("nested-user", "privateuser", replace(clean, provenance={**clean.provenance, "nested": [{"claim": "privateuser"}]})),
            ("bad-prof-id", "privateuser", replace(clean, provenance={**clean.provenance, "profile_identity": "privateuser:" + digest})),
            ("bad-bind-id", "privateuser", replace(clean, provenance={**clean.provenance, "seed": {**clean.provenance["seed"], "source_binding_id": "privateuser:" + digest}})),
            ("bad-snap-id", "privateuser", replace(clean, provenance={**clean.provenance, "seed": {**clean.provenance["seed"], "snapshot_id": "privateuser:" + digest}})),
            ("bad-metric", "privateuser", replace(clean, provenance={**clean.provenance, "profile": {**clean.provenance["profile"], "metric": "privateuser"}})),
            ("bad-search", "privateuser", replace(clean, provenance={**clean.provenance, "search": "privateuser"})),
            ("bad-val", "privateuser", replace(clean, provenance={**clean.provenance, "input_digest_validation": "privateuser"})),
            ("bad-contract", "privateuser", replace(clean, provenance={**clean.provenance, "snapshot_contract": "privateuser"})),
            ("model-sha256", "sha256", replace(clean, provenance={**clean.provenance, "profile": {**clean.provenance["profile"], "model": "sha256:" + digest}})),
            ("nested-bind1", "bind1", replace(clean, provenance={**clean.provenance, "nested": {"source_binding_id": "bind1:" + digest}})),
        ]
        owner = "common_lore_index.server.investigation_read_store.PostgresInvestigationReadStore.similar_nodes"
        for label, user, candidate_res in cases:
            frozen = deepcopy((candidate_res.candidates, candidate_res.provenance))
            with self.subTest(case=label), self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config()), patch(owner, return_value=candidate_res), patch("pathlib.Path.home", return_value=Path("/private/fixture-home") / user):
                payload = self._call_tool(self._valid_args(selected=True))["result"]["structuredContent"]
                self.assertEqual((payload["status"], payload["reason"], payload["candidates"], payload["provenance"], (candidate_res.candidates, candidate_res.provenance)), ("capability_unavailable", "privacy_refused", [], None, frozen))

    def test_similar_nodes_preserves_candidate_paths_and_agrees_with_discovery(self) -> None:
        prof_res, sim_res = self._fixture_results()
        expected_cands, expected_prov = deepcopy(list(sim_res.candidates)), deepcopy(sim_res.provenance)
        expected_ev = [ev["evidence_key"] for cand in expected_cands for ev in cand["evidence"]]
        prof_owner = "common_lore_index.server.investigation_read_store.PostgresInvestigationReadStore.embedding_profiles"
        sim_owner = "common_lore_index.server.investigation_read_store.PostgresInvestigationReadStore.similar_nodes"
        usernames = (prof_res.profiles[0]["profile_identity"].split(":")[1], "sha256", "snapmanifest1", "receipt1",
                     "bundle1", "cand1", "bind1", "snap1", "sg1", "cg1", "eg1", "kg1", "cosine", "exact", "public",
                     "canonical", "node", "l2", "unit", "enrichment_principal_assertion", "receipt", "fenced",
                     "seed", "candidates", "runner", "src", "app", "test", "3" * 64, "4" * 64, "a" * 64)
        for user in usernames:
            with self.subTest(user=user), self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config()), patch(prof_owner, return_value=prof_res), patch(sim_owner, return_value=sim_res), patch("pathlib.Path.home", return_value=Path("/private/fixture-home") / user):
                disc = self._call_rpc("tools/call", {"name": "repomap_embedding_profiles", "arguments": {"graph_id": "repo-map", "selected": True}})["result"]["structuredContent"]
                chosen = disc["profiles"][0]
                sim = self._call_tool(self._valid_args(canonical_key="file:tools/runner_arguments.py", rebuild_id=chosen["rebuild_id"], profile_identity=chosen["profile_identity"], dimensions=chosen["dimensions"], selected=True))["result"]["structuredContent"]
                ev_keys = [ev["evidence_key"] for cand in sim["candidates"] for ev in cand["evidence"]]
                self.assertEqual((disc["status"], sim["status"], sim["candidates"], sim["provenance"], sim["provenance"]["profile_identity"], ev_keys, list(sim_res.candidates), sim_res.provenance), ("ok", "ok", expected_cands, expected_prov, chosen["profile_identity"], expected_ev, expected_cands, expected_prov))
        priv_prof, priv_sim = self._fixture_results(replace(PROFILE, model="fixture-privateuser-model"))
        with self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config()), patch(prof_owner, return_value=priv_prof), patch(sim_owner, return_value=priv_sim), patch("pathlib.Path.home", return_value=Path("/private/fixture-home/privateuser")):
            disc_ref = self._call_rpc("tools/call", {"name": "repomap_embedding_profiles", "arguments": {"graph_id": "repo-map", "selected": True}})["result"]["structuredContent"]
            sim_ref = self._call_tool(self._valid_args(selected=True))["result"]["structuredContent"]
        self.assertEqual((disc_ref["reason"], sim_ref["reason"]), ("privacy_refused", "privacy_refused"))
