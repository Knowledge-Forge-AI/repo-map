import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations
from repomap_kg.graph.readback.zsh import summarize_zsh_evidence
from repomap_kg.observations import RawObservation
from repomap_kg.storage import prepare_canonical_load

FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "zsh"
FIXTURE_NAMES = (
    "advanced-dynamic.zsh",
    "arrays.zsh",
    "associative-arrays.zsh",
    "autoload-and-fpath.zsh",
    "basic.zsh",
    "commands.zsh",
    "completion/_mytool",
    "dynamic.zsh",
    "false-positives.zsh",
    "functions.zsh",
    "globs-and-expansions.zsh",
    "heredocs.zsh",
    "pipelines-and-redirects.zsh",
    "plugins-and-themes.zsh",
    "redaction.zsh",
    "side-effects.zsh",
    "startup/.zprofile",
    "startup/.zshenv",
    "startup/.zshrc",
    "zstyle-and-completion.zsh",
)

FAKE_SECRET_MARKERS = (
    "FAKE_ZSH_TOKEN_VALUE",
    "FAKE_ZSH_PASSWORD_VALUE",
    "FAKE_ZSH_ZSTYLE_TOKEN",
    "FAKE_ZSH_PROMPT_TOKEN",
    "FAKE_ZSH_ARG_TOKEN",
    "FAKE_ZSH_ARRAY_TOKEN",
    "FAKE_ZSH_PATH_TOKEN",
    "FAKE_ZSH_URL_TOKEN",
)


def fixture_observations(*names: str):
    observations: list[RawObservation] = []
    selected = names or FIXTURE_NAMES
    for name in selected:
        content = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        observations.extend(
            extract_zsh_file_observations(f"fixtures/shell/zsh/{name}", content)
        )
    return tuple(observations)


