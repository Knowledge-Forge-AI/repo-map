import json
import unittest

from repomap_kg.extractors.shell.zunit import extract_zunit_file_observations


SUITE_PATH = "test/general1_refusals.zunit"
RUNTIME_FLAGS = (
    "static_only", "shell_executed", "zsh_executed", "zunit_executed", "tests_executed",
    "assertions_executed", "commands_executed", "fixtures_loaded", "mocks_applied",
)
LONG_VALUE = "n" * 130


def extract(*lines):
    return extract_zunit_file_observations(SUITE_PATH, "\n".join(lines) + "\n")


def at(observations, kind, line_number):
    return [
        item for item in observations
        if item.kind == kind and item.start_line == line_number
    ]


def only(observations, kind, line_number):
    matches = at(observations, kind, line_number)
    assert len(matches) == 1, f"{kind} at line {line_number}: {len(matches)} matches"
    return matches[0]


def assert_static_only(test, observations):
    for item in observations:
        test.assertTrue(item.metadata["static_only"], item.kind)
        for flag in RUNTIME_FLAGS[1:]:
            test.assertFalse(item.metadata[flag], f"{item.kind}.{flag}")


class ZunitNameBoundaryContractTests(unittest.TestCase):
    def test_overlong_suite_and_test_names_are_bounded_not_stored(self):
        observations = extract(
            f'describe "{LONG_VALUE}"',
            f'test "{LONG_VALUE}" {{',
            "  run ./bin/example",
            "}",
        )

        suite = only(observations, "zunit.suite", 1)
        self.assertEqual(suite.name, "[dynamic]")
        self.assertEqual(suite.metadata["suite_name_kind"], "unknown")
        self.assertEqual(suite.metadata["dynamic_reason"], "long_name")
        self.assertFalse(suite.metadata["suite_name_redacted"])
        self.assertFalse(suite.metadata["raw_value_stored"])
        self.assertNotIn("suite_name", suite.metadata)
        self.assertEqual(suite.confidence, "heuristic")

        case = only(observations, "zunit.test_case", 2)
        self.assertEqual(case.name, "[dynamic]")
        self.assertEqual(case.metadata["test_name_kind"], "unknown")
        self.assertEqual(case.metadata["dynamic_reason"], "long_name")
        self.assertFalse(case.metadata["test_name_redacted"])
        self.assertFalse(case.metadata["raw_value_stored"])
        self.assertEqual(case.confidence, "heuristic")
        name = only(observations, "zunit.test_name", 2)
        self.assertEqual(name.metadata["name_kind"], "unknown")
        self.assertFalse(name.metadata["raw_name_stored"])
        self.assertNotIn("test_name", name.metadata)

        self.assertEqual([item for item in observations if item.kind == "zunit.secret_like"], [])
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertNotIn(LONG_VALUE, payload)
        assert_static_only(self, observations)


class ZunitTargetPathRefusalContractTests(unittest.TestCase):
    def test_unsafe_and_repository_escaping_targets_are_unresolved(self):
        observations = extract(
            "source /opt/zunit/common.zsh",
            "source ~/zunit/common.zsh",
            "source ../../outside/common.zsh",
            "load_fixture ../../outside/data.txt",
            "source ./helpers/../lib/common.zsh",
        )

        expected = {1: "unsafe_path", 2: "unsafe_path", 3: "repository_escaping_path"}
        for line_number, reason in expected.items():
            helper = only(observations, "zunit.helper", line_number)
            self.assertEqual(helper.name, "[dynamic]")
            self.assertEqual(helper.confidence, "unknown")
            self.assertEqual(helper.metadata["target_kind"], "unknown")
            self.assertEqual(helper.metadata["resolution"], "unknown")
            self.assertEqual(helper.metadata["dynamic_reason"], reason)
            self.assertFalse(helper.metadata["raw_value_stored"])
            self.assertNotIn("helper_path", helper.metadata)
            self.assertNotIn("resolved_path", helper.metadata)
            self.assertFalse(helper.metadata["helper_loaded"] or helper.metadata["file_read"])

        fixture = only(observations, "zunit.fixture_reference", 4)
        self.assertEqual(fixture.name, "[dynamic]")
        self.assertEqual(fixture.metadata["reference_kind"], "load_fixture")
        self.assertEqual(fixture.metadata["dynamic_reason"], "repository_escaping_path")
        self.assertEqual(fixture.confidence, "unknown")
        self.assertFalse(fixture.metadata["fixture_loaded"] or fixture.metadata["filesystem_checked"])

        static = only(observations, "zunit.helper", 5)
        self.assertEqual(static.name, "./helpers/../lib/common.zsh")
        self.assertEqual(static.metadata["resolved_path"], "test/lib/common.zsh")
        self.assertEqual(static.metadata["resolution"], "static")
        self.assertEqual(static.confidence, "extracted")
        assert_static_only(self, observations)


