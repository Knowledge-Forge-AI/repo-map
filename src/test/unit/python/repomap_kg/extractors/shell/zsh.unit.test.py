import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.ingestion.bulk import classify_bulk_route
from repomap_kg.graph.discovery import classify_path, discover_observations
from repomap_kg.ops.ingestion.source import _archive_extractor_route
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations
from repomap_kg.observations.raw import RawObservation


FIXTURE_ROOT = Path(__file__).parents[5] / "fixtures" / "shell" / "zsh"
FAKE_SECRET_MARKERS = (
    "FAKE_ZSH_TOKEN_VALUE", "FAKE_ZSH_PASSWORD_VALUE", "FAKE_ZSH_ZSTYLE_TOKEN",
    "FAKE_ZSH_PROMPT_TOKEN", "FAKE_ZSH_ARG_TOKEN", "FAKE_ZSH_ARRAY_TOKEN",
    "FAKE_ZSH_PATH_TOKEN", "FAKE_ZSH_URL_TOKEN",
)


def observations_by_kind(observations: list[RawObservation] | tuple[RawObservation, ...]) -> dict[str, list[RawObservation]]:
    kinds = dict.fromkeys(observation.kind for observation in observations)
    return {kind: [item for item in observations if item.kind == kind] for kind in kinds}


def first_observation(observations, *, kind, name=None, predicate=None):
    for observation in observations:
        if observation.kind != kind:
            continue
        if name is not None and observation.name != name:
            continue
        if predicate is not None and not predicate(observation):
            continue
        return observation
    raise AssertionError(f"missing observation kind={kind!r} name={name!r}")


