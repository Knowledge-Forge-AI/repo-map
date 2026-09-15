import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.bash import (
    BASH_FIXTURE_ROOT as FIXTURE_ROOT,
    FAKE_SECRET_MARKERS,
    observations_by_kind,
)

from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.graph.discovery import classify_path, discover_observations


class BashExtractorUnitTests(unittest.TestCase):
    def test_classifies_bash_files_by_extension_filename_and_shebang(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "src" / "tool.bash", "# Static fixture\n")
            self.write(root / ".bashrc", "# Static fixture\n")
            self.write(root / ".bash_profile", "# Static fixture\n")
            self.write(root / ".bash_login", "# Static fixture\n")
            self.write(root / "bin" / "tool.sh", "#!/usr/bin/env bash\n")
            self.write(root / "scripts" / "generic.sh", "#!/bin/sh\n")
            self.write(root / ".profile", "# no bash evidence\n")
            self.write(root / "test" / "example.bats", "# bats fixture\n")

            infos = {
                relative: classify_path(root, root / relative)
                for relative in (
                    "src/tool.bash",
                    ".bashrc",
                    ".bash_profile",
                    ".bash_login",
                    "bin/tool.sh",
                    "scripts/generic.sh",
                    ".profile",
                    "test/example.bats",
                )
            }

        self.assertEqual(infos["src/tool.bash"].language, "bash")
        self.assertEqual(infos["src/tool.bash"].role, "source")
        self.assertEqual(infos[".bashrc"].language, "bash")
        self.assertEqual(infos[".bashrc"].role, "config")
        self.assertEqual(infos[".bash_profile"].language, "bash")
        self.assertEqual(infos[".bash_login"].language, "bash")
        self.assertEqual(infos["bin/tool.sh"].language, "bash")
        self.assertEqual(infos["bin/tool.sh"].role, "entrypoint")
        self.assertEqual(infos["scripts/generic.sh"].language, "shell")
        self.assertNotEqual(infos[".profile"].language, "bash")
        self.assertNotEqual(infos["test/example.bats"].language, "bash")

    def test_extracts_script_shell_options_functions_assignments_and_exports(self):
        content = (FIXTURE_ROOT / "basic.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations("scripts/basic.bash", content)

        by_kind = observations_by_kind(observations)
        script = by_kind["shell.script"][0]
        self.assertEqual(script.path, "scripts/basic.bash")
        self.assertEqual(script.confidence, "extracted")
        self.assertEqual(script.metadata["dialect"], "bash")
        self.assertEqual(script.metadata["shebang"], "#!/usr/bin/env bash")
        self.assertEqual(
            script.metadata["classification_evidence"],
            ["extension", "shebang"],
        )
        self.assertTrue(script.metadata["static_only"])
        self.assertFalse(script.metadata["shell_executed"])

        options = {
            (item.kind, item.name, item.metadata["operation"])
            for item in observations
            if item.kind in {"bash.shell_option", "bash.shopt"}
        }
        self.assertIn(("bash.shell_option", "errexit", "enable"), options)
        self.assertIn(("bash.shell_option", "nounset", "enable"), options)
        self.assertIn(("bash.shell_option", "pipefail", "enable"), options)
        self.assertIn(("bash.shopt", "nullglob", "enable"), options)

        functions = by_kind["shell.function"]
        self.assertEqual([item.name for item in functions], ["build_report"])
        self.assertEqual(functions[0].metadata["syntax"], "name_parens")

        assignments = {
            item.name: item.metadata
            for item in by_kind["shell.assignment"]
        }
        self.assertEqual(assignments["CONFIG_FILE"]["declaration"], "readonly")
        self.assertEqual(assignments["CONFIG_FILE"]["value_kind"], "static")
        self.assertEqual(assignments["EXAMPLE_MODE"]["scope"], "file")
        self.assertEqual(assignments["input_path"]["scope"], "function")
        self.assertEqual(assignments["input_path"]["declaration"], "local")
        self.assertEqual(assignments["report_name"]["declaration"], "declare")

        exports = {item.name: item.metadata for item in by_kind["shell.export"]}
        self.assertEqual(exports["PUBLIC_FLAG"]["value_kind"], "static")
        self.assertEqual(exports["OPTIONAL_NAME"]["value_kind"], "omitted")

    def test_extracts_static_sources_and_dynamic_source_marker(self):
        content = (FIXTURE_ROOT / "functions-and-source.bash").read_text(
            encoding="utf-8"
        )

        observations = extract_bash_file_observations(
            "scripts/functions-and-source.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertEqual(
            [(item.metadata["syntax"], item.target) for item in by_kind["shell.source"]],
            [
                ("dot", "file:scripts/lib/common.bash"),
                ("source", "file:scripts/lib/logging.sh"),
                ("source", None),
            ],
        )
        self.assertEqual(
            by_kind["shell.source"][2].metadata["resolution"],
            "dynamic",
        )
        self.assertEqual(
            [item.name for item in by_kind["shell.function"]],
            ["load_config", "invoke_task"],
        )
        self.assertEqual(
            by_kind["shell.function"][1].metadata["syntax"],
            "function_keyword",
        )

    def test_extracts_command_substitution_and_dynamic_invocation_markers(self):
        content = (FIXTURE_ROOT / "dynamic.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations("scripts/dynamic.bash", content)

        by_kind = observations_by_kind(observations)
        substitutions = {
            item.metadata["dynamic_reason"]
            for item in by_kind["shell.command_substitution"]
        }
        self.assertEqual(
            substitutions,
            {"command-substitution", "backtick-command-substitution"},
        )
        dynamic = {
            (item.metadata["invocation_kind"], item.metadata["dynamic_reason"])
            for item in by_kind["shell.dynamic_invocation"]
        }
        self.assertIn(("eval", "eval"), dynamic)
        self.assertIn(("variable_command", "variable-command"), dynamic)
        self.assertIn(("array_command", "array-command"), dynamic)
        self.assertIn(("bash_c", "bash-c"), dynamic)
        self.assertIn(("sh_c", "sh-c"), dynamic)
        self.assertNotIn("shell.command", by_kind)
        self.assertNotIn("shell.external_command", by_kind)

    def test_secret_like_assignments_and_exports_are_redacted(self):
        content = (FIXTURE_ROOT / "redaction.env.example").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/redaction.env.example",
            content,
        )

        payload = "\n".join(item.to_json_line() for item in observations)
        by_kind = observations_by_kind(observations)
        redacted = {
            item.name: item.metadata
            for item in by_kind["shell.assignment"]
            if item.metadata.get("redacted")
        }
        self.assertIn("PASSWORD", redacted)
        self.assertIn("GITHUB_TOKEN", redacted)
        self.assertIn("AWS_SECRET_ACCESS_KEY", redacted)
        self.assertIn("API_KEY", redacted)
        secret_like_names = {item.name for item in by_kind["shell.secret_like"]}
        self.assertIn("PASSWORD", secret_like_names)
        self.assertIn("NPM_TOKEN", secret_like_names)
        self.assertFalse(
            next(
                item
                for item in by_kind["shell.assignment"]
                if item.name == "PUBLIC_VALUE"
            ).metadata["redacted"]
        )
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_false_positive_boundaries_skip_comments_strings_heredocs_and_case_labels(self):
        content = (FIXTURE_ROOT / "false-positives.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/false-positives.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertEqual([item.name for item in by_kind["shell.function"]], [
            "real_function",
        ])
        self.assertEqual(
            {item.name for item in by_kind["shell.assignment"]},
            {
                "quoted_command",
                "side_effect_string",
                "single_quoted",
                "example_assignment",
                "alias_string",
                "trap_string",
                "visible_value",
            },
        )
        self.assertNotIn("shell.dynamic_invocation", by_kind)
        self.assertNotIn("shell.source", by_kind)

    def test_discovery_routes_bash_files_to_bash_extractor_and_preserves_generic_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "scripts" / "bash-tool.sh",
                "#!/usr/bin/env bash\nset -e\nbuild() { :; }\n",
            )
            self.write(root / "scripts" / "generic.sh", "#!/bin/sh\necho ok\n")

            observations = discover_observations(root)

        bash_observations = [
            item for item in observations if item.path == "scripts/bash-tool.sh"
        ]
        generic_observations = [
            item for item in observations if item.path == "scripts/generic.sh"
        ]
        self.assertIn("shell.script", {item.kind for item in bash_observations})
        self.assertIn("bash.shell_option", {item.kind for item in bash_observations})
        bash_file = next(item for item in bash_observations if item.kind == "file")
        self.assertEqual(bash_file.metadata["language"], "bash")
        generic_file = next(item for item in generic_observations if item.kind == "file")
        self.assertEqual(generic_file.metadata["language"], "shell")
        self.assertIn("shell.command", {item.kind for item in generic_observations})

    def test_extractor_does_not_invoke_subprocess_or_shells(self):
        content = (FIXTURE_ROOT / "dynamic.bash").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("executed")):
            observations = extract_bash_file_observations("scripts/dynamic.bash", content)

        self.assertGreater(len(observations), 0)

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
