from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.graph.keys import (
    awk_function_key, awk_program_key, bash_function_key, bash_script_key,
    bats_expectation_key, bats_file_key, bats_test_case_key,
    env_key, external_key, external_url_key, file_key, host_category_key, tool_key,
    zsh_function_key, zsh_script_key, zunit_command_under_test_key,
    zunit_file_key, zunit_suite_key, zunit_test_case_key,
)


def _obs(
    kind: str, path: str, *, name: str | None = None, target: str | None = None,
    metadata: dict[str, Any] | None = None, start_line: int | None = None,
) -> RawObservation:
    end_line = start_line if start_line is not None else None
    return RawObservation(
        kind=kind, source_id=f"{path}#{kind}:{name or 'target'}", path=path,
        name=name, target=target, confidence="extracted", extractor="test",
        extractor_version="1.0.0", metadata=metadata or {}, start_line=start_line, end_line=end_line,
    )


def _edges(result: Any) -> set[tuple[str, str, str]]:
    return {(e.source_key, e.kind, e.target_key) for e in result.graph.edges}


class General1ShellContractsUnitTests(unittest.TestCase):
    """Public contract tests for Shell family canonicalization and authority behaviors."""

    def test_shell_graph_key_error_refusals(self) -> None:
        """Graph key errors in shell families emit error diagnostics, ok=False, and no edges."""
        cases = [
            (_obs("zsh.script", "../escape.zsh"), "repo_escaping_path"),
            (_obs("awk.program", "../escape.awk"), "repo_escaping_path"),
            (_obs("shell.script", "../escape.sh", metadata={"dialect": "bash"}), "repo_escaping_path"),
            (_obs("zunit.file", "../escape.zunit"), "repo_escaping_path"),
            (_obs("bats.file", "../escape.bats"), "repo_escaping_path"),
            (_obs("bats.load", "test.bats", target="file:bad%ZZkey"), "malformed_percent_escape"),
            (_obs("bats.fixture_reference", "test.bats", target="file:bad key with spaces", metadata={"fixture_kind": "repo_fixture"}), "malformed_percent_escape"),
        ]
        for obs, expected_cat in cases:
            with self.subTest(kind=obs.kind, expected_category=expected_cat):
                res = canonicalize_observations([obs])
                self.assertFalse(res.ok)
                self.assertEqual(len(res.diagnostics), 1)
                self.assertEqual(res.diagnostics[0].severity, "error")
                self.assertEqual(res.diagnostics[0].category, expected_cat)
                self.assertEqual(len(res.graph.edges), 0)

    def test_bash_diagnostics_and_reference_contracts(self) -> None:
        """Bash emits warnings for missing metadata and routes reference targets deterministically."""
        warn_cases = [
            (_obs("shell.function", "app.sh", metadata={"dialect": "bash"}), "Bash function observation requires a function name"),
            (_obs("shell.command", "app.sh", metadata={"dialect": "bash"}), "Bash command observation requires a command name"),
            (_obs("shell.env_read", "app.sh", metadata={"dialect": "bash"}), "Bash environment observation requires variable metadata"),
            (_obs("shell.host_mutation", "app.sh", metadata={"dialect": "bash"}), "Bash host mutation observation requires mutation category"),
        ]
        for obs, expected_msg in warn_cases:
            with self.subTest(kind=obs.kind):
                res = canonicalize_observations([obs])
                self.assertTrue(res.ok)
                self.assertEqual(len(res.diagnostics), 1)
                self.assertEqual(res.diagnostics[0].severity, "warning")
                self.assertEqual(res.diagnostics[0].category, "missing_required_metadata")
                self.assertIn(expected_msg, res.diagnostics[0].message)
                self.assertEqual(len(res.graph.edges), 0)

        fallbacks = [
            _obs("shell.source", "app.sh", metadata={"dialect": "bash"}),
            _obs("shell.file_read", "app.sh", metadata={"dialect": "bash", "target_kind": "dynamic"}),
            _obs("shell.file_write", "app.sh", metadata={"dialect": "bash", "target_kind": "static", "target_display": "/etc/hosts"}),
            _obs("shell.network_call", "app.sh", metadata={"dialect": "bash", "target_kind": "dynamic"}),
            _obs("shell.package_manager", "app.sh", metadata={"dialect": "bash"}),
        ]
        for obs in fallbacks:
            with self.subTest(fallback_kind=obs.kind):
                res_fb = canonicalize_observations([obs])
                self.assertTrue(res_fb.ok)
                self.assertEqual(len(res_fb.graph.edges), 0)
                self.assertEqual(len(res_fb.graph.evidence), 1)

        valid_obs = [
            _obs("shell.script", "app.sh", metadata={"dialect": "bash"}),
            _obs("shell.function", "app.sh", name="deploy", metadata={"dialect": "bash"}),
            _obs("shell.command", "app.sh", name="git", metadata={"dialect": "bash"}),
            _obs("shell.source", "app.sh", metadata={"dialect": "bash", "resolved_path": "common.sh"}),
            _obs("shell.env_read", "app.sh", name="HOME", metadata={"dialect": "bash"}),
            _obs("shell.network_call", "app.sh", metadata={"dialect": "bash", "target_kind": "static", "target_display": "https://example.com/api"}),
            _obs("shell.network_call", "app.sh", metadata={"dialect": "bash", "target_kind": "static", "target_display": "api.example.invalid"}),
            _obs("shell.package_manager", "app.sh", name="apt", metadata={"dialect": "bash"}),
        ]
        res_val = canonicalize_observations(valid_obs)
        self.assertTrue(res_val.ok, res_val.diagnostics)
        edges = _edges(res_val)
        self.assertIn((file_key("app.sh"), "defines", bash_script_key("app.sh")), edges)
        self.assertIn((bash_script_key("app.sh"), "defines", bash_function_key("app.sh", "deploy")), edges)
        self.assertIn((file_key("app.sh"), "executes", tool_key("git")), edges)
        self.assertIn((bash_script_key("app.sh"), "sources", file_key("common.sh")), edges)
        self.assertIn((file_key("app.sh"), "reads_env", env_key("HOME")), edges)
        self.assertIn((file_key("app.sh"), "references", external_url_key("https://example.com/api")), edges)
        self.assertIn((file_key("app.sh"), "references", external_key("shell.network", "api.example.invalid")), edges)
        self.assertIn((file_key("app.sh"), "uses_package_manager", tool_key("apt")), edges)

    def test_zsh_contracts_and_fallbacks(self) -> None:
        """Zsh canonicalization produces typed edges and handles dynamic fallbacks safely."""
        fallbacks = [
            _obs("zsh.autoload", "init.zsh", metadata={"target_kind": "dynamic"}),
            _obs("zsh.autoload", "init.zsh", metadata={"target_kind": "static", "function_names": "not_list"}),
            _obs("zsh.zmodload", "init.zsh", name="[dynamic]", metadata={"target_kind": "static"}),
            _obs("zsh.zmodload", "init.zsh", name="list", metadata={"target_kind": "static"}),
            _obs("zsh.completion_function", "init.zsh"),
            _obs("zsh.plugin_manager", "init.zsh", name="[dynamic]"),
            _obs("zsh.plugin", "init.zsh", name="[unknown]"),
            _obs("shell.env_read", "init.zsh", metadata={"dialect": "zsh"}),
            _obs("shell.file_read", "init.zsh", metadata={"dialect": "zsh", "target_kind": "static", "target_display": "/etc/passwd"}),
            _obs("shell.network_call", "init.zsh", name="curl", metadata={"dialect": "zsh", "target_kind": "static", "target_display": "x" * 150}),
            _obs("shell.package_manager", "init.zsh", metadata={"dialect": "zsh"}),
            _obs("shell.host_mutation", "init.zsh", metadata={"dialect": "zsh"}),
        ]
        for obs in fallbacks:
            with self.subTest(zsh_fallback=obs.kind):
                res_fb = canonicalize_observations([obs])
                self.assertTrue(res_fb.ok)
                self.assertEqual(len(res_fb.graph.edges), 0)
                self.assertEqual(len(res_fb.graph.evidence), 1)

        valid_obs = [
            _obs("zsh.script", "init.zsh"),
            _obs("zsh.startup_file", "init.zsh", name="zshrc"),
            _obs("shell.function", "init.zsh", name="my_fn", metadata={"dialect": "zsh"}),
            _obs("zsh.autoload", "init.zsh", metadata={"target_kind": "static", "function_names": ["compinit"]}),
            _obs("zsh.zmodload", "init.zsh", name="zsh/stat", metadata={"target_kind": "static"}),
            _obs("zsh.completion_function", "init.zsh", name="_mytool"),
            _obs("zsh.plugin_manager", "init.zsh", name="zinit"),
            _obs("zsh.plugin", "init.zsh", name="zsh-completions", metadata={"manager": "zinit"}),
            _obs("shell.network_call", "init.zsh", name="curl", metadata={"dialect": "zsh", "target_kind": "static", "target_display": "[dynamic]"}),
            _obs("shell.package_manager", "init.zsh", name="brew", metadata={"dialect": "zsh"}),
            _obs("shell.host_mutation", "init.zsh", metadata={"dialect": "zsh", "mutation_category": "cron"}),
        ]
        res = canonicalize_observations(valid_obs)
        self.assertTrue(res.ok, res.diagnostics)
        edges = _edges(res)
        script_k = zsh_script_key("init.zsh")
        self.assertIn((file_key("init.zsh"), "defines", script_k), edges)
        self.assertIn((script_k, "configures", external_key("zsh.startup_file", "zshrc")), edges)
        self.assertIn((script_k, "defines", zsh_function_key("init.zsh", "my_fn")), edges)
        self.assertIn((script_k, "configures", external_key("zsh.autoload", "compinit")), edges)
        self.assertIn((script_k, "uses_zsh_module", external_key("zsh.module", "zsh/stat")), edges)
        self.assertIn((script_k, "completion_for", external_key("zsh.completion", "_mytool")), edges)
        self.assertIn((script_k, "uses_plugin_manager", external_key("zsh.plugin_manager", "zinit")), edges)
        self.assertIn((script_k, "uses_plugin", external_key("zsh.plugin", "zinit:zsh-completions")), edges)
        self.assertIn((script_k, "network_intent", external_key("zsh.network_intent", "curl")), edges)
        self.assertIn((script_k, "package_intent", external_key("zsh.package_manager", "brew")), edges)
        self.assertIn((script_k, "host_mutation_intent", host_category_key("cron")), edges)

    def test_awk_contracts_and_fallbacks(self) -> None:
        """AWK canonicalization validates static program semantics and falls back on dynamic."""
        fallbacks = [
            _obs("awk.function", "calc.awk"),
            _obs("awk.builtin_call", "calc.awk"),
            _obs("awk.user_function_call", "calc.awk"),
            _obs("awk.file_read", "calc.awk", metadata={"target_kind": "dynamic"}),
            _obs("awk.file_read", "calc.awk", metadata={"target_kind": "static", "target_display": "/etc/passwd"}),
            _obs("awk.file_write", "calc.awk", metadata={"target_kind": "static", "target_display": "../escape.txt"}),
            _obs("awk.system_call", "calc.awk", metadata={"command_text_kind": "dynamic"}),
            _obs("awk.system_call", "calc.awk", metadata={"command_text_kind": "static", "command_summary": "[dynamic]"}),
            _obs("awk.pipe_read", "calc.awk", metadata={"command_text_kind": "static", "command_summary": "echo\nline"}),
            _obs("awk.pipe_write", "calc.awk", metadata={"command_text_kind": "static", "command_summary": "x" * 90}),
            _obs("awk.include", "calc.awk", metadata={"target_kind": "dynamic"}),
            _obs("awk.include", "calc.awk", metadata={"target_kind": "static", "resolved_path": "/abs/inc.awk"}),
            _obs("awk.include", "calc.awk", metadata={"target_kind": "static", "resolved_path": "../parent.awk"}),
            _obs("awk.extension", "calc.awk"),
            _obs("awk.extension", "calc.awk", name="ord", metadata={"target_kind": "dynamic"}),
        ]
        for obs in fallbacks:
            with self.subTest(awk_fallback=obs.kind):
                res_fb = canonicalize_observations([obs])
                self.assertTrue(res_fb.ok)
                self.assertEqual(len(res_fb.graph.edges), 0)
                self.assertEqual(len(res_fb.graph.evidence), 1)

        valid_obs = [
            _obs("awk.program", "calc.awk"),
            _obs("awk.function", "calc.awk", name="add"),
            _obs("awk.builtin_call", "calc.awk", name="length"),
            _obs("awk.user_function_call", "calc.awk", name="add"),
            _obs("awk.file_read", "calc.awk", metadata={"target_kind": "static", "target_display": "in.txt"}),
            _obs("awk.system_call", "calc.awk", metadata={"command_text_kind": "static", "command_summary": "date"}),
            _obs("awk.pipe_read", "calc.awk", metadata={"command_text_kind": "static", "command_summary": "sort"}),
            _obs("awk.include", "calc.awk", metadata={"target_kind": "static", "resolved_path": "lib/math.awk"}),
            _obs("awk.extension", "calc.awk", name="json", metadata={"target_kind": "static"}),
        ]
        res = canonicalize_observations(valid_obs)
        self.assertTrue(res.ok, res.diagnostics)
        edges = _edges(res)
        prog_k = awk_program_key("calc.awk")
        self.assertIn((file_key("calc.awk"), "defines", prog_k), edges)
        self.assertIn((prog_k, "defines", awk_function_key("calc.awk", "add")), edges)
        self.assertIn((prog_k, "uses_builtin", external_key("awk.builtin", "length")), edges)
        self.assertIn((prog_k, "calls", awk_function_key("calc.awk", "add")), edges)
        self.assertIn((prog_k, "reads", file_key("in.txt")), edges)
        self.assertIn((prog_k, "system_command_intent", external_key("awk.command_intent", "date")), edges)
        self.assertIn((prog_k, "pipe_command_intent", external_key("awk.command_intent", "sort")), edges)
        self.assertIn((prog_k, "includes", file_key("lib/math.awk")), edges)
        self.assertIn((prog_k, "depends_on", external_key("awk.extension", "json")), edges)

    def test_zunit_context_authority_and_contracts(self) -> None:
        """Zunit routes context ownership correctly and suppresses dynamic/redacted artifacts."""
        fallbacks = [
            _obs("zunit.suite", "suite.zunit", name="S", metadata={"suite_name_kind": "dynamic"}),
            _obs("zunit.suite", "suite.zunit", name="S", metadata={"suite_name_kind": "static", "suite_name_redacted": True}),
            _obs("zunit.test_case", "suite.zunit", name="T", metadata={"test_name_kind": "dynamic"}),
            _obs("zunit.test_case", "suite.zunit", name="T", metadata={"test_name_kind": "static", "test_name_redacted": True}),
            _obs("zunit.hook", "suite.zunit", name="[dynamic]"),
            _obs("zunit.helper", "suite.zunit", metadata={"target_kind": "dynamic"}),
            _obs("zunit.fixture_reference", "suite.zunit", metadata={"target_kind": "dynamic"}),
            _obs("zunit.command_under_test", "suite.zunit", name="grep", metadata={"target_kind": "dynamic"}),
            _obs("zunit.command_under_test", "suite.zunit", name="[dynamic]", metadata={"target_kind": "command"}),
            _obs("zunit.assertion", "suite.zunit", name="[dynamic]"),
            _obs("zunit.expectation", "suite.zunit", metadata={"expectation_kind": "dynamic"}),
            _obs("zunit.expectation", "suite.zunit", metadata={"expectation_kind": "redacted"}),
            _obs("zunit.mock", "suite.zunit", name="curl", metadata={"target_kind": "dynamic"}),
            _obs("zunit.stub", "suite.zunit", name="curl", metadata={"target_kind": "dynamic"}),
        ]
        for obs in fallbacks:
            with self.subTest(zunit_fallback=obs.kind):
                res_fb = canonicalize_observations([obs])
                self.assertTrue(res_fb.ok)
                self.assertEqual(len(res_fb.graph.edges), 0)
                self.assertEqual(len(res_fb.graph.evidence), 1)

        tc_in_suite = _obs("zunit.test_case", "suite.zunit", name="t1", metadata={"test_name_kind": "static", "enclosing_suite": "Core"})
        tc_no_suite = _obs("zunit.test_case", "suite.zunit", name="t2", metadata={"test_name_kind": "static"})
        res_tc = canonicalize_observations([tc_in_suite, tc_no_suite])
        edges_tc = _edges(res_tc)
        self.assertIn((zunit_suite_key("suite.zunit", "Core"), "has_test_case", zunit_test_case_key("suite.zunit", "t1")), edges_tc)
        self.assertIn((zunit_file_key("suite.zunit"), "contains", zunit_test_case_key("suite.zunit", "t2")), edges_tc)

        fix_tc = _obs("zunit.fixture_reference", "suite.zunit", metadata={"target_kind": "static", "resolved_path": "f1.json", "enclosing_test": "t1"})
        fix_suite = _obs("zunit.fixture_reference", "suite.zunit", metadata={"target_kind": "static", "resolved_path": "f2.json", "enclosing_suite": "Core"})
        fix_file = _obs("zunit.fixture_reference", "suite.zunit", metadata={"target_kind": "static", "resolved_path": "f3.json"})
        res_fix = canonicalize_observations([fix_tc, fix_suite, fix_file])
        edges_fix = _edges(res_fix)
        self.assertIn((zunit_test_case_key("suite.zunit", "t1"), "uses_fixture", file_key("f1.json")), edges_fix)
        self.assertIn((zunit_suite_key("suite.zunit", "Core"), "uses_fixture", file_key("f2.json")), edges_fix)
        self.assertIn((zunit_file_key("suite.zunit"), "uses_fixture", file_key("f3.json")), edges_fix)

        cut = _obs("zunit.command_under_test", "suite.zunit", name="grep", start_line=5, metadata={"target_kind": "command", "command_name": "grep", "enclosing_test": "t1"})
        res_cut = canonicalize_observations([cut])
        self.assertIn((zunit_test_case_key("suite.zunit", "t1"), "command_under_test", tool_key("grep")), _edges(res_cut))
        node_keys = {n.canonical_key for n in res_cut.graph.nodes}
        self.assertIn(zunit_command_under_test_key("suite.zunit", 5, "grep"), node_keys)
        self.assertIn(tool_key("grep"), node_keys)

    def test_bats_context_authority_and_contracts(self) -> None:
        """Bats routes test-case context authority and models assertion semantics."""
        fallbacks = [
            _obs("bats.test_case", "suite.bats", name="T", metadata={"test_name_kind": "dynamic"}),
            _obs("bats.test_case", "suite.bats", name="T", metadata={"test_name_kind": "static", "test_name_redacted": True}),
            _obs("bats.load", "suite.bats", target="not_file:lib"),
            _obs("bats.library_load", "suite.bats", metadata={"target_kind": "dynamic", "library_name": "lib"}),
            _obs("bats.run", "suite.bats", name="grep", metadata={"command_kind": "dynamic"}),
            _obs("bats.run", "suite.bats", name="[dynamic]", metadata={"command_kind": "static"}),
            _obs("bats.assertion", "suite.bats", name="assert_success"),
            _obs("bats.assertion", "suite.bats", metadata={"test_case_name": "t1"}),
            _obs("bats.fixture_reference", "suite.bats", target="file:f.txt", metadata={"fixture_kind": "external"}),
            _obs("bats.helper_reference", "suite.bats"),
        ]
        for obs in fallbacks:
            with self.subTest(bats_fallback=obs.kind):
                res_fb = canonicalize_observations([obs])
                self.assertTrue(res_fb.ok)
                self.assertEqual(len(res_fb.graph.edges), 0)
                self.assertEqual(len(res_fb.graph.evidence), 1)

        run_tc = _obs("bats.run", "suite.bats", name="grep", metadata={"command_kind": "static", "command_token": "grep", "test_context": "test_case", "test_case_name": "t1"})
        run_file = _obs("bats.run", "suite.bats", name="awk", metadata={"command_kind": "static", "command_token": "awk"})
        res_run = canonicalize_observations([run_tc, run_file])
        edges_run = _edges(res_run)
        self.assertIn((bats_test_case_key("suite.bats", "t1"), "tests_command", tool_key("grep")), edges_run)
        self.assertIn((bats_file_key("suite.bats"), "tests_command", tool_key("awk")), edges_run)

        obs_assert = _obs("bats.assertion", "suite.bats", start_line=10, metadata={"assertion_name": "assert_output", "test_case_name": "t1"})
        obs_refute = _obs("bats.refutation", "suite.bats", start_line=15, metadata={"assertion_name": "refute_output", "test_case_name": "t1"})
        res_eval = canonicalize_observations([obs_assert, obs_refute])
        edges_eval = _edges(res_eval)
        self.assertIn((bats_file_key("suite.bats"), "asserts", bats_expectation_key("suite.bats", "t1", 10, "assert_output")), edges_eval)
        self.assertIn((bats_file_key("suite.bats"), "refutes", bats_expectation_key("suite.bats", "t1", 15, "refute_output")), edges_eval)