class ZshExtractorUnitTests(unittest.TestCase):
    def _extract_fixture(self, path: str, fixture_name: str | None = None) -> list[RawObservation]:
        rel = fixture_name or path
        content = (FIXTURE_ROOT / rel).read_text(encoding="utf-8")
        return list(extract_zsh_file_observations(path, content))

    def test_classifies_zsh_files_shebang_startup_and_completion_boundaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            files = {
                "scripts/basic.zsh": "# static fixture\n", "bin/ztool": "#!/usr/bin/env zsh\n",
                "scripts/explicit.sh": "#!/bin/zsh\n", "config/.zshrc": "# static fixture\n",
                "zsh/completions/_mytool": "#compdef mytool\n", "scripts/inline.sh": "#!/bin/sh\nzsh -c 'print ok'\n",
                "scripts/plain.sh": "#!/bin/sh\nset -e\n", "scripts/other.bash": "#!/usr/bin/env bash\n",
                "test/case.bats": "#!/usr/bin/env bats\n", "filters/report.awk": "# awk fixture\n",
                "scripts/script.ps1": "Write-Output ok\n", "misc/_not_completion": "# underscore only\n",
            }
            for rel, text in files.items():
                self.write(root / rel, text)
            os.chmod(root / "bin" / "ztool", 0o755)
            infos = {rel: classify_path(root, root / rel) for rel in files}

        expected = {
            "scripts/basic.zsh": ("zsh", "source"), "bin/ztool": ("zsh", "entrypoint"),
            "scripts/explicit.sh": ("zsh", None), "config/.zshrc": ("zsh", "config"),
            "zsh/completions/_mytool": ("zsh", "source"), "scripts/inline.sh": ("shell", None),
            "scripts/plain.sh": ("shell", None), "scripts/other.bash": ("bash", None),
            "test/case.bats": ("bats", None), "filters/report.awk": ("awk", None),
            "scripts/script.ps1": ("powershell", None),
        }
        for rel, (lang, role) in expected.items():
            self.assertEqual(infos[rel].language, lang)
            if role is not None:
                self.assertEqual(infos[rel].role, role)
        self.assertNotEqual(infos["misc/_not_completion"].language, "zsh")

    def test_zsh_script_options_functions_assignments_exports_and_sources(self):
        observations = self._extract_fixture("scripts/basic.zsh", "basic.zsh")
        by_kind = observations_by_kind(observations)
        script = by_kind["zsh.script"][0]
        for k, v in [
            ("language", "zsh"), ("dialect", "zsh"), ("file_type", "script"),
            ("shebang", "#!/usr/bin/env zsh"), ("classification_evidence", ["extension", "shebang"]),
            ("parser", "stdlib-static-scanner"), ("static_only", True), ("shell_executed", False),
            ("zsh_executed", False), ("startup_executed", False), ("plugins_loaded", False),
        ]:
            self.assertEqual(script.metadata[k], v)

        options = {(item.metadata["source_form"], item.name, item.metadata["operation"]) for item in by_kind["zsh.option"]}
        for opt in (("setopt", "extendedglob", "set"), ("setopt", "nullglob", "set"), ("setopt", "prompt_subst", "set"),
                    ("unsetopt", "beep", "unset"), ("unsetopt", "nomatch", "unset")):
            self.assertIn(opt, options)
        emulate = first_observation(by_kind["zsh.option"], kind="zsh.option", name="zsh")
        self.assertEqual((emulate.metadata["operation"], emulate.metadata["option_scope"]), ("emulate", "function_local"))
        self.assertFalse(emulate.metadata["runtime_option_state_known"])

        functions = {item.name: item.metadata for item in by_kind["shell.function"]}
        self.assertEqual(functions["mkcd"]["syntax"], "name_parens")
        self.assertEqual(functions["greet"]["syntax"], "function_keyword")
        self.assertFalse(functions["mkcd"]["body_modeled"])

        exports = {item.name: item.metadata for item in by_kind["shell.export"]}
        self.assertEqual((exports["EXAMPLE_MODE"]["operation"], exports["EXAMPLE_MODE"]["value_kind"], exports["EXAMPLE_MODE"]["value"]), ("export", "static", "public"))

        assignments = {item.name: item.metadata for item in by_kind["shell.assignment"]}
        self.assertEqual((assignments["EXAMPLE_VALUE"]["operation"], assignments["EXAMPLE_VALUE"]["value_kind"], assignments["EXAMPLE_VALUE"]["value"]), ("assign", "static", "safe"))

        source = by_kind["shell.source"][0]
        self.assertEqual((source.metadata["dialect"], source.metadata["syntax"], source.metadata["target_kind"]), ("zsh", "source", "static"))
        self.assertEqual(source.metadata["resolved_path"], "scripts/lib/example.zsh")
        self.assertEqual(source.target, "file:scripts/lib/example.zsh")
        self.assertFalse(source.metadata["source_executed"] or source.metadata["file_read"])

    def test_startup_files_are_marked_without_runtime_state_claims(self):
        observations = self._extract_fixture("startup/.zshrc")
        by_kind = observations_by_kind(observations)
        script, startup = by_kind["zsh.script"][0], by_kind["zsh.startup_file"][0]
        self.assertEqual(script.metadata["file_type"], "startup")
        self.assertIn("startup_filename", script.metadata["classification_evidence"])
        self.assertEqual((startup.metadata["startup_file_kind"], startup.metadata["startup_order"]), ("zshrc", "interactive"))
        self.assertFalse(startup.metadata["startup_executed"] or startup.metadata["profile_loaded"])
        assignments = {item.name: item.metadata for item in by_kind["shell.assignment"]}
        self.assertEqual((assignments["path"]["value_kind"], assignments["path"]["operation"]), ("array", "prepend"))
        self.assertEqual(assignments["fpath"]["value_kind"], "array")
        fpath = by_kind["zsh.fpath"][0]
        self.assertEqual(fpath.metadata["operation"], "prepend")
        self.assertFalse(fpath.metadata["filesystem_checked"] or fpath.metadata["fpath_runtime_state_known"])

    def test_hook_functions_use_bounded_zsh_metadata(self):
        observations = self._extract_fixture("functions.zsh")
        functions = {item.name: item.metadata for item in observations if item.kind == "shell.function"}
        self.assertEqual(functions["precmd"]["zsh_function_kind"], "hook")
        self.assertEqual(functions["chpwd"]["zsh_function_kind"], "hook")
        self.assertFalse(functions["precmd"]["body_modeled"])

    def test_dynamic_source_autoload_eval_and_command_substitution_are_bounded(self):
        observations = self._extract_fixture("dynamic.zsh")
        by_kind = observations_by_kind(observations)
        dynamic_reasons = {item.metadata["dynamic_reason"] for item in by_kind["shell.dynamic_invocation"]}
        self.assertTrue({"eval", "computed_source", "computed_autoload", "plugin_manager_eval", "array_command"}.issubset(dynamic_reasons))
        source = first_observation(by_kind["shell.source"], kind="shell.source", predicate=lambda item: item.metadata["target_kind"] == "dynamic")
        self.assertEqual((source.metadata["target_display"], source.metadata["dynamic_reason"]), ("[dynamic]", "computed_source"))
        self.assertIsNone(source.target)
        sub = by_kind["shell.command_substitution"][0]
        self.assertFalse(sub.metadata["inner_modeled"] or sub.metadata["command_executed"] or sub.metadata["shell_executed"] or sub.metadata["zsh_executed"])
        self.assertEqual(by_kind["zsh.zstyle"][0].metadata["value_kind"], "dynamic")
        prompt = by_kind["zsh.prompt"][0]
        self.assertFalse(prompt.metadata["prompt_applied"] or prompt.metadata["raw_value_stored"])

    def test_commands_arguments_wrappers_and_external_commands_are_static_evidence(self):
        observations = self._extract_fixture("commands.zsh")
        by_kind = observations_by_kind(observations)
        commands = [item.name for item in by_kind["shell.command"]]
        for cmd in ("print", "git", "noglob"):
            self.assertIn(cmd, commands)
        wrapper = first_observation(by_kind["shell.command"], kind="shell.command", name="command")
        self.assertEqual((wrapper.metadata["command_family"], wrapper.metadata["wrapped_command"]), ("wrapper", "git"))
        git_external = first_observation(by_kind["shell.external_command"], kind="shell.external_command", name="git")
        self.assertEqual(git_external.target, "tool:git")
        self.assertFalse(git_external.metadata["command_executed"])

        arguments = by_kind["shell.command_argument"]
        arg_kinds = {item.metadata["argument_kind"] for item in arguments}
        for ak in ("long_flag", "short_flag", "positional"):
            self.assertIn(ak, arg_kinds)
        redacted = first_observation(arguments, kind="shell.command_argument", predicate=lambda item: item.metadata["argument_kind"] == "redacted")
        self.assertEqual(redacted.metadata["argument_display"], "[redacted]")
        self.assertFalse(redacted.metadata["raw_value_stored"])
        for kind in ("shell.host_mutation", "shell.network_call", "shell.package_manager"):
            self.assertNotIn(kind, by_kind)

    def test_pipelines_chains_redirects_and_heredocs_are_bounded_syntax(self):
        observations = list(self._extract_fixture("pipelines-and-redirects.zsh"))
        observations.extend(self._extract_fixture("heredocs.zsh"))
        by_kind = observations_by_kind(observations)
        pipeline = by_kind["shell.pipeline"][0]
        self.assertEqual((pipeline.metadata["segment_count"], pipeline.metadata["operators"]), (2, ["|"]))
        self.assertFalse(pipeline.metadata["object_or_byte_flow_modeled"])
        chain_ops = [item.metadata["operators"][0] for item in by_kind["shell.command_chain"]]
        self.assertTrue("&&" in chain_ops and "||" in chain_ops)
        redirect_modes = {item.metadata["redirect_operator"]: item.metadata["mode"] for item in by_kind["shell.redirect"]}
        expected_modes = {">": "truncate", ">>": "append", "<": "read", "2>": "truncate", "&>": "combined_output", "2>&1": "duplicate", "<<<": "here_string"}
        for op, mode in expected_modes.items():
            self.assertEqual(redirect_modes[op], mode)
        heredoc = by_kind["shell.heredoc"][0]
        self.assertFalse(heredoc.metadata["raw_body_stored"])
        self.assertEqual(heredoc.metadata["body_line_count"], 2)
        self.assertNotIn("hidden_function", json.dumps([item.to_dict() for item in observations]))
        self.assertNotIn("zsh.plugin", {item.kind for item in observations if item.path == "heredocs.zsh"})

    def test_autoload_fpath_and_compinit_are_configuration_intent_only(self):
        observations = self._extract_fixture("autoload-and-fpath.zsh")
        by_kind = observations_by_kind(observations)
        fpath = first_observation(by_kind["zsh.fpath"], kind="zsh.fpath", name="fpath")
        self.assertEqual((fpath.metadata["operation"], fpath.metadata["path_count"], fpath.metadata["static_path_count"], fpath.metadata["dynamic_path_count"]), ("prepend", 3, 1, 2))
        self.assertFalse(fpath.metadata["filesystem_checked"])
        static_auto = first_observation(by_kind["zsh.autoload"], kind="zsh.autoload", predicate=lambda it: it.metadata["target_kind"] == "static")
        self.assertEqual((static_auto.metadata["function_names"], static_auto.metadata["flags"]), (["compinit", "promptinit"], ["-Uz"]))
        self.assertFalse(static_auto.metadata["autoload_executed"])
        dyn_auto = first_observation(by_kind["zsh.autoload"], kind="zsh.autoload", predicate=lambda it: it.metadata["target_kind"] == "dynamic")
        self.assertEqual(dyn_auto.metadata["dynamic_reason"], "computed_autoload")
        compinit = by_kind["zsh.compinit"][0]
        self.assertFalse(compinit.metadata["compinit_executed"] or compinit.metadata["completion_system_initialized"])

    def test_zstyle_zmodload_bindkey_and_completion_observations_do_not_apply_state(self):
        observations = list(self._extract_fixture("zstyle-and-completion.zsh"))
        observations.extend(self._extract_fixture("zsh/completions/_mytool", "completion/_mytool"))
        by_kind = observations_by_kind(observations)
        zstyle = first_observation(by_kind["zsh.zstyle"], kind="zsh.zstyle", name="menu")
        self.assertEqual((zstyle.metadata["context_pattern"], zstyle.metadata["value_kind"]), (":completion:*", "static"))
        self.assertFalse(zstyle.metadata["zstyle_applied"])
        zmod_operations = {item.metadata["operation"] for item in by_kind["zsh.zmodload"]}
        self.assertEqual(zmod_operations, {"load", "unload"})
        self.assertTrue(all(not item.metadata["module_loaded"] for item in by_kind["zsh.zmodload"]))
        self.assertIn("emacs", {item.metadata["keymap_mode"] for item in by_kind["zsh.bindkey"]})
        self.assertTrue(all(not item.metadata["binding_applied"] for item in by_kind["zsh.bindkey"]))
        completion = first_observation(by_kind["zsh.completion_function"], kind="zsh.completion_function", name="mytool")
        self.assertEqual(completion.metadata["compdef_target"], "mytool")
        self.assertTrue(completion.metadata["uses_arguments"])
        self.assertFalse(completion.metadata["completion_loaded"])

    def test_plugins_themes_and_prompts_are_configuration_intent_only(self):
        observations = self._extract_fixture("plugins-and-themes.zsh")
        by_kind = observations_by_kind(observations)
        managers = {item.metadata["manager"] for item in by_kind["zsh.plugin_manager"]}
        self.assertTrue({"oh_my_zsh", "zinit", "antigen", "zplug", "antidote", "sheldon"}.issubset(managers))
        plugins = {item.metadata["plugin_name"] for item in by_kind["zsh.plugin"]}
        self.assertTrue({"git", "docker", "kubectl", "zsh-users/zsh-autosuggestions"}.issubset(plugins))
        theme = by_kind["zsh.theme"][0]
        self.assertEqual(theme.metadata["theme_name"], "example-theme")
        self.assertFalse(theme.metadata["theme_loaded"])
        for item in by_kind["zsh.plugin_manager"] + by_kind["zsh.plugin"]:
            self.assertFalse(item.metadata["plugin_loaded"] or item.metadata["plugin_installed"] or item.metadata["network_called"])
        dynamic_reasons = {item.metadata["dynamic_reason"] for item in by_kind["shell.dynamic_invocation"]}
        self.assertIn("plugin_manager_eval", dynamic_reasons)
        for kind in ("shell.host_mutation", "shell.network_call", "shell.package_manager"):
            self.assertNotIn(kind, by_kind)

    def test_arrays_and_associative_arrays_are_bounded_syntax(self):
        observations = list(self._extract_fixture("arrays.zsh"))
        observations.extend(self._extract_fixture("associative-arrays.zsh"))
        by_kind = observations_by_kind(observations)
        arrays = {item.name: item.metadata for item in by_kind["zsh.array_assignment"]}
        self.assertEqual((arrays["tools"]["element_count"], arrays["path"]["operation"], arrays["path"]["dynamic_element_count"]), (3, "prepend", 1))
        self.assertEqual(arrays["names"]["declaration_keyword"], "local")
        self.assertIn("-a", arrays["colors"]["flags"])
        for m in arrays.values():
            self.assertTrue(m["syntax_only"])
            self.assertFalse(m["array_expanded"] or m["runtime_state_known"] or m["command_executed"])

        associative = {item.name: item.metadata for item in by_kind["zsh.associative_array_assignment"]}
        self.assertEqual((associative["aliases"]["pair_count"], associative["colors"]["pair_count"], associative["routes"]["static_key_count"]), (0, 2, 2))
        self.assertEqual((associative["secrets"]["redacted_key_count"], associative["secrets"]["redacted_value_count"]), (1, 1))
        self.assertFalse(associative["secrets"]["raw_value_stored"])
        self.assertTrue(any(item.metadata["secret_source"] == "associative_array" for item in by_kind["shell.secret_like"]))

    def test_parameter_expansion_globs_and_path_references_are_syntax_only(self):
        observations = self._extract_fixture("globs-and-expansions.zsh")
        by_kind = observations_by_kind(observations)
        flag_summaries = {item.metadata["flag_summary"] for item in by_kind["zsh.parameter_expansion"]}
        self.assertTrue({"q", "@f", "j", "U", "L", "u"}.issubset(flag_summaries))
        for item in by_kind["zsh.parameter_expansion"]:
            self.assertFalse(item.metadata["value_expanded"] or item.metadata["command_executed"] or item.metadata["raw_value_stored"])

        qualifiers = {item.metadata["qualifier_summary"] for item in by_kind["zsh.glob_qualifier"]}
        self.assertTrue({".", "N", ".om[1,10]"}.issubset(qualifiers))
        features = {item.metadata["feature"] for item in by_kind["zsh.extended_glob"]}
        self.assertTrue({"qualifier", "negation", "alternation"}.issubset(features))
        for item in by_kind["zsh.glob_qualifier"] + by_kind["zsh.extended_glob"]:
            self.assertTrue(item.metadata["syntax_only"])
            self.assertFalse(item.metadata["glob_expanded"] or item.metadata["filesystem_checked"] or item.metadata["target_count_known"])

        self.assertGreaterEqual(len(by_kind["zsh.path_reference"]), 3)
        for item in by_kind["zsh.path_reference"]:
            self.assertFalse(item.metadata["filesystem_checked"] or item.metadata["file_opened"] or item.metadata["target_count_known"])

    def test_zsh_specific_dynamic_markers_are_bounded(self):
        observations = self._extract_fixture("advanced-dynamic.zsh")
        by_kind = observations_by_kind(observations)
        shell_dynamic = {item.metadata["dynamic_reason"] for item in by_kind["shell.dynamic_invocation"]}
        self.assertTrue({"eval", "plugin_manager_eval", "computed_source", "computed_autoload", "array_command"}.issubset(shell_dynamic))
        zsh_dynamic = {item.metadata["dynamic_reason"] for item in by_kind["zsh.dynamic_invocation"]}
        self.assertTrue({"plugin_manager_eval", "computed_fpath", "plugin_loader"}.issubset(zsh_dynamic))
        for item in by_kind["zsh.dynamic_invocation"]:
            self.assertEqual(item.metadata["target_kind"], "dynamic")
            self.assertFalse(item.metadata["command_executed"] or item.metadata["plugin_loaded"] or item.metadata["network_called"])

    def test_side_effect_intent_is_not_runtime_proof(self):
        observations = self._extract_fixture("side-effects.zsh")
        by_kind = observations_by_kind(observations)
        for kind in ("shell.env_write", "shell.env_read", "shell.file_read", "shell.file_write",
                     "shell.host_mutation", "shell.network_call", "shell.package_manager"):
            self.assertIn(kind, by_kind)
        host_categories = {item.metadata["mutation_category"] for item in by_kind["shell.host_mutation"]}
        for cat in ("file_write", "permission_mutation", "package_management"):
            self.assertIn(cat, host_categories)
        self.assertTrue({"brew", "npm", "pip", "cargo", "go"}.issubset({item.name for item in by_kind["shell.package_manager"]}))
        self.assertTrue({"curl", "wget"}.issubset({item.name for item in by_kind["shell.network_call"]}))
        side_effect_kinds = {"shell.env_write", "shell.env_read", "shell.file_read", "shell.file_write",
                             "shell.host_mutation", "shell.network_call", "shell.package_manager"}
        for item in observations:
            if item.kind in side_effect_kinds:
                self.assertTrue(item.metadata["runtime_intent"])
                self.assertFalse(item.metadata["command_executed"] or item.metadata["host_mutation_proven"]
                                 or item.metadata["network_called"] or item.metadata["package_manager_executed"]
                                 or item.metadata["filesystem_checked"] or item.metadata["file_opened"]
                                 or item.metadata["file_mutated"])

    def test_startup_side_effect_intent_keeps_startup_boundary(self):
        observations = self._extract_fixture("startup/.zshenv")
        env_write = observations_by_kind(observations)["shell.env_write"][0]
        self.assertEqual(env_write.metadata["startup_file_kind"], "zshenv")
        self.assertFalse(env_write.metadata["startup_executed"] or env_write.metadata["zsh_executed"])

    def test_secret_like_values_are_redacted_and_fake_markers_are_absent(self):
        observations = self._extract_fixture("redaction.zsh")
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        by_kind = observations_by_kind(observations)
        assignments = {item.name: item.metadata for item in by_kind["shell.assignment"]}
        exports = {item.name: item.metadata for item in by_kind["shell.export"]}
        self.assertTrue(assignments["API_TOKEN"]["redacted"])
        self.assertFalse(assignments["API_TOKEN"]["raw_value_stored"])
        self.assertTrue(exports["PASSWORD"]["redacted"])
        self.assertFalse(exports["PASSWORD"]["raw_value_stored"])
        self.assertTrue(assignments["ZSH_PRIVATE_REPO"]["redacted"] and assignments["PROMPT"]["redacted"] and assignments["secret_paths"]["redacted"])
        zstyle = by_kind["zsh.zstyle"][0]
        self.assertTrue(zstyle.metadata["redacted"])
        self.assertFalse(zstyle.metadata["raw_value_stored"])
        prompt = by_kind["zsh.prompt"][0]
        self.assertTrue(prompt.metadata["redacted"])
        self.assertFalse(prompt.metadata["raw_value_stored"])
        redacted_argument = first_observation(by_kind["shell.command_argument"], kind="shell.command_argument", predicate=lambda item: item.metadata["argument_kind"] == "redacted")
        self.assertFalse(redacted_argument.metadata["raw_value_stored"])
        self.assertEqual(by_kind["zsh.associative_array_assignment"][0].metadata["redacted_value_count"], 1)
        self.assertEqual(by_kind["zsh.array_assignment"][0].metadata["redacted_element_count"], 1)
        net = by_kind["shell.network_call"][0]
        self.assertEqual((net.metadata["target_kind"], net.metadata["target_display"]), ("redacted", "[redacted]"))
        self.assertGreaterEqual(len(by_kind["shell.secret_like"]), 6)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_completion_fixture_records_completion_function_without_loading_it(self):
        observations = self._extract_fixture("zsh/completions/_mytool", "completion/_mytool")
        by_kind = observations_by_kind(observations)
        script = by_kind["zsh.script"][0]
        self.assertEqual(script.metadata["file_type"], "completion")
        for ev in ("completion_path", "compdef", "arguments_function"):
            self.assertIn(ev, script.metadata["classification_evidence"])
        completion = by_kind["zsh.completion_function"][0]
        self.assertEqual((completion.metadata["completion_name"], completion.metadata["compdef_target"]), ("mytool", "mytool"))
        self.assertFalse(completion.metadata["completion_loaded"] or completion.metadata["compinit_executed"])
        self.assertNotIn("shell.command", by_kind)

    def test_false_positive_boundaries_skip_comments_strings_heredocs_and_case_labels(self):
        observations = self._extract_fixture("false-positives.zsh")
        by_kind = observations_by_kind(observations)
        for kind in ("zsh.option", "shell.source", "shell.dynamic_invocation", "zsh.zstyle",
                     "zsh.plugin", "zsh.parameter_expansion", "zsh.glob_qualifier", "zsh.extended_glob",
                     "zsh.dynamic_invocation", "shell.host_mutation", "shell.network_call",
                     "shell.package_manager", "shell.file_write"):
            self.assertNotIn(kind, by_kind)
        assignments = {item.name: item.metadata for item in by_kind["shell.assignment"]}
        self.assertTrue("message" in assignments and "array_with_text" in assignments)
        self.assertEqual(assignments["array_with_text"]["value_kind"], "array")
        commands = {item.name for item in by_kind.get("shell.command", [])}
        self.assertFalse("setopt" in commands or "zinit" in commands)

    def test_discovery_and_ingestion_routes_use_zsh_without_generic_shell_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "scripts" / "basic.zsh", (FIXTURE_ROOT / "basic.zsh").read_text())
            self.write(root / "startup" / ".zshrc", (FIXTURE_ROOT / "startup" / ".zshrc").read_text())
            self.write(root / "scripts" / "plain.sh", "#!/bin/sh\necho ok\n")
            observations = discover_observations(root)

        zsh_files = [obs for obs in observations if obs.kind == "file" and obs.metadata["language"] == "zsh"]
        self.assertEqual({item.path for item in zsh_files}, {"scripts/basic.zsh", "startup/.zshrc"})
        self.assertTrue(any(item.kind == "zsh.script" for item in observations))
        self.assertFalse(any(item.path == "scripts/basic.zsh" and item.extractor == "repo-shell" for item in observations))
        self.assertTrue(any(item.path == "scripts/plain.sh" and item.extractor == "repo-shell" for item in observations))

    def test_bulk_and_archive_routes_include_zsh(self):
        self.assertEqual(classify_bulk_route(Path("scripts/basic.zsh")), "zsh")
        self.assertEqual(_archive_extractor_route(Path("scripts/basic.zsh")), "zsh")
        self.assertEqual(classify_bulk_route(Path("scripts/plain.sh")), "shell")
        self.assertEqual(_archive_extractor_route(Path("scripts/plain.sh")), "shell")
        self.assertEqual(classify_bulk_route(Path("scripts/other.bash")), "bash")

    def test_extractor_does_not_invoke_subprocess_or_shells(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")):
            observations = self._extract_fixture("dynamic.zsh")
        self.assertTrue(observations)

    @staticmethod
    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
