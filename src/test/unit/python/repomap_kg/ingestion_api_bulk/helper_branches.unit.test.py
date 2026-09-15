import ast
import importlib.util
from types import ModuleType
from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.policy_helper_branches import (
    load_unit_contract_class,
    raw_observation,
    write_api_fixture,
)

from repomap_kg.ops.ingestion import api
from repomap_kg.ops.ingestion import bulk
from repomap_kg.ops import config as ops_config
from repomap_kg.extractors.languages import python as python_extractor

FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "support" / "python" / "repomap_test_support" / "contract_loader_fixtures"


def _load_contract_module(name: str, path: Path) -> ModuleType:
    """Exercise real file loading only at the loader-control test boundary."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load unit contract module {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApiBulkPythonOpsConfigHelperBranchUnitTests(unittest.TestCase):
    def test_observation_leaf_preserves_facade_identity_and_loader_resolution(self):
        from repomap_test_support import policy_helper_branches, policy_observations
        self.assertIs(raw_observation, policy_observations.raw_observation)
        nested_root = FIXTURE_ROOT / "nested"
        with patch.object(policy_helper_branches, "UNIT_REPOMAP_TEST_ROOT", nested_root):
            selected = load_unit_contract_class("probe.py", "Selected", load_module=_load_contract_module)
            self.assertEqual(getattr(selected, "marker"), 17)
            self.assertEqual(selected.__module__, "repomap_helper_contract_Selected")
            with self.assertRaises(AttributeError):
                load_unit_contract_class("probe.py", "Missing", load_module=_load_contract_module)
            with self.assertRaisesRegex(RuntimeError, "found 0"):
                load_unit_contract_class("absent.py", "Selected", load_module=_load_contract_module)
        with patch.object(policy_helper_branches, "UNIT_REPOMAP_TEST_ROOT", FIXTURE_ROOT):
            with self.assertRaisesRegex(RuntimeError, "found 2"):
                load_unit_contract_class("probe.py", "Selected", load_module=_load_contract_module)

    def test_contract_loader_accepts_caller_binding_and_resolves_paths_before_loading(self):
        from repomap_test_support import policy_helper_branches

        class ArbitraryOwner:
            pass

        calls: list[tuple[str, Path]] = []

        def bind(name: str, path: Path) -> ModuleType:
            calls.append((name, path))
            module = ModuleType(name)
            setattr(module, "ArbitraryOwner", ArbitraryOwner)
            return module

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(policy_helper_branches, "UNIT_REPOMAP_TEST_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "found 0"):
                    load_unit_contract_class("owner.py", "ArbitraryOwner", load_module=bind)
                self.assertEqual(calls, [])
                (root / "nested").mkdir()
                path = root / "nested" / "owner.py"
                path.write_text("# caller-owned fixture\n", encoding="utf-8")
                selected = load_unit_contract_class("owner.py", "ArbitraryOwner", load_module=bind)
                self.assertIs(selected, ArbitraryOwner)
                self.assertEqual(calls, [("repomap_helper_contract_ArbitraryOwner", path)])

    def test_api_bulk_python_and_ops_config_helpers_cover_small_branch_matrices(self):
        literal_cases = (
            (None, "null"),
            (True, "boolean"),
            (7, "number"),
            (1.5, "number"),
            ("value", "string"),
            (["value"], "array"),
            ({"value": 1}, "object"),
            (object(), "unknown"),
        )
        for value, value_type in literal_cases:
            with self.subTest(value=repr(value)):
                self.assertEqual(api.literal_type(value), value_type)

        expression_cases = {
            None: "unknown",
            '"literal"': "literal_string",
            "False": "literal_bool",
            "7": "literal_number",
            "None": "literal_null",
            "[1, 2]": "collection_shape",
            "(1, 2)": "collection_shape",
            "{1, 2}": "collection_shape",
            '{"a": 1}': "collection_shape",
            "call()": "function_call",
            "name": "traversal_reference",
            "obj.attr": "traversal_reference",
            "left + right": "dynamic_expression",
            "lambda x: x": "unknown",
        }
        for expression, expression_kind in expression_cases.items():
            with self.subTest(expression=expression):
                node = (
                    None
                    if expression is None
                    else ast.parse(expression, mode="eval").body
                )
                self.assertEqual(
                    python_extractor._expression_kind(node),
                    expression_kind,
                )

        graph_status_cases = (
            (None, "unchecked"),
            ({"error": "psql failed"}, "error"),
            ({"schema_available": False}, "schema-missing"),
            (
                {
                    "schema_available": True,
                    "repository_exists": True,
                    "raw_observations": 3,
                    "canonical_nodes": 2,
                    "canonical_edges": 1,
                },
                "ready(raw_total=3,raw_latest=0,nodes=2,edges=1)",
            ),
            ({"schema_available": True, "repository_exists": False}, "missing"),
        )
        for status, label in graph_status_cases:
            with self.subTest(status=status):
                self.assertEqual(ops_config.graph_storage_label(status), label)

        sentinel = (
            raw_observation(
                "file",
                path="fixture.txt",
                metadata={"language": "text"},
            ),
        )
        extractor_names = (
            "extract_markdown_file_observations_from_file",
            "extract_shell_file_observations",
            "extract_python_file_observations_from_file",
            "extract_ruby_file_observations_from_file",
            "extract_javascript_file_observations_from_file",
            "extract_eml_file_observations_from_file",
            "extract_mbox_file_observations_from_file",
            "extract_nix_file_observations_from_file",
            "extract_feed_file_observations_from_file",
            "extract_config_file_observations_from_file",
            "extract_html_file_observations_from_file",
            "extract_css_file_observations_from_file",
            "extract_document_file_observations_from_file",
        )
        route_cases = {
            "markdown": "extract_markdown_file_observations_from_file",
            "shell": "extract_shell_file_observations",
            "python": "extract_python_file_observations_from_file",
            "ruby": "extract_ruby_file_observations_from_file",
            "javascript": "extract_javascript_file_observations_from_file",
            "eml": "extract_eml_file_observations_from_file",
            "mbox": "extract_mbox_file_observations_from_file",
            "nix": "extract_nix_file_observations_from_file",
            "html": "extract_html_file_observations_from_file",
            "css": "extract_css_file_observations_from_file",
            "text": "extract_document_file_observations_from_file",
            "csv": "extract_document_file_observations_from_file",
            "tsv": "extract_document_file_observations_from_file",
            "latex": "extract_document_file_observations_from_file",
            "odf": "extract_document_file_observations_from_file",
        }

        def file_info(language: str) -> bulk.FileInfo:
            return bulk.FileInfo(
                path=f"fixture.{language}",
                language=language,
                role="source",
                content_hash="0" * 64,
                executable=False,
                generated=False,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            with ExitStack() as stack:
                mocks = {
                    name: stack.enter_context(patch.object(bulk, name, return_value=sentinel))
                    for name in extractor_names
                }
                for language, expected_extractor in route_cases.items():
                    with self.subTest(language=language):
                        self.assertEqual(
                            bulk.observations_for_file_info(
                                repo_root,
                                file_info(language),
                                module_index=bulk.PythonModuleIndex.empty(),
                                repository_paths=frozenset({"README.md"}),
                                markdown_anchors={},
                            ),
                            sentinel,
                        )
                        self.assertTrue(mocks[expected_extractor].called)

                mocks["extract_feed_file_observations_from_file"].reset_mock(
                    return_value=True,
                )
                mocks["extract_config_file_observations_from_file"].reset_mock(
                    return_value=True,
                )
                mocks["extract_feed_file_observations_from_file"].return_value = sentinel
                self.assertEqual(
                    bulk.observations_for_file_info(
                        repo_root,
                        file_info("json"),
                        module_index=bulk.PythonModuleIndex.empty(),
                        repository_paths=frozenset(),
                        markdown_anchors={},
                    ),
                    sentinel,
                )
                mocks["extract_config_file_observations_from_file"].assert_not_called()

                mocks["extract_feed_file_observations_from_file"].return_value = ()
                mocks["extract_config_file_observations_from_file"].return_value = sentinel
                self.assertEqual(
                    bulk.observations_for_file_info(
                        repo_root,
                        file_info("yaml"),
                        module_index=bulk.PythonModuleIndex.empty(),
                        repository_paths=frozenset(),
                        markdown_anchors={},
                    ),
                    sentinel,
                )
                self.assertEqual(
                    bulk.observations_for_file_info(
                        repo_root,
                        file_info("binary"),
                        module_index=bulk.PythonModuleIndex.empty(),
                        repository_paths=frozenset(),
                        markdown_anchors={},
                    ),
                    (),
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid_path = write_api_fixture(root)
            valid_text = valid_path.read_text(encoding="utf-8")
            self.assertEqual(api.load_api_source_config(valid_path).source_id, "fixture-readonly-api")

            invalid_cases = {
                "unsupported source_type": valid_text.replace(
                    'source_type = "api.rest"',
                    'source_type = "api.write"',
                ),
                "read_only must be true": valid_text.replace(
                    "read_only = true",
                    "read_only = false",
                ),
                "mutation_allowed must be false": valid_text.replace(
                    "mutation_allowed = false",
                    "mutation_allowed = true",
                    1,
                ),
                "consent is revoked": valid_text.replace(
                    "revoked = false",
                    "revoked = true",
                ),
                "consent mutation_allowed must be false": valid_text.replace(
                    "[consent]\n"
                    'consent_ref = "local_consent_ref:fixture-readonly-api-2026-07"\n'
                    'scope_description = "Read-only fixture API metadata export"\n'
                    'authorized_operations = ["read"]\n'
                    'authorized_data_classes = ["metadata"]\n'
                    "revoked = false\n"
                    "mutation_allowed = false\n",
                    "[consent]\n"
                    'consent_ref = "local_consent_ref:fixture-readonly-api-2026-07"\n'
                    'scope_description = "Read-only fixture API metadata export"\n'
                    'authorized_operations = ["read"]\n'
                    'authorized_data_classes = ["metadata"]\n'
                    "revoked = false\n"
                    "mutation_allowed = true\n",
                ),
                "authorized_operations must be read-only": valid_text.replace(
                    'authorized_operations = ["read"]',
                    'authorized_operations = ["read", "write"]',
                ),
                "authorized_data_classes is required": valid_text.replace(
                    'authorized_data_classes = ["metadata"]',
                    'authorized_data_classes = []',
                ),
                "max_concurrent_requests must be 1": valid_text.replace(
                    "max_concurrent_requests = 1",
                    "max_concurrent_requests = 2",
                ),
            }
            for expected_message, content in invalid_cases.items():
                with self.subTest(expected_message=expected_message):
                    invalid_path = root / f"{expected_message.split()[0]}.toml"
                    invalid_path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(api.ApiPolicyError, expected_message):
                        api.load_api_source_config(invalid_path)