class ZunitCommandUnderTestRefusalContractTests(unittest.TestCase):
    def setUp(self):
        self.observations = extract(
            'input_fixture="./fixtures/a.txt"',
            'test "command shapes" {',
            "  run",
            "  run ./bin/token-tool status",
            f"  run ./bin/{LONG_VALUE}",
            '  run ./bin/example "unterminated',
            '  run ./bin/example "${input_fixture}" "$other_value" "$ZUNIT_TMPDIR/out.txt"',
            "}",
        )

    def test_missing_command_is_dynamic_with_no_arguments(self):
        missing = only(self.observations, "zunit.command_under_test", 3)

        self.assertEqual(missing.name, "[dynamic]")
        self.assertEqual(missing.confidence, "unknown")
        self.assertEqual(missing.metadata["command_kind"], "dynamic")
        self.assertEqual(missing.metadata["dynamic_reason"], "missing_command")
        self.assertEqual(missing.metadata["argument_count"], 0)
        self.assertEqual(missing.metadata["argument_summary_kind"], "omitted")
        self.assertEqual(missing.metadata["enclosing_test"], "command shapes")
        self.assertFalse(missing.metadata["raw_value_stored"])

    def test_secret_like_and_overlong_command_names_are_never_stored(self):
        redacted = only(self.observations, "zunit.command_under_test", 4)
        self.assertEqual(redacted.name, "[dynamic]")
        self.assertEqual(redacted.metadata["target_kind"], "redacted")
        self.assertEqual(redacted.metadata["redaction_reason"], "secret-like-name")
        self.assertNotIn("command_name", redacted.metadata)
        self.assertFalse(redacted.metadata["raw_value_stored"])
        self.assertEqual(redacted.metadata["argument_summary_kind"], "bounded")

        overlong = only(self.observations, "zunit.command_under_test", 5)
        self.assertEqual(overlong.name, "[dynamic]")
        self.assertEqual(overlong.metadata["target_kind"], "unknown")
        self.assertEqual(overlong.metadata["dynamic_reason"], "long_command")
        self.assertNotIn("command_name", overlong.metadata)
        self.assertFalse(overlong.metadata["raw_value_stored"])

        payload = json.dumps([item.to_dict() for item in self.observations], sort_keys=True)
        self.assertNotIn("token-tool", payload)
        self.assertNotIn(LONG_VALUE, payload)

    def test_unterminated_quote_line_yields_no_observations(self):
        self.assertEqual([item for item in self.observations if item.start_line == 6], [])
        self.assertEqual(len(at(self.observations, "zunit.command_under_test", 7)), 1)

    def test_fixture_arguments_resolve_only_through_known_fixture_variables(self):
        command = only(self.observations, "zunit.command_under_test", 7)
        self.assertEqual(command.name, "./bin/example")
        self.assertEqual(command.metadata["command_kind"], "run_wrapper")
        self.assertEqual(command.metadata["argument_count"], 3)
        self.assertEqual(command.metadata["argument_summary_kind"], "dynamic")

        assignment = only(self.observations, "zunit.fixture_reference", 1)
        self.assertEqual(assignment.metadata["reference_kind"], "assignment")
        self.assertEqual(assignment.metadata["resolved_path"], "test/fixtures/a.txt")

        references = at(self.observations, "zunit.fixture_reference", 7)
        self.assertEqual(sorted(item.name for item in references), ["./fixtures/a.txt", "[dynamic]"])
        by_name = {item.name: item for item in references}
        resolved = by_name["./fixtures/a.txt"]
        self.assertEqual(resolved.metadata["reference_kind"], "command_argument")
        self.assertEqual(resolved.metadata["target_kind"], "static")
        self.assertEqual(resolved.metadata["enclosing_test"], "command shapes")
        self.assertEqual(resolved.confidence, "extracted")
        temporary = by_name["[dynamic]"]
        self.assertEqual(temporary.metadata["target_kind"], "dynamic")
        self.assertEqual(temporary.metadata["dynamic_reason"], "computed_target")
        self.assertEqual(temporary.confidence, "unknown")
        self.assertFalse(temporary.metadata["raw_value_stored"])
        assert_static_only(self, self.observations)


