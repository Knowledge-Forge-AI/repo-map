import json
import unittest
from pathlib import Path

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.keys import (
    env_key,
    external_key,
    file_key,
    host_category_key,
    tool_key,
    zsh_function_key,
    zsh_script_key,
)
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations
from repomap_kg.observations import RawObservation


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


def edge_pairs(payload):
    return {
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    }


class ZshCanonicalizationUnitTests(unittest.TestCase):
    def test_zsh_fixture_observations_create_selected_canonical_graph_evidence(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )

        basic_script = zsh_script_key("fixtures/shell/zsh/basic.zsh")
        commands_script = zsh_script_key("fixtures/shell/zsh/commands.zsh")
        plugins_script = zsh_script_key("fixtures/shell/zsh/plugins-and-themes.zsh")
        zstyle_script = zsh_script_key(
            "fixtures/shell/zsh/zstyle-and-completion.zsh"
        )
        completion_script = zsh_script_key("fixtures/shell/zsh/completion/_mytool")
        side_effect_script = zsh_script_key("fixtures/shell/zsh/side-effects.zsh")
        mkcd_function = zsh_function_key("fixtures/shell/zsh/basic.zsh", "mkcd")

        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn(basic_script, node_keys)
        self.assertIn(mkcd_function, node_keys)
        self.assertIn(tool_key("git"), node_keys)
        self.assertIn(env_key("PATH"), node_keys)
        self.assertIn(host_category_key("file-write"), node_keys)
        self.assertIn(external_key("zsh.plugin_manager", "oh_my_zsh"), node_keys)
        self.assertIn(external_key("zsh.plugin", "oh_my_zsh:git"), node_keys)
        self.assertIn(external_key("zsh.module", "zsh/complist"), node_keys)
        self.assertIn(external_key("zsh.completion", "mytool"), node_keys)
        self.assertIn(
            file_key("fixtures/shell/zsh/lib/example.zsh"),
            node_keys,
        )
        self.assertIn(
            file_key("fixtures/shell/zsh/data/input.txt"),
            node_keys,
        )
        self.assertIn(
            file_key("fixtures/shell/zsh/out/report.txt"),
            node_keys,
        )
        self.assertIn(
            external_key(
                "zsh.network_intent",
                "curl:https://example.invalid/install.zsh",
            ),
            node_keys,
        )
        self.assertIn(external_key("zsh.package_manager", "brew"), node_keys)

        pairs = edge_pairs(payload)
        self.assertIn(
            (
                file_key("fixtures/shell/zsh/basic.zsh"),
                "defines",
                basic_script,
            ),
            pairs,
        )
        self.assertIn((basic_script, "defines", mkcd_function), pairs)
        self.assertIn(
            (
                basic_script,
                "includes",
                file_key("fixtures/shell/zsh/lib/example.zsh"),
            ),
            pairs,
        )
        self.assertIn((commands_script, "command_intent", tool_key("git")), pairs)
        self.assertIn(
            (
                plugins_script,
                "uses_plugin_manager",
                external_key("zsh.plugin_manager", "oh_my_zsh"),
            ),
            pairs,
        )
        self.assertIn(
            (
                plugins_script,
                "uses_plugin",
                external_key("zsh.plugin", "oh_my_zsh:git"),
            ),
            pairs,
        )
        self.assertIn(
            (
                zstyle_script,
                "uses_zsh_module",
                external_key("zsh.module", "zsh/complist"),
            ),
            pairs,
        )
        self.assertIn(
            (
                completion_script,
                "completion_for",
                external_key("zsh.completion", "mytool"),
            ),
            pairs,
        )
        self.assertIn((side_effect_script, "reads_env", env_key("PATH")), pairs)
        self.assertIn((side_effect_script, "writes_env", env_key("PATH")), pairs)
        self.assertIn(
            (
                side_effect_script,
                "reads",
                file_key("fixtures/shell/zsh/data/input.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                side_effect_script,
                "writes",
                file_key("fixtures/shell/zsh/out/report.txt"),
            ),
            pairs,
        )
        self.assertIn(
            (
                side_effect_script,
                "network_intent",
                external_key(
                    "zsh.network_intent",
                    "curl:https://example.invalid/install.zsh",
                ),
            ),
            pairs,
        )
        self.assertIn(
            (
                side_effect_script,
                "package_intent",
                external_key("zsh.package_manager", "brew"),
            ),
            pairs,
        )
        self.assertIn(
            (
                side_effect_script,
                "host_mutation_intent",
                host_category_key("file-write"),
            ),
            pairs,
        )

        edge_payloads = {
            (edge["source_key"], edge["kind"], edge["target_key"]): edge
            for edge in payload["edges"]
        }
        command_edge = edge_payloads[(commands_script, "command_intent", tool_key("git"))]
        self.assertFalse(command_edge["metadata"]["command_executed"])
        self.assertFalse(command_edge["metadata"]["shell_executed"])
        self.assertFalse(command_edge["metadata"]["zsh_executed"])
        source_edge = edge_payloads[
            (
                basic_script,
                "includes",
                file_key("fixtures/shell/zsh/lib/example.zsh"),
            )
        ]
        self.assertFalse(source_edge["metadata"]["source_executed"])
        self.assertFalse(source_edge["metadata"]["file_read"])
        plugin_edge = edge_payloads[
            (
                plugins_script,
                "uses_plugin",
                external_key("zsh.plugin", "oh_my_zsh:git"),
            )
        ]
        self.assertFalse(plugin_edge["metadata"]["plugin_loaded"])
        self.assertFalse(plugin_edge["metadata"]["plugin_installed"])
        self.assertFalse(plugin_edge["metadata"]["network_called"])
        host_edge = edge_payloads[
            (
                side_effect_script,
                "host_mutation_intent",
                host_category_key("file-write"),
            )
        ]
        self.assertFalse(host_edge["metadata"]["host_mutation_proven"])
        self.assertNotIn("executes", {edge["kind"] for edge in payload["edges"]})
        self.assertNotIn("mutates_host", {edge["kind"] for edge in payload["edges"]})

    def test_dynamic_and_raw_only_zsh_observations_remain_bounded(self):
        observations = fixture_observations()

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.ok)
        self.assertNotIn("tool:%24cmd", serialized)
        self.assertNotIn("file:%5Bdynamic%5D", serialized)
        self.assertNotIn("external:zsh.plugin:%5Bdynamic%5D", serialized)
        self.assertEqual(
            [
                diagnostic
                for diagnostic in payload["diagnostics"]
                if diagnostic["category"] == "unsupported_raw_observation_kind"
            ],
            [],
        )

        raw_evidence_kinds = {evidence["raw_kind"] for evidence in payload["evidence"]}
        self.assertTrue(
            {
                "zsh.option",
                "zsh.fpath",
                "zsh.zstyle",
                "zsh.bindkey",
                "zsh.compinit",
                "zsh.array_assignment",
                "zsh.associative_array_assignment",
                "zsh.parameter_expansion",
                "zsh.glob_qualifier",
                "zsh.extended_glob",
                "zsh.path_reference",
                "zsh.dynamic_invocation",
                "zsh.prompt",
                "shell.assignment",
                "shell.export",
                "shell.command_argument",
                "shell.pipeline",
                "shell.command_chain",
                "shell.redirect",
                "shell.heredoc",
                "shell.command_substitution",
                "shell.dynamic_invocation",
                "shell.secret_like",
            }.issubset(raw_evidence_kinds)
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
