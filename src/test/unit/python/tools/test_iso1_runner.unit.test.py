from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import run_tests as run_tests

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_run_tests():
    return run_tests


def test_int_suite_dispatches_integration_population_only():
    run_tests = load_run_tests()
    args = SimpleNamespace(suite="int")
    with (
        patch.object(run_tests, "require_integration_sandbox"),
        patch.object(run_tests, "prepare_go_test_environment"),
        patch.object(run_tests, "run_pytest_suites", return_value=0) as pytest_run,
    ):
        assert run_tests.run_selected_suites(args, [], None) == 0

    assert pytest_run.call_args.args[1] == ("int",)


def test_staging_suite_runs_smoke_then_integration_only():
    run_tests = load_run_tests()
    args = SimpleNamespace(suite="staging")
    with (
        patch.object(run_tests, "require_integration_sandbox"),
        patch.object(run_tests, "prepare_go_test_environment"),
        patch.object(run_tests, "run_pytest_suites", return_value=0) as pytest_run,
        patch.object(run_tests, "run_smoke_suite", return_value=0) as smoke,
    ):
        assert run_tests.run_selected_suites(args, [], object()) == 0

    assert pytest_run.call_args.args[1] == ("int",)
    smoke.assert_called_once()


def test_exact_parameterized_int_node_is_forwarded_unchanged():
    run_tests = load_run_tests()
    node = "src/test/int/python/pkg/file.int.test.py::test_case[param]"
    assert run_tests.build_pytest_args(("int",), [node]) == [node]


def test_exact_unit_file_selector_is_forwarded_unchanged():
    run_tests = load_run_tests()
    selector = "src/test/unit/python/pkg/file.unit.test.py"
    assert run_tests.build_pytest_args(("unit",), [selector]) == [selector]


def test_exact_unit_node_selector_is_forwarded_unchanged():
    run_tests = load_run_tests()
    selector = "src/test/unit/python/pkg/file.unit.test.py::test_contract"
    assert run_tests.build_pytest_args(("unit",), [selector]) == [selector]


def test_multiple_exact_selectors_remain_ordered():
    run_tests = load_run_tests()
    selectors = [
        "src/test/unit/python/pkg/first.unit.test.py::test_first",
        "src/test/unit/python/pkg/second.unit.test.py::test_second[param]",
    ]
    assert run_tests.build_pytest_args(("unit",), selectors) == selectors


@pytest.mark.parametrize(
    ("suite", "selector"),
    [
        ("unit", "src/test/int/python/pkg/file.int.test.py::test_contract"),
        ("int", "src/test/unit/python/pkg/file.unit.test.py::test_contract"),
        ("unit", "tools/test_outside_suite.py::test_contract"),
    ],
)
def test_exact_selector_must_be_beneath_selected_suite_root(suite, selector):
    run_tests = load_run_tests()
    with pytest.raises(RuntimeError, match="outside selected suite root"):
        run_tests.build_pytest_args((suite,), [selector])


@pytest.mark.parametrize("explicit_sandbox", [False, True])
def test_host_int_dispatches_before_allocating_canonical_inner_run(explicit_sandbox):
    run_tests = load_run_tests()
    argv = ["--suite", "int", "--no-coverage"]
    if explicit_sandbox:
        argv.insert(2, "--sandbox")
    with (
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=17) as dispatch,
        patch.object(run_tests, "establish_test_scratch") as establish,
        patch.object(run_tests, "prepare_go_test_environment") as prepare_go,
        patch.object(run_tests, "import_pytest") as import_pytest,
    ):
        assert run_tests.main(argv) == 17

    dispatch.assert_called_once_with(dispatch.call_args.args[0], argv)
    establish.assert_not_called()
    prepare_go.assert_not_called()
    import_pytest.assert_not_called()


@pytest.mark.parametrize(
    ("suite", "raw_argv"),
    [
        ("int", ["--suite", "int", "--", "first::node[param]", "second::node"]),
        ("staging", ["--suite", "staging"]),
    ],
)
def test_host_integration_suites_auto_dispatch_with_exact_argv(suite, raw_argv):
    run_tests = load_run_tests()
    args = SimpleNamespace(suite=suite, sandbox=False)
    with (
        patch("test_sandbox.active_sandbox", return_value=False),
        patch("test_sandbox.ensure_sandbox_image", return_value="sha256:" + "a" * 64),
        patch("test_sandbox.run_in_sandbox", return_value=19) as run_in_sandbox,
        patch("repomap_test_support.unit_purity.require_live_resource_allowed"),
    ):
        assert run_tests.integration_sandbox_dispatch(args, raw_argv) == 19

    run_in_sandbox.assert_called_once_with(
        raw_argv,
        repo_root=run_tests.REPO_ROOT,
        image_id="sha256:" + "a" * 64,
    )


def test_authenticated_inner_integration_invocation_does_not_redispatch():
    run_tests = load_run_tests()
    args = SimpleNamespace(suite="int", sandbox=False)
    with (
        patch("test_sandbox.active_sandbox", return_value=True),
        patch("test_sandbox.ensure_sandbox_image") as ensure_image,
        patch("test_sandbox.run_in_sandbox") as run_in_sandbox,
    ):
        assert run_tests.integration_sandbox_dispatch(args, ["--suite", "int"]) is None

    ensure_image.assert_not_called()
    run_in_sandbox.assert_not_called()