class ZunitExpectationValueContractTests(unittest.TestCase):
    def setUp(self):
        self.observations = extract(
            'test "assertion values" {',
            "  run ./bin/example",
            '  assert_equal "$output" "hello"',
            '  assert_equal "$output" "$expected_text"',
            f'  assert_output "{LONG_VALUE}"',
            "  assert_output --partial",
            "}",
        )

    def test_equality_without_a_status_argument_has_unknown_expectation_kind(self):
        assertion = only(self.observations, "zunit.assertion", 3)
        self.assertEqual(assertion.metadata["assertion_family"], "equality")
        self.assertEqual(assertion.metadata["mode"], "exact")
        self.assertEqual(assertion.metadata["argument_count"], 2)
        expectation = only(self.observations, "zunit.expectation", 3)
        self.assertEqual(expectation.metadata["expectation_kind"], "unknown")
        self.assertEqual(expectation.metadata["matcher"], "equals")
        self.assertEqual(expectation.metadata["expected_value_kind"], "static")
        self.assertEqual(expectation.metadata["expected_value_summary"], "hello")
        self.assertEqual(expectation.confidence, "extracted")

    def test_dynamic_expected_value_is_not_stored(self):
        expectation = only(self.observations, "zunit.expectation", 4)
        self.assertEqual(expectation.metadata["expected_value_kind"], "dynamic")
        self.assertEqual(expectation.metadata["dynamic_reason"], "computed_expected_value")
        self.assertFalse(expectation.metadata["raw_expected_value_stored"])
        self.assertNotIn("expected_value_summary", expectation.metadata)
        self.assertEqual(expectation.confidence, "heuristic")

    def test_overlong_and_missing_expected_values_are_omitted(self):
        overlong = only(self.observations, "zunit.expectation", 5)
        self.assertEqual(overlong.metadata["expected_value_kind"], "omitted")
        self.assertEqual(overlong.metadata["dynamic_reason"], "long_expected_value")
        self.assertFalse(overlong.metadata["raw_expected_value_stored"])
        self.assertEqual(overlong.confidence, "extracted")

        partial = only(self.observations, "zunit.assertion", 6)
        self.assertEqual(partial.metadata["mode"], "partial")
        missing = only(self.observations, "zunit.expectation", 6)
        self.assertEqual(missing.metadata["matcher"], "contains")
        self.assertEqual(missing.metadata["expected_value_kind"], "omitted")
        self.assertFalse(missing.metadata["raw_expected_value_stored"])

        payload = json.dumps([item.to_dict() for item in self.observations], sort_keys=True)
        self.assertNotIn(LONG_VALUE, payload)
        assert_static_only(self, self.observations)


class ZunitMockAndReasonContractTests(unittest.TestCase):
    def test_mock_behavior_kind_follows_the_declared_option_or_argument(self):
        observations = extract(
            "mock_command git --stderr oops",
            "stub_command git --status 1",
            "mock_command git ./fixtures/out.txt",
            'mock_command git "$canned_text"',
            "stub_command git",
            "mock_command",
        )

        expected = {
            1: ("zunit.mock", "stderr"), 2: ("zunit.stub", "status"),
            3: ("zunit.mock", "file"), 4: ("zunit.mock", "dynamic"),
            5: ("zunit.stub", "unknown"),
        }
        for line_number, (kind, behavior) in expected.items():
            item = only(observations, kind, line_number)
            self.assertEqual(item.name, "git")
            self.assertEqual(item.metadata["target_command"], "git")
            self.assertEqual(item.metadata["behavior_kind"], behavior)
            self.assertFalse(item.metadata["target_executed"] or item.metadata["command_executed"])
        bare = only(observations, "zunit.mock", 6)
        self.assertEqual(bare.name, "[dynamic]")
        self.assertEqual(bare.confidence, "unknown")
        self.assertEqual(bare.metadata["dynamic_reason"], "missing_command")
        self.assertEqual(bare.metadata["behavior_kind"], "unknown")
        self.assertEqual(bare.metadata["argument_count"], 0)
        self.assertNotIn("target_command", bare.metadata)
        assert_static_only(self, observations)

    def test_skip_and_todo_reasons_are_omitted_dynamic_or_bounded(self):
        observations = extract(
            'test "reasons" {',
            "  skip",
            '  todo "$why_text"',
            f'  skip "{LONG_VALUE}"',
            "}",
        )

        omitted = only(observations, "zunit.skip", 2)
        self.assertEqual(omitted.metadata["reason_kind"], "omitted")
        self.assertFalse(omitted.metadata["raw_value_stored"])
        self.assertEqual(omitted.confidence, "extracted")
        self.assertNotIn("reason_summary", omitted.metadata)

        dynamic = only(observations, "zunit.todo", 3)
        self.assertEqual(dynamic.metadata["reason_kind"], "dynamic")
        self.assertEqual(dynamic.metadata["dynamic_reason"], "computed_reason")
        self.assertFalse(dynamic.metadata["raw_value_stored"])
        self.assertEqual(dynamic.confidence, "heuristic")
        self.assertFalse(dynamic.metadata["todo_executed"])

        overlong = only(observations, "zunit.skip", 4)
        self.assertEqual(overlong.metadata["reason_kind"], "omitted")
        self.assertEqual(overlong.metadata["dynamic_reason"], "long_reason")
        self.assertFalse(overlong.metadata["raw_value_stored"])
        self.assertFalse(overlong.metadata["skip_executed"] or overlong.metadata["test_status_known"])
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertNotIn(LONG_VALUE, payload)
        assert_static_only(self, observations)


if __name__ == "__main__":
    unittest.main()
