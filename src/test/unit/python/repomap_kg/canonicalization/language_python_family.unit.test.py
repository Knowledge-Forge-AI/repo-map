import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key


class CanonicalizationPythonLanguageFamilyUnitTests(unittest.TestCase):
    def test_python_module_creates_file_defines_module_edge(self):
        observation = RawObservation(
            kind="python.module",
            source_id="src/main/python/repomap_kg/cli.py#module:repomap_kg.cli",
            path="src/main/python/repomap_kg/cli.py",
            start_line=1,
            end_line=5,
            name="repomap_kg.cli",
            target="python.module:repomap_kg.cli",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "repomap_kg.cli",
                "package_root": "src/main/python",
                "parser": "ast",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:src/main/python/repomap_kg/cli.py",
            kind="defines",
            target_key="python.module:repomap_kg.cli",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "file:src/main/python/repomap_kg/cli.py",
                "python.module:repomap_kg.cli",
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:src/main/python/repomap_kg/cli.py",
                    "kind": "defines",
                    "target_key": "python.module:repomap_kg.cli",
                    "identity_metadata": {},
                    "metadata": {"modules": ["repomap_kg.cli"]},
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["evidence"][0]["start_line"], 1)
        self.assertEqual(payload["evidence"][0]["end_line"], 5)

    def test_python_symbol_kinds_create_file_defines_symbol_edges(self):
        observations = [
            RawObservation(
                kind="python.class",
                source_id="src/main/python/app.py#class:3:Service",
                path="src/main/python/app.py",
                start_line=3,
                end_line=5,
                name="Service",
                target="python.class:app:Service",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "bases": [], "decorators": []},
            ),
            RawObservation(
                kind="python.function",
                source_id="src/main/python/app.py#function:8:build",
                path="src/main/python/app.py",
                start_line=8,
                end_line=8,
                name="build",
                target="python.function:app:build",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "async": False, "decorators": []},
            ),
            RawObservation(
                kind="python.method",
                source_id="src/main/python/app.py#method:4:Service.run",
                path="src/main/python/app.py",
                start_line=4,
                end_line=5,
                name="run",
                target="python.method:app:Service:run",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={
                    "module": "app",
                    "class": "Service",
                    "async": False,
                    "decorators": [],
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "file:src/main/python/app.py",
                "python.class:app:Service",
                "python.function:app:build",
                "python.method:app:Service:run",
            ],
        )
        self.assertEqual(
            [(edge["kind"], edge["source_key"], edge["target_key"]) for edge in payload["edges"]],
            [
                ("defines", "file:src/main/python/app.py", "python.class:app:Service"),
                ("defines", "file:src/main/python/app.py", "python.function:app:build"),
                (
                    "defines",
                    "file:src/main/python/app.py",
                    "python.method:app:Service:run",
                ),
            ],
        )

    def test_python_import_creates_module_imports_edge(self):
        observation = RawObservation(
            kind="python.import",
            source_id="src/main/python/repomap_kg/cli.py#import:storage",
            path="src/main/python/repomap_kg/cli.py",
            start_line=4,
            end_line=4,
            name="repomap_kg.storage",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            target="python.module:repomap_kg.storage",
            metadata={
                "module": "repomap_kg.cli",
                "imported_module": "repomap_kg.storage",
                "imported_names": ["storage"],
                "level": 0,
                "resolution": "local",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="python.module:repomap_kg.cli",
            kind="imports",
            target_key="python.module:repomap_kg.storage",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "python.module:repomap_kg.cli",
                "python.module:repomap_kg.storage",
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "python.module:repomap_kg.cli",
                    "kind": "imports",
                    "target_key": "python.module:repomap_kg.storage",
                    "identity_metadata": {},
                    "metadata": {
                        "imported_modules": ["repomap_kg.storage"],
                        "resolutions": ["local"],
                    },
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["summary"]["warnings"], 0)

    def test_python_import_preserves_unknown_target_placeholder(self):
        observation = RawObservation(
            kind="python.import",
            source_id="scratch.py#import:1:relative",
            path="scratch.py",
            start_line=1,
            end_line=1,
            name="relative",
            target="unknown:python.module:missing-package-context",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "scratch",
                "imported_names": ["relative"],
                "level": 1,
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "python.module:scratch",
                "unknown:python.module:missing-package-context",
            ],
        )
        self.assertEqual(payload["edges"][0]["kind"], "imports")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:python.module:missing-package-context",
        )

    def test_python_import_missing_source_module_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="python.import",
            source_id="app.py#import:1:json",
            path="app.py",
            start_line=1,
            end_line=1,
            name="json",
            target="external:python.module:json",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={"imported_module": "json", "resolution": "external"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.module")

    def test_python_import_with_malformed_unknown_target_reports_warning(self):
        observation = RawObservation(
            kind="python.import",
            source_id="scratch.py#import:1:relative",
            path="scratch.py",
            start_line=1,
            end_line=1,
            name="relative",
            target="unknown:python.module:bad%2fescape",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "scratch",
                "imported_names": ["relative"],
                "level": 1,
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "malformed_percent_escape")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:python.module:missing-module",
        )

    def test_python_definition_missing_metadata_is_error(self):
        observations = [
            RawObservation(
                kind="python.class",
                source_id="app.py#class:1:Service",
                path="app.py",
                start_line=1,
                end_line=1,
                name="Service",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
            ),
            RawObservation(
                kind="python.method",
                source_id="app.py#method:2:run",
                path="app.py",
                start_line=2,
                end_line=2,
                name="run",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn("module metadata", payload["diagnostics"][0]["message"])
        self.assertIn("class metadata", payload["diagnostics"][1]["message"])
