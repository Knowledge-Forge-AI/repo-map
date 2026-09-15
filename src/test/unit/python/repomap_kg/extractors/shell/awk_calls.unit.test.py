import json
import unittest

from repomap_test_support.awk import (
    FAKE_SECRET_MARKERS,
    FIXTURE_ROOT,
    RUNTIME_PROOF_KINDS,
    first_observation,
    observations_by_kind,
)

from repomap_kg.extractors.shell.awk import extract_awk_file_observations


class AwkCallObservationUnitTests(unittest.TestCase):
    def test_AWK2_builtin_and_user_function_calls_are_static_source_evidence(self):
        content = (FIXTURE_ROOT / "calls.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/calls.awk", content)

        by_kind = observations_by_kind(observations)
        builtin_names = {item.name for item in by_kind["awk.builtin_call"]}
        self.assertTrue(
            {"tolower", "print", "length", "sprintf", "gsub", "match", "substr"}.issubset(
                builtin_names
            )
        )
        print_call = first_observation(by_kind["awk.builtin_call"], kind="awk.builtin_call", name="print")
        self.assertEqual(print_call.metadata["builtin_family"], "output")
        self.assertEqual(print_call.metadata["call_context"], "pattern_action")
        self.assertFalse(print_call.metadata["awk_executed"])

        user_call = first_observation(
            by_kind["awk.user_function_call"],
            kind="awk.user_function_call",
            name="normalize",
        )
        self.assertEqual(user_call.metadata["function_name"], "normalize")
        self.assertTrue(user_call.metadata["definition_source_id"].endswith("awk-function:3:normalize"))
        self.assertEqual(user_call.metadata["argument_count"], 1)
        self.assertFalse(user_call.metadata["function_executed"])

    def test_AWK2_file_io_pipe_system_and_redirect_intent_is_non_executing(self):
        content = (FIXTURE_ROOT / "io-and-pipes.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/io-and-pipes.awk", content)

        by_kind = observations_by_kind(observations)
        self.assertIn("awk.builtin_call", by_kind)
        self.assertIn("awk.file_read", by_kind)
        self.assertIn("awk.file_write", by_kind)
        self.assertIn("awk.pipe_read", by_kind)
        self.assertIn("awk.pipe_write", by_kind)
        self.assertIn("awk.system_call", by_kind)
        self.assertIn("awk.redirect", by_kind)

        file_read = by_kind["awk.file_read"][0]
        self.assertEqual(file_read.metadata["target_kind"], "static")
        self.assertEqual(file_read.metadata["target_display"], "docs/examples/awk/public-input.txt")
        self.assertFalse(file_read.metadata["filesystem_checked"])
        self.assertFalse(file_read.metadata["file_opened"])
        self.assertTrue(file_read.metadata["runtime_intent"])

        write_modes = {item.metadata["write_mode"] for item in by_kind["awk.file_write"]}
        self.assertTrue({"truncate", "append"}.issubset(write_modes))
        for write in by_kind["awk.file_write"]:
            self.assertTrue(write.metadata["runtime_intent"])
            self.assertFalse(write.metadata["file_mutated"])
            self.assertFalse(write.metadata["host_mutation_proven"])

        pipe_read = by_kind["awk.pipe_read"][0]
        self.assertEqual(pipe_read.metadata["command_text_kind"], "static")
        self.assertEqual(pipe_read.metadata["command_summary"], "printf static-example")
        self.assertFalse(pipe_read.metadata["command_executed"])
        self.assertFalse(pipe_read.metadata["pipe_opened"])

        pipe_write = by_kind["awk.pipe_write"][0]
        self.assertEqual(pipe_write.metadata["command_summary"], "sort")
        self.assertFalse(pipe_write.metadata["shell_executed"])

        system_call = by_kind["awk.system_call"][0]
        self.assertEqual(system_call.metadata["command_summary"], "printf static-example")
        self.assertTrue(system_call.metadata["runtime_intent"])
        self.assertFalse(system_call.metadata["command_executed"])
        self.assertFalse(system_call.metadata["host_mutation_proven"])
        self.assertFalse(RUNTIME_PROOF_KINDS & {item.kind for item in observations})

        redirect_kinds = {item.metadata["redirect_kind"] for item in by_kind["awk.redirect"]}
        self.assertTrue({"file_read", "file_write", "pipe_read", "pipe_write"}.issubset(redirect_kinds))

    def test_AWK2_dynamic_targets_are_bounded_without_precise_targets(self):
        content = (FIXTURE_ROOT / "dynamic.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/dynamic.awk", content)

        by_kind = observations_by_kind(observations)
        dynamic_write = first_observation(
            by_kind["awk.file_write"],
            kind="awk.file_write",
            predicate=lambda item: item.metadata["target_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_write.metadata["target_display"], "[dynamic]")
        self.assertEqual(dynamic_write.metadata["dynamic_reason"], "computed_target")

        dynamic_pipe = first_observation(
            by_kind["awk.pipe_read"],
            kind="awk.pipe_read",
            predicate=lambda item: item.metadata["command_text_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_pipe.metadata["command_summary"], "[dynamic]")
        self.assertFalse(dynamic_pipe.metadata["command_executed"])

        dynamic_system = first_observation(
            by_kind["awk.system_call"],
            kind="awk.system_call",
            predicate=lambda item: item.metadata["command_text_kind"] == "dynamic",
        )
        self.assertEqual(dynamic_system.metadata["dynamic_reason"], "computed_target")
        self.assertFalse(dynamic_system.metadata["shell_executed"])

    def test_AWK2_gawk_include_and_extension_are_static_without_loading(self):
        content = (FIXTURE_ROOT / "includes-and-extensions.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/includes-and-extensions.awk", content)

        by_kind = observations_by_kind(observations)
        include = by_kind["awk.include"][0]
        self.assertEqual(include.metadata["dialect"], "gawk")
        self.assertEqual(include.metadata["include_target"], "lib/common.awk")
        self.assertEqual(include.metadata["target_kind"], "static")
        self.assertEqual(include.metadata["resolved_path"], "filters/lib/common.awk")
        self.assertFalse(include.metadata["file_read"])
        self.assertFalse(include.metadata["include_loaded"])

        extension = by_kind["awk.extension"][0]
        self.assertEqual(extension.metadata["extension_name"], "ordchr")
        self.assertFalse(extension.metadata["extension_loaded"])
        self.assertFalse(extension.metadata["awk_executed"])

    def test_AWK2_secret_like_evidence_redacts_assignment_command_and_path_contexts(self):
        content = (FIXTURE_ROOT / "redaction.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/redaction.awk", content)

        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        by_kind = observations_by_kind(observations)
        secret_sources = {item.metadata["secret_source"] for item in by_kind["awk.secret_like"]}
        self.assertTrue(
            {"variable_assignment", "system_call", "file_target"}.issubset(secret_sources)
        )
        redacted_system = first_observation(
            by_kind["awk.system_call"],
            kind="awk.system_call",
            predicate=lambda item: item.metadata["command_text_kind"] == "redacted",
        )
        self.assertFalse(redacted_system.metadata["raw_value_stored"])
        redacted_path = first_observation(
            by_kind["awk.file_write"],
            kind="awk.file_write",
            predicate=lambda item: item.metadata["target_kind"] == "redacted",
        )
        self.assertFalse(redacted_path.metadata["raw_value_stored"])
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)
