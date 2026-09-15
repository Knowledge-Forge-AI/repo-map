import unittest

from repomap_test_support.bash import (
    BASH_FIXTURE_ROOT as FIXTURE_ROOT,
    FAKE_SECRET_MARKERS,
    first_observation,
    observations_by_kind,
)

from repomap_kg.extractors.shell.bash import extract_bash_file_observations


class BashSideEffectExtractorUnitTests(unittest.TestCase):
    def test_extracts_env_reads_writes_and_redacts_side_effect_secrets(self):
        content = (FIXTURE_ROOT / "side-effects.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/side-effects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        env_write_names = {item.name for item in by_kind["shell.env_write"]}
        self.assertTrue(
            {"EXAMPLE_TOKEN", "EXAMPLE_MODE", "EXAMPLE_OVERLAY"}.issubset(
                env_write_names
            )
        )
        env_read_names = {item.name for item in by_kind["shell.env_read"]}
        self.assertTrue({"EXAMPLE_MODE", "EXAMPLE_TOKEN"}.issubset(env_read_names))

        token_write = first_observation(
            by_kind["shell.env_write"],
            kind="shell.env_write",
            name="EXAMPLE_TOKEN",
        )
        self.assertTrue(token_write.metadata["redacted"])
        self.assertFalse(token_write.metadata["raw_value_stored"])
        self.assertEqual(token_write.metadata["scope"], "export")
        overlay = first_observation(
            by_kind["shell.env_write"],
            kind="shell.env_write",
            name="EXAMPLE_OVERLAY",
        )
        self.assertEqual(overlay.metadata["scope"], "process_overlay")

        payload = "\n".join(item.to_json_line() for item in observations)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_extracts_file_effects_redirects_and_host_mutation_boundaries(self):
        content = (FIXTURE_ROOT / "side-effects.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/side-effects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        file_reads = {
            (item.metadata["command_name"], item.metadata["target_display"])
            for item in by_kind["shell.file_read"]
        }
        self.assertIn(("cat", "./data/input.txt"), file_reads)
        self.assertIn(("grep", "./data/input.txt"), file_reads)
        self.assertIn(("test", "./data/input.txt"), file_reads)
        self.assertIn(("grep", "./data/input.txt"), file_reads)

        file_write_targets = {
            item.metadata["target_display"] for item in by_kind["shell.file_write"]
        }
        self.assertTrue(
            {
                "./out/report.txt",
                "./err.log",
                "./combined.log",
                "./out/state.txt",
                "./out/cache",
                "./out/source.txt",
                "./out/current.txt",
                "./current-link",
                "./out/archive.tar.gz",
            }.issubset(file_write_targets)
        )
        dynamic_file_write = first_observation(
            by_kind["shell.file_write"],
            kind="shell.file_write",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_file_write.metadata["target_display"], "[dynamic]")

        mutation_categories = {
            item.metadata["mutation_category"] for item in by_kind["shell.host_mutation"]
        }
        self.assertTrue(
            {
                "file_write",
                "directory_mutation",
                "symlink_mutation",
                "permission_mutation",
                "ownership_mutation",
                "archive_extraction",
                "shell_profile_mutation",
            }.issubset(mutation_categories)
        )
        read_only_mutators = {
            item.metadata["command_name"]
            for item in by_kind["shell.host_mutation"]
            if item.metadata["command_name"] in {"cat", "grep", "test"}
        }
        self.assertEqual(read_only_mutators, set())

    def test_extracts_network_package_runtime_and_policy_side_effects(self):
        content = (FIXTURE_ROOT / "side-effects.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/side-effects.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        network_commands = {item.metadata["command_name"] for item in by_kind["shell.network_call"]}
        self.assertTrue({"curl", "wget", "nc", "ssh", "scp"}.issubset(network_commands))
        dynamic_network = first_observation(
            by_kind["shell.network_call"],
            kind="shell.network_call",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_network.metadata["target_display"], "[dynamic]")

        package_managers = {
            item.metadata["manager"] for item in by_kind["shell.package_manager"]
        }
        self.assertTrue(
            {"apt-get", "brew", "npm", "pip", "gem", "cargo", "go"}.issubset(
                package_managers
            )
        )
        self.assertFalse(
            any(
                item.metadata["command_name"] == "npm"
                and item.metadata["operation"] == "--version"
                for item in by_kind["shell.host_mutation"]
            )
        )
        mutations = {
            (item.metadata["command_name"], item.metadata["mutation_category"])
            for item in by_kind["shell.host_mutation"]
        }
        self.assertIn(("apt-get", "package_management"), mutations)
        self.assertIn(("systemctl", "service_control"), mutations)
        self.assertIn(("crontab", "scheduled_job"), mutations)
        self.assertIn(("docker", "container_runtime"), mutations)
        self.assertIn(("kubectl", "container_runtime"), mutations)
        self.assertIn(("terraform", "infrastructure_runtime"), mutations)
        self.assertIn(("chmod", "permission_mutation"), mutations)
        self.assertIn(("chown", "ownership_mutation"), mutations)
        self.assertIn(("security", "credential_handling"), mutations)
        self.assertIn(("spctl", "security_policy"), mutations)
        self.assertIn(("defaults", "security_policy"), mutations)
        self.assertFalse(any(item[0] == "docker" and item[1] == "unknown_host_mutation" for item in mutations))

        read_only_runtime = [
            item
            for item in by_kind["shell.host_mutation"]
            if (
                item.metadata["command_name"] == "kubectl"
                and item.metadata["operation"] == "get"
            )
            or (
                item.metadata["command_name"] == "terraform"
                and item.metadata["operation"] == "plan"
            )
        ]
        self.assertEqual(read_only_runtime, [])

    def test_bash3_false_positive_boundaries_skip_side_effect_lookalikes(self):
        content = (FIXTURE_ROOT / "false-positives.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/false-positives.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertNotIn("shell.file_read", by_kind)
        self.assertNotIn("shell.file_write", by_kind)
        self.assertNotIn("shell.host_mutation", by_kind)
        self.assertNotIn("shell.network_call", by_kind)
        self.assertNotIn("shell.package_manager", by_kind)

    def test_extracts_advanced_safety_observations_without_runtime_claims(self):
        content = (FIXTURE_ROOT / "advanced-safety.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/advanced-safety.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        alias_names = {item.name for item in by_kind["bash.alias"]}
        self.assertTrue({"ll", "gs", "dangerous", "secret_alias"}.issubset(alias_names))
        dynamic_alias = first_observation(
            by_kind["bash.alias"],
            kind="bash.alias",
            predicate=lambda item: item.metadata["resolution"] == "dynamic",
        )
        self.assertEqual(dynamic_alias.metadata["alias_name"], "[dynamic]")
        secret_alias = first_observation(
            by_kind["bash.alias"],
            kind="bash.alias",
            name="secret_alias",
        )
        self.assertTrue(secret_alias.metadata["target_redacted"])
        self.assertFalse(secret_alias.metadata["target_value_stored"])
        self.assertFalse(
            any(
                item.metadata["command_name"] == "rm"
                for item in by_kind.get("shell.host_mutation", [])
            )
        )

        arrays = {
            (item.name, item.metadata["operation"]): item.metadata
            for item in by_kind["bash.array_assignment"]
        }
        self.assertEqual(arrays[("items", "assign")]["item_count"], 3)
        self.assertEqual(arrays[("items", "append")]["item_count"], 1)
        self.assertEqual(arrays[("names", "assign")]["static_item_count"], 2)
        assoc = {item.name: item.metadata for item in by_kind["bash.associative_array_assignment"]}
        self.assertEqual(assoc["labels"]["known_keys"], ["ok", "fail"])
        self.assertIn("ApiToken", assoc["secret_map"]["redacted_keys"])
        self.assertGreater(assoc["secret_map"]["redacted_item_count"], 0)

        traps = by_kind["bash.trap"]
        exit_trap = first_observation(traps, kind="bash.trap", name="EXIT")
        self.assertEqual(exit_trap.metadata["handler_kind"], "static")
        self.assertFalse(exit_trap.metadata["executes_at_parse_time"])
        reset_trap = first_observation(
            traps,
            kind="bash.trap",
            predicate=lambda item: item.metadata["handler_kind"] == "reset",
        )
        self.assertEqual(reset_trap.metadata["events"], ["EXIT"])
        secret_trap = first_observation(
            traps,
            kind="bash.trap",
            predicate=lambda item: "INT" in item.metadata["events"],
        )
        self.assertTrue(secret_trap.metadata["handler_redacted"])

        arithmetic_forms = {item.metadata["form"] for item in by_kind["bash.arithmetic"]}
        self.assertEqual(arithmetic_forms, {"expansion", "command", "let"})
        self.assertTrue(
            all(not item.metadata["expression_modeled"] for item in by_kind["bash.arithmetic"])
        )

        test_forms = {item.metadata["form"] for item in by_kind["bash.test_expression"]}
        self.assertEqual(test_forms, {"bracket", "double_bracket", "test_builtin"})
        self.assertFalse(
            any(
                item.metadata["command_name"] in {"[", "[[", "test"}
                and item.metadata["mutation_category"] == "unknown_host_mutation"
                for item in by_kind.get("shell.host_mutation", [])
            )
        )

        case_patterns = {item.metadata["pattern"] for item in by_kind["bash.case_pattern"]}
        self.assertTrue({"start|restart", "stop", "docker", "*"}.issubset(case_patterns))
        command_names = {item.name for item in by_kind.get("shell.command", [])}
        self.assertNotIn("docker", command_names)

        dynamic = {
            (item.metadata["invocation_kind"], item.metadata["dynamic_reason"])
            for item in by_kind["shell.dynamic_invocation"]
        }
        self.assertIn(("eval", "eval"), dynamic)
        self.assertIn(("command_eval", "eval"), dynamic)
        self.assertIn(("variable_command", "variable-command"), dynamic)
        self.assertIn(("array_command", "array-command"), dynamic)
        self.assertIn(("bash_c", "bash-c"), dynamic)
        self.assertIn(("indirect_expansion", "indirect-expansion"), dynamic)
        self.assertIn(("parameter_expansion", "parameter-expansion"), dynamic)

        payload = "\n".join(item.to_json_line() for item in observations)
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_bash4_false_positive_boundaries_skip_advanced_safety_literals(self):
        content = (FIXTURE_ROOT / "false-positives.bash").read_text(encoding="utf-8")

        observations = extract_bash_file_observations(
            "scripts/false-positives.bash",
            content,
        )

        by_kind = observations_by_kind(observations)
        self.assertNotIn("bash.alias", by_kind)
        self.assertNotIn("bash.trap", by_kind)
        command_names = {item.name for item in by_kind.get("shell.command", [])}
        self.assertFalse({"alias", "trap", "curl", "rm", "docker"} & command_names)
        self.assertNotIn(";;", command_names)
