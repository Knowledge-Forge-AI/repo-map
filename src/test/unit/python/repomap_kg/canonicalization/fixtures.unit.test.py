import unittest
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import read_observations_jsonl
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import read_observations_jsonl


FIXTURE_ROOT = (
    Path(__file__).parents[4] / "fixtures" / "canonicalization"
)


class CanonicalizationFixtureTests(unittest.TestCase):
    def test_golden_fixtures_match_exact_json(self):
        fixture_names = (
            "files_basic",
            "files_conflict",
            "shell_executes_nix",
            "shell_executes_collapse",
            "shell_source_static",
            "shell_source_dynamic",
            "shell_env_read",
            "shell_env_write",
            "shell_env_write_collapse",
            "shell_host_mutation_package",
            "malformed_target_rebuilt",
            "malformed_target_placeholder",
            "shell_source_repo_escape",
            "shell_env_missing_variable",
            "unsupported_kind",
            "python_package",
            "go_basic",
            "go_duplicate_modules",
            "nix_flake_basic",
            "markdown_docs_basic",
            "config_json_basic",
            "config_toml_basic",
            "config_codex_mcp_dogfood",
            "yaml_basic",
            "js_basic",
            "xml_plist_chrome_policy_basic",
            "xml_java_spring_maven_basic",
            "html_static_basic",
            "css_static_basic",
            "css_html_matching_basic",
            "feed_static_basic",
            "docs_text_table_basic",
            "docs_odf_basic",
            "mail_basic",
        )

        for fixture_name in fixture_names:
            with self.subTest(fixture_name=fixture_name):
                fixture_dir = FIXTURE_ROOT / fixture_name
                observations = read_observations_jsonl(
                    fixture_dir / "raw_observations.jsonl"
                )
                expected = (fixture_dir / "expected_canonical_graph.json").read_text()
                result = canonicalize_observations(
                    observations,
                    repository_scope=f"canonical-{fixture_name}",
                )

                self.assertEqual(result.to_json(), expected)
                if fixture_name == "go_duplicate_modules":
                    self.assertEqual(
                        sum(
                            node.kind == "go.source_function"
                            for node in result.graph.nodes
                        ),
                        2,
                    )
                    self.assertFalse(
                        any(edge.kind == "imports" for edge in result.graph.edges)
                    )


if __name__ == "__main__":
    unittest.main()
