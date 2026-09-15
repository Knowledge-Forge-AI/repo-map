import unittest

from repomap_test_support.bash import (
    BASH_FIXTURE_ROOT as FIXTURE_ROOT,
    FAKE_SECRET_MARKERS,
    first_observation,
    observations_by_kind,
)

from repomap_kg.extractors.shell.bash import extract_bash_file_observations


class BashCommandExtractorUnitTests(unittest.TestCase):
    def test_extracts_commands_external_tools_and_arguments(self):
        content = (FIXTURE_ROOT / "commands-pipelines-redirects.bash").read_text(
            encoding="utf-8"
        )

        observations = extract_bash_file_observations(
            "scripts/commands-pipelines-redirects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        command_names = {item.name for item in by_kind["shell.command"]}
        self.assertIn("printf", command_names)
        self.assertIn("git", command_names)
        self.assertIn("sudo", command_names)
        self.assertIn("curl", command_names)
        external_names = {item.name for item in by_kind["shell.external_command"]}
        self.assertTrue(
            {
                "git",
                "docker",
                "kubectl",
                "terraform",
                "grep",
                "sort",
                "uniq",
                "make",
                "python3",
                "curl",
            }.issubset(external_names)
        )
        printf = first_observation(by_kind["shell.command"], kind="shell.command", name="printf")
        self.assertEqual(printf.metadata["command_family"], "builtin")
        self.assertEqual(printf.metadata["original_token"], "printf")
        self.assertEqual(printf.metadata["dialect"], "bash")
        self.assertTrue(printf.metadata["static_only"])
        self.assertFalse(printf.metadata["shell_executed"])

        kubectl = first_observation(
            by_kind["shell.command"],
            kind="shell.command",
            name="kubectl",
        )
        kubectl_args = [
            item.metadata
            for item in by_kind["shell.command_argument"]
            if item.metadata["command_source_id"] == kubectl.source_id
        ]
        self.assertEqual(
            [(item.get("argument_name"), item["argument_form"], item["value_kind"]) for item in kubectl_args],
            [
                (None, "positional", "static"),
                (None, "positional", "static"),
                ("namespace", "long", "static"),
            ],
        )
        self.assertEqual(kubectl_args[2]["value"], "fixture")

        curl = first_observation(
            by_kind["shell.command"],
            kind="shell.command",
            name="curl",
        )
        curl_args = [
            item.metadata
            for item in by_kind["shell.command_argument"]
            if item.metadata["command_source_id"] == curl.source_id
        ]
        self.assertIn(("fsS", "short", "omitted"), [
            (item.get("argument_name"), item["argument_form"], item["value_kind"])
            for item in curl_args
        ])
        redacted_headers = [
            item for item in curl_args if item.get("argument_name") == "H"
        ]
        self.assertEqual(redacted_headers[0]["value_kind"], "redacted")
        self.assertTrue(redacted_headers[0]["redacted"])
        self.assertFalse(redacted_headers[0]["raw_value_stored"])

        overlay_git = first_observation(
            by_kind["shell.command"],
            kind="shell.command",
            name="git",
            predicate=lambda item: item.metadata["assignment_overlay_count"] == 1,
        )
        self.assertEqual(overlay_git.metadata["argument_count"], 1)
        overlay_args = [
            item.metadata
            for item in by_kind["shell.command_argument"]
            if item.metadata["command_source_id"] == overlay_git.source_id
        ]
        self.assertEqual(overlay_args[0]["argument_form"], "assignment_overlay")
        self.assertEqual(overlay_args[0]["argument_name"], "FOO")

        sudo = first_observation(by_kind["shell.command"], kind="shell.command", name="sudo")
        self.assertEqual(sudo.metadata["command_family"], "wrapper")
        self.assertEqual(sudo.metadata["wrapper_command"], "sudo")
        self.assertEqual(sudo.metadata["wrapped_command"], "apt-get")

        payload = "\n".join(item.to_json_line() for item in observations)
        self.assertNotIn("FAKE_BASH_HEADER_SECRET", payload)

    def test_extracts_pipelines_and_command_chains_with_order_only(self):
        content = (FIXTURE_ROOT / "commands-pipelines-redirects.bash").read_text(
            encoding="utf-8"
        )

        observations = extract_bash_file_observations(
            "scripts/commands-pipelines-redirects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        pipeline = first_observation(
            by_kind["shell.pipeline"],
            kind="shell.pipeline",
            predicate=lambda item: item.metadata["segment_count"] == 3,
        )
        self.assertEqual(pipeline.metadata["operators"], ["|", "|"])
        self.assertFalse(pipeline.metadata["object_or_byte_flow_modeled"])
        pipeline_commands = [
            (item.name, item.metadata["pipeline_index"])
            for item in by_kind["shell.command"]
            if item.metadata.get("pipeline_id") == pipeline.metadata["pipeline_id"]
        ]
        self.assertEqual(pipeline_commands, [("grep", 0), ("sort", 1), ("uniq", 2)])

        pipe_err = first_observation(
            by_kind["shell.pipeline"],
            kind="shell.pipeline",
            predicate=lambda item: item.metadata["operators"] == ["|&"],
        )
        self.assertEqual(pipe_err.metadata["segment_count"], 2)

        chain = first_observation(by_kind["shell.command_chain"], kind="shell.command_chain")
        self.assertEqual(chain.metadata["operators"], ["&&", "||"])
        self.assertEqual(chain.metadata["segment_count"], 3)
        self.assertFalse(chain.metadata["control_flow_modeled"])
        chain_commands = [
            (item.name, item.metadata["chain_index"])
            for item in by_kind["shell.command"]
            if item.metadata.get("chain_id") == chain.metadata["chain_id"]
        ]
        self.assertEqual(chain_commands, [("make", 0), ("make", 1), ("printf", 2)])

    def test_extracts_redirects_here_strings_and_process_substitutions(self):
        content = (FIXTURE_ROOT / "commands-pipelines-redirects.bash").read_text(
            encoding="utf-8"
        )

        observations = extract_bash_file_observations(
            "scripts/commands-pipelines-redirects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        redirects = by_kind["shell.redirect"]
        redirect_modes = {
            (item.metadata["operator"], item.metadata["mode"])
            for item in redirects
        }
        self.assertTrue(
            {
                (">", "truncate"),
                (">>", "append"),
                ("<", "read"),
                ("2>", "truncate"),
                ("2>&1", "duplicate"),
                ("&>", "truncate"),
                ("<<<", "here_string"),
            }.issubset(redirect_modes)
        )
        dynamic_redirect = first_observation(
            redirects,
            kind="shell.redirect",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_redirect.metadata["target_display"], "[dynamic]")
        here_string = first_observation(
            redirects,
            kind="shell.redirect",
            predicate=lambda item: item.metadata["operator"] == "<<<",
        )
        self.assertEqual(here_string.metadata["value_kind"], "static")
        self.assertEqual(here_string.metadata["target_kind"], "static")

        process_substitutions = by_kind["shell.process_substitution"]
        self.assertEqual(
            {item.metadata["direction"] for item in process_substitutions},
            {"input", "output"},
        )
        self.assertTrue(all(not item.metadata["inner_modeled"] for item in process_substitutions))
        self.assertTrue(all(item.metadata["dynamic_reason"] == "process-substitution" for item in process_substitutions))

    def test_extracts_heredoc_summaries_without_body_leaks(self):
        content = (FIXTURE_ROOT / "heredocs.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations("scripts/heredocs.bash", content)

        by_kind = observations_by_kind(observations)
        heredocs = {item.metadata["delimiter"]: item.metadata for item in by_kind["shell.heredoc"]}
        self.assertEqual(heredocs["EOF"]["body_line_count"], 2)
        self.assertFalse(heredocs["EOF"]["delimiter_quoted"])
        self.assertEqual(heredocs["EOF"]["expansion_mode"], "expandable")
        self.assertTrue(heredocs["LITERAL"]["delimiter_quoted"])
        self.assertEqual(heredocs["LITERAL"]["expansion_mode"], "literal")
        self.assertTrue(heredocs["INDENTED"]["tab_stripping"])
        self.assertEqual(heredocs["INDENTED"]["secret_like_assignment_count"], 1)

        command_names = {item.name for item in by_kind["shell.command"]}
        self.assertEqual(command_names, {"cat"})
        secret_like_names = {item.name for item in by_kind["shell.secret_like"]}
        self.assertTrue({"TOKEN", "PASSWORD", "api_key"}.issubset(secret_like_names))
        payload = "\n".join(item.to_json_line() for item in observations)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)
        self.assertNotIn("docker run not-a-command", payload)

    def test_bash2_false_positive_boundaries_do_not_extract_body_or_string_commands(self):
        content = (FIXTURE_ROOT / "false-positives.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/false-positives.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        command_names = {item.name for item in by_kind.get("shell.command", [])}
        self.assertFalse({"curl", "rm", "eval", "source", "docker"} & command_names)
        self.assertNotIn("shell.pipeline", by_kind)
        self.assertNotIn("shell.redirect", by_kind)
        self.assertNotIn("shell.process_substitution", by_kind)
