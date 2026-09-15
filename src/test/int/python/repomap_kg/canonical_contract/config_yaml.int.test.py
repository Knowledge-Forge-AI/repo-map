import unittest

from repomap_test_support.canonical_contract import DISCOVERY_FIXTURE_ROOT

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.config.generic import extract_config_file_observations, json_pointer
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.observations import RawObservation


class CanonicalConfigYamlIntegrationTests(unittest.TestCase):
    def test_config_canonicalization_placeholder_and_raw_only_contracts(self):
        result = canonicalize_observations(
            [
                RawObservation(
                    kind="config.path",
                    source_id="settings.json#config-path:missing",
                    path="settings.json",
                    confidence="extracted",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "json"},
                ),
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/missing:0",
                    path="settings.json",
                    name="/missing",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/missing",
                        "source_path_key": "config.path:file%3Asettings.json:%2Fmissing",
                    },
                ),
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/bad:0",
                    path="settings.json",
                    name="/bad",
                    target="bad target",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/bad",
                        "source_path_key": "config.path:file%3Asettings.json:%2Fbad",
                    },
                ),
                RawObservation(
                    kind="config.parse_error",
                    source_id="settings.json#config-parse-error:document",
                    path="settings.json",
                    confidence="unknown",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "json", "error_kind": "malformed-json"},
                ),
                RawObservation(
                    kind="config.jsonl_record",
                    source_id="events.jsonl#jsonl-record:1",
                    path="events.jsonl",
                    start_line=1,
                    end_line=1,
                    confidence="extracted",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "jsonl", "record_index": 0},
                ),
            ]
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 5)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["edges"], 2)
        self.assertEqual(payload["summary"]["evidence"], 4)
        self.assertEqual(payload["diagnostics"][1]["placeholder_key"], "unknown:config.reference:missing-target")
        self.assertEqual(payload["diagnostics"][2]["placeholder_key"], "unknown:config.reference:malformed-target")
        self.assertEqual(
            {
                edge["target_key"]
                for edge in payload["edges"]
                if edge["kind"] == "references"
            },
            {
                "unknown:config.reference:missing-target",
                "unknown:config.reference:malformed-target",
            },
        )

    def test_config_reference_rejects_non_config_source_path_key_contract(self):
        result = canonicalize_observations(
            [
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/command:0",
                    path="settings.json",
                    name="/command",
                    target="tool:repomap-kg",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/command",
                        "source_path_key": "file:settings.json",
                    },
                )
            ]
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")

    def test_yaml_config_extraction_and_canonicalization_contract(self):
        fixture = DISCOVERY_FIXTURE_ROOT / "yaml_basic"
        observations = discover_observations(fixture)
        yaml_observations = [
            observation
            for observation in observations
            if observation.metadata.get("format") == "yaml"
        ]
        payload = "\n".join(observation.to_json_line() for observation in yaml_observations)
        result = canonicalize_observations(observations)
        graph = result.to_dict()

        self.assertTrue(result.ok, graph["diagnostics"])
        self.assertNotIn("fake-actions-token", payload)
        self.assertNotIn("fake-kubernetes-password", payload)
        self.assertNotIn("fake-client-secret", payload)
        self.assertTrue(
            any(
                observation.kind == "config.parse_error"
                and observation.metadata.get("error_kind") == "malformed-yaml"
                for observation in yaml_observations
            )
        )
        self.assertTrue(
            any(
                observation.kind == "config.parse_error"
                and observation.metadata.get("error_kind") == "duplicate-yaml-key"
                for observation in yaml_observations
            )
        )
        node_keys = {node["canonical_key"] for node in graph["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in graph["edges"]
        }

        self.assertIn("config.document:file%3Aopenapi.yaml", node_keys)
        self.assertIn(
            "config.path:file%3Amulti-kubernetes.yaml:%2Fdocuments%2F1%2Fspec%2Ftemplate%2Fspec%2Fcontainers%2Fapp%2Fimage",
            node_keys,
        )
        self.assertIn(
            (
                "config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses",
                "references",
                "external:github.action:actions%2Fcheckout%40v4",
            ),
            edge_pairs,
        )
        self.assertIn(
            (
                "config.path:file%3Aopenapi.yaml:%2Fpaths%2F~1pets%2Fget%2Fresponses%2F200%2F%24ref",
                "references",
                "config.path:file%3Aopenapi.yaml:%2Fcomponents%2Fresponses%2FPets",
            ),
            edge_pairs,
        )
        self.assertIn(
            (
                "config.path:file%3Adocker-compose.yml:%2Fservices%2Fapp%2Fimage",
                "references",
                "external:docker.image:example%2Fapp%3Alatest",
            ),
            edge_pairs,
        )

    def test_yaml_parser_safety_limit_and_reference_contracts(self):
        observations = extract_config_file_observations(
            ".github/workflows/advanced.yml",
            """
name: advanced
on: [push, "pull_request"]
jobs:
  build:
    steps:
      - name: local action
        uses: ./local-action
      - name: dynamic action
        uses: ${{ matrix.action }}
      - name: repo escape
        uses: ../../../outside-action
      - name: mixed scalars
        with: {enabled: true, retries: 3, ratio: 1.5, empty: null}
defaults: &defaults
  repository: https://charts.example.invalid
  path_value: /etc/example/config.yml
  config_path: ~/dynamic/config.yml
service:
  <<: *defaults
  include_file: !include ./extra-values.yml
  token_ref: !vault
    value: fake-vault-value
fingerprint: keytoken012345678901234567890123456789
""",
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_metadata = {item.metadata["pointer"]: item.metadata for item in paths}
        targets = {item.target for item in references}
        reference_reasons = {
            (item.metadata["pointer"], item.metadata["resolution_reason"])
            for item in references
        }

        self.assertNotIn("fake-vault-value", payload)
        self.assertEqual(observations[0].metadata["profile"], "github_actions")
        self.assertEqual(pointer_metadata["/defaults"].get("anchor"), "defaults")
        self.assertTrue(pointer_metadata["/service/<<"].get("merge_key"))
        self.assertEqual(pointer_metadata["/service/<<"].get("alias"), "defaults")
        self.assertEqual(
            pointer_metadata["/service/include_file"].get("yaml_tag"),
            "!include",
        )
        self.assertEqual(
            pointer_metadata["/service/token_ref"].get("yaml_tag"),
            "!vault",
        )
        self.assertTrue(pointer_metadata["/fingerprint"].get("redacted"))
        self.assertIn("file:local-action", targets)
        self.assertIn("dynamic:github.action:dynamic-yaml-uses", targets)
        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            targets,
        )
        self.assertIn("external.url:https%3A%2F%2Fcharts.example.invalid", targets)
        self.assertIn(
            "external:file:absolute-config-reference",
            targets,
        )
        self.assertIn(
            "dynamic:file:config-reference-expanded-from-variable",
            targets,
        )
        self.assertIn("file:.github/workflows/extra-values.yml", targets)
        self.assertIn(("/jobs/build/steps/local action/uses", "github-actions-local-uses"), reference_reasons)

        parse_error_cases = {
            "too-large.yaml": (
                "description: " + ("x" * 1_048_577),
                "yaml-file-byte-limit",
            ),
            "too-many-documents.yaml": (
                "".join(f"---\nname: doc-{index}\n" for index in range(65)),
                "yaml-document-count-limit",
            ),
            "too-deep.yaml": (
                "".join(("  " * index) + f"k{index}:\n" for index in range(66))
                + ("  " * 66)
                + "leaf: value\n",
                "yaml-depth-limit",
            ),
            "too-many-aliases.yaml": (
                "defaults: &defaults value\nrefs:\n"
                + "".join("  - *defaults\n" for _ in range(513)),
                "yaml-alias-count-limit",
            ),
            "tab-indent.yaml": (
                "root:\n\tchild: value\n",
                "malformed-yaml",
            ),
            "bad-inline-sequence.yaml": (
                "items: [one, two\n",
                "malformed-yaml",
            ),
            "bad-inline-mapping.yaml": (
                "items: {name: app\n",
                "malformed-yaml",
            ),
            "duplicate-inline-mapping.yaml": (
                "items: {name: app, name: api}\n",
                "duplicate-yaml-key",
            ),
        }
        for path, (content, error_kind) in parse_error_cases.items():
            with self.subTest(path=path):
                case_observations = extract_config_file_observations(path, content)

                self.assertEqual([item.kind for item in case_observations], ["config.parse_error"])
                self.assertEqual(case_observations[0].metadata["format"], "yaml")
                self.assertEqual(case_observations[0].metadata["error_kind"], error_kind)

    def test_yaml_parser_edge_case_contracts(self):
        self.assertEqual(json_pointer([]), "")
        self.assertEqual(json_pointer(["a/b", "c~d"]), "/a~1b/c~0d")
        empty_document = extract_config_file_observations("empty.yaml", "")
        self.assertEqual([item.kind for item in empty_document], ["config.document"])
        self.assertEqual(empty_document[0].metadata["top_level_type"], "null")

        observations = extract_config_file_observations(
            "profiles/app.yml",
            """
items:
  - name: with-nested-list-error-source
    path: ../shared/config.yml
refs:
  ref: models/pet.yaml#/Pet
env:
  NOT-VALID!: value
quoted:
  single: 'it''s safe'
  invalid_escape: "bad\\x"
scalars:
  enabled: false
  nothing: ~
  count: +42
  ratio: -1.5
empty_inline:
  seq: []
  map: {}
""",
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_metadata = {item.metadata["pointer"]: item.metadata for item in paths}
        edge_targets = {
            (item.metadata["pointer"], item.target, item.metadata["resolution_reason"])
            for item in references
        }

        self.assertIn("/items", pointer_metadata)
        self.assertIn("/items/with-nested-list-error-source/path", pointer_metadata)
        self.assertIn(
            (
                "/items/with-nested-list-error-source/path",
                "file:shared/config.yml",
                "relative-file-reference",
            ),
            edge_targets,
        )
        self.assertIn(
            (
                "/refs/ref",
                "file:models/pet.yaml",
                "openapi-local-file-ref",
            ),
            edge_targets,
        )
        self.assertIn(
            (
                "/env/NOT-VALID!",
                "dynamic:env:dynamic-config-env-name",
                "dynamic-env-object-key",
            ),
            edge_targets,
        )
        self.assertEqual(pointer_metadata["/quoted/single"]["value_summary"], "it's safe")
        self.assertEqual(pointer_metadata["/quoted/invalid_escape"]["value_summary"], "bad\\x")
        self.assertEqual(pointer_metadata["/scalars/enabled"]["value_summary"], False)
        self.assertNotIn("value_summary", pointer_metadata["/scalars/nothing"])
        self.assertEqual(pointer_metadata["/scalars/count"]["value_summary"], 42)
        self.assertEqual(pointer_metadata["/scalars/ratio"]["value_summary"], -1.5)
        self.assertEqual(pointer_metadata["/empty_inline/seq"]["item_count"], 0)
        self.assertEqual(pointer_metadata["/empty_inline/map"]["value_type"], "object")

        invalid_cases = {
            "sequence-then-mapping.yaml": "- one\nname: after\n",
            "empty-sequence-item.yaml": "items:\n  -\n",
            "missing-colon.yaml": "name value\n",
            "bad-nested-sequence.yaml": "items:\n  - name: app\n    - bad\n",
            "bad-inline-depth.yaml": "items: [one]]\n",
        }
        for path, content in invalid_cases.items():
            with self.subTest(path=path):
                case_observations = extract_config_file_observations(path, content)

                self.assertEqual([item.kind for item in case_observations], ["config.parse_error"])
                self.assertEqual(case_observations[0].metadata["format"], "yaml")
