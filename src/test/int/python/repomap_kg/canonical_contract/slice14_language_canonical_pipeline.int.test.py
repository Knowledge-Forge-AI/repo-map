"""Retained Slice14 public canonicalizer compositions; isolated Terraform controls moved to unit ownership."""

from __future__ import annotations

import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.keys import (
    js_class_key,
    js_route_key,
    js_method_key,
    ruby_constant_key,
    ruby_singleton_method_key,
    js_test_case_key,
    js_test_suite_key,
    ruby_test_case_key,
    ruby_test_method_key,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.canonicalization.records import CanonicalizationResult


class Slice14LanguageCanonicalPipelineIntegrationTests(unittest.TestCase):
    """Slice 14 Group S14-A integration tests for language and config canonical pipeline."""

    def _make_obs(
        self,
        kind: str,
        source_id: str,
        path: str,
        name: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RawObservation:
        return RawObservation(
            kind=kind,
            source_id=source_id,
            path=path,
            name=name,
            confidence="extracted",
            extractor="slice14-test-extractor",
            extractor_version="1.0.0",
            metadata=metadata or {},
        )

    def _assert_evidence(self, result: CanonicalizationResult, observations: list[RawObservation]) -> None:
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.graph.raw_observation_count, len(observations))
        self.assertEqual(len(result.graph.evidence), len(observations))
        evidence_by_id = {item.raw_source_id: item for item in result.graph.evidence}
        self.assertEqual(set(evidence_by_id), {item.source_id for item in observations})
        for observation in observations:
            evidence = evidence_by_id[observation.source_id]
            self.assertEqual((evidence.raw_kind, evidence.path, evidence.metadata),
                             (observation.kind, observation.path, observation.metadata))
            self.assertEqual((evidence.extractor, evidence.extractor_version),
                             ("slice14-test-extractor", "1.0.0"))
            links = [link for link in result.graph.edge_evidence_links
                     if link.evidence_key == evidence.evidence_key]
            self.assertEqual(len(links), 1)
            edge = next(edge for edge in result.graph.edges if edge.edge_key == links[0].edge_key)
            node_links = {link.canonical_key for link in result.graph.node_evidence_links
                          if link.evidence_key == evidence.evidence_key}
            self.assertEqual(node_links, {edge.source_key, edge.target_key})

    def test_s14_a01_ruby_method_with_module_owner(self) -> None:
        """Ruby method with owner_kind ruby.module canonicalizes with ruby.module owner key."""
        obs = self._make_obs(
            "ruby.method",
            "m1",
            "lib/utils.rb",
            name="format_name",
            metadata={"owner": "Utils", "owner_kind": "ruby.module"},
        )
        res = canonicalize_observations([obs])
        self.assertTrue(res.ok)
        self._assert_evidence(res, [obs])
        self.assertEqual(len(res.graph.edges), 1)
        edge = res.graph.edges[0]
        self.assertEqual(edge.source_key, "ruby.module:Utils")
        self.assertEqual(edge.target_key, "ruby.method:Utils:format_name")

    def test_s14_a02_ruby_test_method_with_test_case_key(self) -> None:
        """Ruby test method with valid test_case_key canonicalizes to expected edge target."""
        tc_key = ruby_test_case_key("test/test_app.rb", "AppTest")
        obs = self._make_obs(
            "ruby.test_method",
            "tm1",
            "test/test_app.rb",
            name="test_default_flow",
            metadata={"test_case_key": tc_key},
        )
        res = canonicalize_observations([obs])
        self.assertTrue(res.ok)
        self._assert_evidence(res, [obs])
        self.assertEqual(len(res.graph.edges), 1)
        edge = res.graph.edges[0]
        self.assertEqual(edge.source_key, tc_key)
        self.assertEqual(edge.target_key, ruby_test_method_key(tc_key, "test_default_flow"))

    def test_s14_a03_ruby_singleton_method_and_constant_with_class_owner(self) -> None:
        """Ruby singleton method and constant with class owner resolve to ruby.class keys."""
        obs1 = self._make_obs(
            "ruby.singleton_method",
            "sm1",
            "lib/app.rb",
            name="instance",
            metadata={"owner": "App", "owner_kind": "ruby.class"},
        )
        obs2 = self._make_obs(
            "ruby.constant",
            "c1",
            "lib/app.rb",
            name="DEFAULT_PORT",
            metadata={"owner": "App", "owner_kind": "ruby.class"},
        )
        res = canonicalize_observations([obs1, obs2])
        self.assertTrue(res.ok)
        self._assert_evidence(res, [obs1, obs2])
        sources = {e.source_key for e in res.graph.edges}
        self.assertEqual(sources, {"ruby.class:App"})
        self.assertEqual({edge.target_key for edge in res.graph.edges}, {
            ruby_singleton_method_key("App", "instance"), ruby_constant_key("App", "DEFAULT_PORT")})
        self.assertEqual(len(res.graph.edges), 2)

    def test_s14_a04_javascript_method_class_key_and_class_name_alternatives(self) -> None:
        """JavaScript method canonicalization supports explicit class_key or class_name resolution."""
        cls_key = js_class_key("src/controller.js", "UserController")
        obs1 = self._make_obs(
            "js.method",
            "jm1",
            "src/controller.js",
            name="index",
            metadata={"class_key": cls_key},
        )
        obs2 = self._make_obs(
            "js.method",
            "jm2",
            "src/controller.js",
            name="show",
            metadata={"class_name": "UserController"},
        )
        res = canonicalize_observations([obs1, obs2])
        self.assertTrue(res.ok)
        self._assert_evidence(res, [obs1, obs2])
        self.assertEqual(len(res.graph.edges), 2)
        self.assertEqual({edge.target_key for edge in res.graph.edges}, {
            js_method_key(cls_key, "index"), js_method_key(cls_key, "show")})
        for edge in res.graph.edges:
            self.assertEqual(edge.source_key, cls_key)

    def test_s14_a05_javascript_test_suite_and_case_custom_pointers(self) -> None:
        """JavaScript test suite and test case accept explicit pointer metadata."""
        suite_key = js_test_suite_key("test/service.test.js", "/custom/suite/path")
        obs1 = self._make_obs(
            "js.test_suite",
            "ts1",
            "test/service.test.js",
            name="ServiceSuite",
            metadata={"test_pointer": "/custom/suite/path"},
        )
        obs2 = self._make_obs(
            "js.test_case",
            "tc1",
            "test/service.test.js",
            name="verifies health",
            metadata={
                "test_suite_key": suite_key,
                "test_pointer": "/custom/case/health",
            },
        )
        res = canonicalize_observations([obs1, obs2])
        self.assertTrue(res.ok)
        self._assert_evidence(res, [obs1, obs2])
        expected_case_key = js_test_case_key(suite_key, "/custom/case/health")
        case_edges = [e for e in res.graph.edges if e.target_key == expected_case_key]
        self.assertEqual(len(case_edges), 1)
        self.assertEqual(case_edges[0].source_key, suite_key)

    def test_s14_a06_javascript_route_definition_pointer(self) -> None:
        """JavaScript route observation requires and resolves explicit route_pointer."""
        obs = self._make_obs(
            "js.route",
            "r1",
            "src/api.js",
            name="listOrders",
            metadata={"route_pointer": "/api/v1/orders"},
        )
        res = canonicalize_observations([obs])
        self.assertTrue(res.ok)
        self.assertEqual(len(res.graph.edges), 1)
        self._assert_evidence(res, [obs])
        expected_route_key = js_route_key("src/api.js", "/api/v1/orders")
        self.assertEqual(res.graph.edges[0].target_key, expected_route_key)