class ZshCanonicalizationBoundariesUnitTests(unittest.TestCase):
    def test_zsh_fixture_dogfood_summary_is_bounded_and_count_only(self):
        observations = fixture_observations()
        result = canonicalize_observations(observations)

        summary = summarize_zsh_evidence(observations, result)
        payload = summary.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertGreater(payload["raw_observations"], 0)
        self.assertGreater(payload["zsh"]["scripts"], 0)
        self.assertGreater(payload["zsh"]["startup_files"], 0)
        self.assertGreater(payload["zsh"]["options"], 0)
        self.assertGreater(payload["zsh"]["functions"], 0)
        self.assertGreater(payload["zsh"]["assignments"], 0)
        self.assertGreater(payload["zsh"]["exports"], 0)
        self.assertGreater(payload["zsh"]["sources"], 0)
        self.assertGreater(payload["zsh"]["commands"], 0)
        self.assertGreater(payload["zsh"]["external_commands"], 0)
        self.assertGreater(payload["zsh"]["arguments"], 0)
        self.assertGreater(payload["zsh"]["pipelines"], 0)
        self.assertGreater(payload["zsh"]["command_chains"], 0)
        self.assertGreater(payload["zsh"]["redirects"], 0)
        self.assertGreater(payload["zsh"]["heredocs"], 0)
        self.assertGreater(payload["zsh"]["autoloads"], 0)
        self.assertGreater(payload["zsh"]["fpaths"], 0)
        self.assertGreater(payload["zsh"]["zstyles"], 0)
        self.assertGreater(payload["zsh"]["zmodloads"], 0)
        self.assertGreater(payload["zsh"]["bindkeys"], 0)
        self.assertGreater(payload["zsh"]["compinits"], 0)
        self.assertGreater(payload["zsh"]["completion_functions"], 0)
        self.assertGreater(payload["zsh"]["plugin_managers"], 0)
        self.assertGreater(payload["zsh"]["plugins"], 0)
        self.assertGreater(payload["zsh"]["themes"], 0)
        self.assertGreater(payload["zsh"]["prompts"], 0)
        self.assertGreater(payload["zsh"]["array_assignments"], 0)
        self.assertGreater(payload["zsh"]["associative_array_assignments"], 0)
        self.assertGreater(payload["zsh"]["parameter_expansions"], 0)
        self.assertGreater(payload["zsh"]["glob_qualifiers"], 0)
        self.assertGreater(payload["zsh"]["extended_globs"], 0)
        self.assertGreater(payload["zsh"]["path_references"], 0)
        self.assertGreater(payload["zsh"]["dynamic_invocations"], 0)
        self.assertGreater(payload["zsh"]["command_substitutions"], 0)
        self.assertGreater(payload["zsh"]["env_reads"], 0)
        self.assertGreater(payload["zsh"]["env_writes"], 0)
        self.assertGreater(payload["zsh"]["file_reads"], 0)
        self.assertGreater(payload["zsh"]["file_writes"], 0)
        self.assertGreater(payload["zsh"]["network_calls"], 0)
        self.assertGreater(payload["zsh"]["package_managers"], 0)
        self.assertGreater(payload["zsh"]["host_mutations"], 0)
        self.assertGreater(payload["zsh"]["secret_like_redacted"], 0)
        self.assertGreater(payload["canonical"]["nodes"], 0)
        self.assertGreater(payload["canonical"]["edges"], 0)
        self.assertIn("zsh.script", payload["canonical"]["node_kinds"])
        self.assertIn("command_intent", payload["canonical"]["edge_kinds"])
        self.assertEqual(
            payload["safety"],
            {
                "bounded": True,
                "raw_payloads_included": False,
                "source_snippets_included": False,
                "command_strings_included": False,
                "prompt_strings_included": False,
                "secret_values_included": False,
                "path_examples_included": False,
                "zsh_executed": False,
                "shell_executed": False,
                "startup_executed": False,
                "commands_executed": False,
                "plugins_loaded": False,
                "plugin_managers_executed": False,
                "completions_loaded": False,
                "modules_loaded": False,
                "globs_expanded": False,
                "parameters_expanded": False,
                "files_opened": False,
                "filesystem_checked": False,
                "host_mutation_proven": False,
                "live_graph_refreshed": False,
            },
        )
        self.assertNotIn("fixtures/shell/zsh/basic.zsh", serialized)
        self.assertNotIn("https://example.invalid/install.zsh", serialized)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_zsh_fixture_dogfood_prepares_existing_storage_rows(self):
        observations = fixture_observations(
            "basic.zsh",
            "commands.zsh",
            "plugins-and-themes.zsh",
            "zstyle-and-completion.zsh",
            "side-effects.zsh",
            "redaction.zsh",
        )

        prepared = prepare_canonical_load(observations)
        serialized = json.dumps(
            {
                "raw": [row.payload_json for row in prepared.raw_rows],
                "nodes": [row.metadata_json for row in prepared.canonical_rows.nodes],
                "edges": [row.metadata_json for row in prepared.canonical_rows.edges],
                "evidence": [
                    row.metadata_json for row in prepared.canonical_rows.evidence
                ],
            },
            sort_keys=True,
        )

        self.assertTrue(prepared.result.ok)
        self.assertGreater(len(prepared.raw_rows), 0)
        self.assertGreater(len(prepared.canonical_rows.nodes), 0)
        self.assertGreater(len(prepared.canonical_rows.edges), 0)
        self.assertIn(
            "zsh.script",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        self.assertIn(
            "zsh.function",
            {row.kind for row in prepared.canonical_rows.nodes},
        )
        edge_kinds = {row.edge_kind for row in prepared.canonical_rows.edges}
        self.assertIn("command_intent", edge_kinds)
        self.assertIn("uses_plugin", edge_kinds)
        self.assertIn("uses_zsh_module", edge_kinds)
        self.assertIn("host_mutation_intent", edge_kinds)
        self.assertNotIn("executes", edge_kinds)
        self.assertNotIn("mutates_host", edge_kinds)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)

    def test_zsh_canonicalization_dogfood_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = fixture_observations()
            result = canonicalize_observations(observations)
            summary = summarize_zsh_evidence(observations, result)

        self.assertTrue(result.ok)
        self.assertGreater(summary.to_dict()["canonical"]["nodes"], 0)


if __name__ == "__main__":
    unittest.main()
