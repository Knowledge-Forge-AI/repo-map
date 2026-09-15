import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key
from repomap_kg.graph.keys import (
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
)


class CanonicalizationRubyLanguageFamilyUnitTests(unittest.TestCase):
    def test_ruby_definitions_create_generic_defines_edges(self):
        test_case_key = ruby_test_case_key("test/example_test.rb", "ExampleTest")
        observations = [
            RawObservation(
                kind="ruby.file",
                source_id="lib/example.rb#ruby-file",
                path="lib/example.rb",
                start_line=1,
                end_line=20,
                name="lib/example.rb",
                target=ruby_file_key("lib/example.rb"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"format": "ruby", "profile": "generic_ruby"},
            ),
            RawObservation(
                kind="ruby.module",
                source_id="lib/example.rb#module:Example",
                path="lib/example.rb",
                start_line=1,
                end_line=1,
                name="Example",
                target=ruby_module_key("Example"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"qualified_name": "Example", "profile": "generic_ruby"},
            ),
            RawObservation(
                kind="ruby.class",
                source_id="lib/example.rb#class:Example::Runner",
                path="lib/example.rb",
                start_line=2,
                end_line=2,
                name="Example::Runner",
                target=ruby_class_key("Example::Runner"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "qualified_name": "Example::Runner",
                    "superclass": "BaseRunner",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.method",
                source_id="lib/example.rb#method:Example::Runner:call",
                path="lib/example.rb",
                start_line=3,
                end_line=3,
                name="call",
                target=ruby_method_key("Example::Runner", "call"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "method_name": "call",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.singleton_method",
                source_id="lib/example.rb#singleton-method:Example::Runner:build",
                path="lib/example.rb",
                start_line=4,
                end_line=4,
                name="build",
                target=ruby_singleton_method_key("Example::Runner", "build"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "method_name": "build",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.constant",
                source_id="lib/example.rb#constant:Example::Runner:DEFAULT_URL",
                path="lib/example.rb",
                start_line=5,
                end_line=5,
                name="DEFAULT_URL",
                target=ruby_constant_key("Example::Runner", "DEFAULT_URL"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "constant_name": "DEFAULT_URL",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.test_case",
                source_id="test/example_test.rb#test-case:ExampleTest",
                path="test/example_test.rb",
                start_line=1,
                end_line=1,
                name="ExampleTest",
                target=test_case_key,
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "qualified_name": "ExampleTest",
                    "test_framework": "minitest",
                    "profile": "minitest",
                },
            ),
            RawObservation(
                kind="ruby.test_method",
                source_id="test/example_test.rb#test-method:ExampleTest:test_call",
                path="test/example_test.rb",
                start_line=2,
                end_line=2,
                name="test_call",
                target=ruby_test_method_key(test_case_key, "test_call"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "test_case_key": test_case_key,
                    "method_name": "test_call",
                    "test_framework": "minitest",
                    "profile": "minitest",
                },
            ),
            RawObservation(
                kind="ruby.route",
                source_id="sinatra_app.rb#route:get:/health",
                path="sinatra_app.rb",
                start_line=3,
                end_line=3,
                name="GET /health",
                target=ruby_route_key("sinatra_app.rb", "/routes/get:/health"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "route_method": "get",
                    "route_pattern": "/health",
                    "profile": "sinatra",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        edges = {
            (edge["kind"], edge["source_key"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertIn(
            "ruby.file:file%3Alib%2Fexample.rb",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "ruby.class:Example%3A%3ARunner",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "defines",
                "ruby.class:Example%3A%3ARunner",
                "ruby.method:Example%3A%3ARunner:call",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                test_case_key,
                ruby_test_method_key(test_case_key, "test_call"),
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "ruby.file:file%3Asinatra_app.rb",
                "ruby.route:file%3Asinatra_app.rb:%2Froutes%2Fget%3A%2Fhealth",
            ),
            edges,
        )

    def test_ruby_reference_creates_references_edge_and_parse_errors_are_raw_only(self):
        observation = RawObservation(
            kind="ruby.reference",
            source_id="lib/example.rb#reference:1:require-relative",
            path="lib/example.rb",
            start_line=1,
            end_line=1,
            name="example/service",
            target="file:lib/example/service.rb",
            confidence="extracted",
            extractor="repo-ruby",
            extractor_version="0.1.0",
            metadata={
                "source_key": ruby_file_key("lib/example.rb"),
                "reference_kind": "require_relative",
                "raw_value_summary": "example/service",
                "resolution_reason": "repo-local",
                "profile": "generic_ruby",
            },
        )
        parse_error = RawObservation(
            kind="ruby.parse_error",
            source_id="lib/example.rb#ruby-diagnostic:dynamic:2",
            path="lib/example.rb",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-ruby",
            extractor_version="0.1.0",
            metadata={
                "error_kind": "dynamic-ruby-construct",
                "dynamic": True,
                "dynamic_reason": "define_method",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key=ruby_file_key("lib/example.rb"),
            kind="references",
            target_key="file:lib/example/service.rb",
            identity_metadata={},
        )

        result = canonicalize_observations([observation, parse_error])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["edges"][0]["edge_key"], edge_key)
        self.assertEqual(payload["edges"][0]["kind"], "references")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "profiles": ["generic_ruby"],
                "raw_value_summaries": ["example/service"],
                "reference_kinds": ["require_relative"],
                "resolution_reasons": ["repo-local"],
            },
        )
        self.assertEqual(payload["edge_evidence_links"][0]["link_kind"], "supports")