def test_direct_integration_conftest_import_refuses_before_fixture_setup():
    conftest_path = REPO_ROOT / 'src' / 'test' / 'int' / 'python' / 'conftest.py'
    spec = importlib.util.spec_from_file_location('conftest', conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch('test_sandbox.active_sandbox', return_value=False), patch('repomap_test_support.postgres_harness.postgres_container_session') as postgres, pytest.raises(pytest.exit.Exception, match='authenticated container sandbox'):
        spec.loader.exec_module(module)
    postgres.assert_not_called()


def test_unit_inspection_import_of_integration_conftest_does_not_activate_guard():
    conftest_path = REPO_ROOT / 'src' / 'test' / 'int' / 'python' / 'conftest.py'
    spec = importlib.util.spec_from_file_location('repomap_int_conftest_inspection', conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch('test_sandbox.active_sandbox', return_value=False) as active, patch('repomap_test_support.postgres_harness.postgres_container_session') as postgres:
        spec.loader.exec_module(module)
    active.assert_not_called()
    postgres.assert_not_called()



def test_no_selector_unit_and_int_keep_canonical_roots_and_coverage_policy():
    run_tests = load_run_tests()
    assert run_tests.build_pytest_args(("unit",), []) == [
        str(run_tests.TEST_ROOTS["unit"])
    ]
    assert run_tests.build_pytest_args(("int",), []) == [
        str(run_tests.TEST_ROOTS["int"])
    ]

    staging_policy = run_tests.coverage_policy_for_suite("staging")
    assert staging_policy.line_hard_threshold == 80.0
    assert staging_policy.branch_hard_threshold == 80.0

    unit_policy = run_tests.coverage_policy_for_suite("unit")
    assert unit_policy.line_hard_threshold == 85.0
    assert unit_policy.branch_hard_threshold == 85.0

    int_policy = run_tests.coverage_policy_for_suite("int")
    assert int_policy.line_hard_threshold == 80.0
    assert int_policy.branch_hard_threshold == 80.0

    override_policy = run_tests.coverage_policy_for_suite("int", threshold_override=60.0)
    assert override_policy.line_hard_threshold == 60.0
    assert override_policy.branch_hard_threshold == 60.0


def test_no_coverage_skips_complete_source_coverage_gate():
    run_tests = load_run_tests()
    args = SimpleNamespace(
        suite="unit",
        threshold=None,
        jobs="1",
        no_coverage=True,
        report=False,
    )
    pytest_module = SimpleNamespace(
        ExitCode=SimpleNamespace(NO_TESTS_COLLECTED=5),
    )
    with (
        patch.object(run_tests, "import_pytest", return_value=pytest_module),
        patch.object(run_tests, "run_pytest", return_value=0),
        patch.object(
            run_tests,
            "import_coverage",
            side_effect=AssertionError("coverage must stay disabled"),
        ),
        patch.object(
            run_tests,
            "collect_coverage_summary",
            side_effect=AssertionError("coverage gate must stay disabled"),
        ),
    ):
        assert run_tests.run_pytest_suites(args, ("unit",), []) == 0


def test_no_tests_collected_remains_runner_failure():
    run_tests = load_run_tests()
    args = SimpleNamespace(
        suite="unit",
        threshold=None,
        jobs="1",
        no_coverage=True,
        report=False,
    )
    pytest_module = SimpleNamespace(
        ExitCode=SimpleNamespace(NO_TESTS_COLLECTED=5),
    )
    with (
        patch.object(run_tests, "import_pytest", return_value=pytest_module),
        patch.object(run_tests, "run_pytest", return_value=5),
    ):
        assert run_tests.run_pytest_suites(args, ("unit",), []) == 2


def test_int_suite_run_keeps_containerized_postgres_environment(
    monkeypatch,
):
    run_tests = load_run_tests()
    args = SimpleNamespace(pg_container_runtime="docker", pg_container_port=55433)
    monkeypatch.delenv("REPOMAP_TEST_PG_CONTAINER_RUNTIME", raising=False)
    monkeypatch.delenv("REPOMAP_TEST_PG_CONTAINER_PORT", raising=False)

    with run_tests.pytest_environment_for(("int",), args):
        assert os.environ["REPOMAP_TEST_PG_CONTAINER_RUNTIME"] == "docker"
        assert os.environ["REPOMAP_TEST_PG_CONTAINER_PORT"] == "55433"

    assert "REPOMAP_TEST_PG_CONTAINER_RUNTIME" not in os.environ
    assert "REPOMAP_TEST_PG_CONTAINER_PORT" not in os.environ


def test_unit_purity_guard_refuses_accidental_outer_sandbox(monkeypatch):
    run_tests = load_run_tests()
    args = SimpleNamespace(suite="int", sandbox=True)
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "1")
    with patch("test_sandbox.active_sandbox", return_value=False):
        assert run_tests.integration_sandbox_dispatch(args, ["--suite", "int", "--sandbox"]) == 2


def test_recording_plugin_marks_only_unit_items_for_purity_guard(monkeypatch):
    run_tests = load_run_tests()
    plugin = run_tests.RecordingPytestPlugin(suite="staging", full_population=True)
    unit_item = SimpleNamespace(path=run_tests.TEST_ROOTS["unit"] / "pkg" / "x.unit.test.py")
    int_item = SimpleNamespace(path=run_tests.TEST_ROOTS["int"] / "pkg" / "x.int.test.py")
    monkeypatch.delenv("REPOMAP_UNIT_PURITY_GUARD", raising=False)

    plugin.pytest_runtest_protocol(unit_item, None)
    assert os.environ["REPOMAP_UNIT_PURITY_GUARD"] == "1"
    plugin.pytest_runtest_logreport(SimpleNamespace(when="teardown", failed=False))
    assert "REPOMAP_UNIT_PURITY_GUARD" not in os.environ

    plugin.pytest_runtest_protocol(int_item, None)
    assert "REPOMAP_UNIT_PURITY_GUARD" not in os.environ
    plugin.pytest_runtest_logreport(SimpleNamespace(when="teardown", failed=False))
