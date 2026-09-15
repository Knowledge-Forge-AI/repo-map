"""REPOMAP-CI2A-R1 staged runner topology contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

import pytest

import run_tests as run_tests

ROOT = Path(__file__).resolve().parents[5]


def _load_run_tests():
    return run_tests


def test_ci2a_r1_per_suite_coverage_policy_is_hard_and_independent() -> None:
    run_tests = _load_run_tests()

    unit = run_tests.coverage_policy_for_suite("unit")
    integration = run_tests.coverage_policy_for_suite("int")
    staging = run_tests.coverage_policy_for_suite("staging")

    assert (unit.line_hard_threshold, unit.branch_hard_threshold) == (85.0, 85.0)
    assert (integration.line_hard_threshold, integration.branch_hard_threshold) == (
        80.0,
        80.0,
    )
    assert (staging.line_hard_threshold, staging.branch_hard_threshold) == (80.0, 80.0)
    assert not hasattr(run_tests, "DEFAULT_ALL_HARD_THRESHOLD")


def test_ci2a_r1_integration_population_does_not_recompute_unit_contracts() -> None:
    violations = []
    integration_root = ROOT / "src/test/int/python"
    for path in sorted(integration_root.rglob("*.test.py")):
        source = path.read_text(encoding="utf-8")
        if "load_unit_contract_class(" in source or "unit_reuse" in path.name:
            violations.append(path.relative_to(ROOT).as_posix())

    assert violations == []


def test_ci2a_r1_staging_runs_smoke_before_integration() -> None:
    run_tests = _load_run_tests()
    args = SimpleNamespace(suite="staging")
    events: list[str] = []

    def record(event: str) -> int:
        events.append(event)
        return 0

    with (
        patch.object(run_tests, "require_integration_sandbox"),
        patch.object(
            run_tests,
            "run_smoke_suite",
            side_effect=lambda *_args: record("smoke"),
        ),
        patch.object(
            run_tests,
            "prepare_go_test_environment",
            side_effect=lambda *_args: record("prepare-go"),
        ),
        patch.object(
            run_tests,
            "run_pytest_suites",
            side_effect=lambda *_args: record("integration"),
        ),
    ):
        result = run_tests.run_selected_suites(args, [], None)

    assert result == 0
    assert events == ["smoke", "prepare-go", "integration"]


def test_ci2a_r1_staging_smoke_failure_is_fail_fast() -> None:
    run_tests = _load_run_tests()
    args = SimpleNamespace(suite="staging")

    with (
        patch.object(run_tests, "require_integration_sandbox"),
        patch.object(run_tests, "run_smoke_suite", return_value=17),
        patch.object(run_tests, "prepare_go_test_environment") as prepare,
        patch.object(run_tests, "run_pytest_suites") as integration,
    ):
        result = run_tests.run_selected_suites(args, [], None)

    assert result == 17
    prepare.assert_not_called()
    integration.assert_not_called()


def test_ci2a_r1_retired_all_suite_is_not_a_public_choice() -> None:
    run_tests = _load_run_tests()

    with pytest.raises(SystemExit) as caught:
        run_tests.main(["--suite", "all"])

    assert caught.value.code == 2


def test_ci2a_r1_staging_dispatches_to_the_owned_sandbox(monkeypatch) -> None:
    run_tests = _load_run_tests()
    args = SimpleNamespace(suite="staging", sandbox=True)
    monkeypatch.setattr("test_sandbox.active_sandbox", lambda: False)
    monkeypatch.setattr("test_sandbox.ensure_sandbox_image", lambda **_kwargs: "image")
    dispatched = Mock(return_value=23)
    monkeypatch.setattr("test_sandbox.run_in_sandbox", dispatched)
    monkeypatch.setattr(
        "repomap_test_support.unit_purity.require_live_resource_allowed",
        lambda _label: None,
    )

    assert (
        run_tests.integration_sandbox_dispatch(
            args,
            ["--suite", "staging", "--sandbox"],
        )
        == 23
    )
    dispatched.assert_called_once()


def _run_main_staging_probe(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    script = (
        "import sys\n"
        "from unittest.mock import patch\n"
        "\n"
        "sys.path.insert(0, 'tools')\n"
        "# run_tests has a lightweight repomap_kg Go-helper import.\n"
        "# Block the original product path that reached Psycopg.\n"
        "BLOCKED_MODULES = [\n"
        "    'smoke.container_smoke',\n"
        "    'smoke.lifecycle',\n"
        "    'repomap_kg.ops.refresh',\n"
        "    'psycopg',\n"
        "]\n"
        "\n"
        "class BlockedImportFinder:\n"
        "    def find_spec(self, fullname, path, target=None):\n"
        "        if any(fullname == m or fullname.startswith(m + '.') for m in BLOCKED_MODULES):\n"
        "            raise ModuleNotFoundError(f'Blocked import of {fullname}')\n"
        "        return None\n"
        "\n"
        "sys.meta_path.insert(0, BlockedImportFinder())\n"
        "for mod in list(sys.modules):\n"
        "    if any(mod == m or mod.startswith(m + '.') for m in BLOCKED_MODULES):\n"
        "        del sys.modules[mod]\n"
        "\n"
        "import run_tests\n"
        "\n"
        "dispatched = []\n"
        "def mock_dispatch(args, raw_argv):\n"
        "    dispatched.append((args.suite, getattr(args, 'smoke_image_reference', None), raw_argv))\n"
        "    return 42\n"
        "\n"
        "argv = ['--suite', 'staging'] + sys.argv[1:]\n"
        "with patch.object(run_tests, 'integration_sandbox_dispatch', side_effect=mock_dispatch):\n"
        "    code = run_tests.main(argv)\n"
        "    print(f'DISPATCH_COUNT:{len(dispatched)}')\n"
        "    if dispatched:\n"
        "        print(f'DISPATCH_SUITE:{dispatched[0][0]}')\n"
        "        print(f'DISPATCH_OVERRIDE:{dispatched[0][1]}')\n"
        "    sys.exit(code)\n"
    )
    return subprocess.run(
        [sys.executable, "-B", "-c", script, *extra_args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_ci2a_r1_staging_main_without_override_reaches_dispatch_with_blocked_modules() -> None:
    proc = _run_main_staging_probe([])
    assert proc.returncode == 42, f"stdout: {proc.stdout}, stderr: {proc.stderr}"
    assert "DISPATCH_COUNT:1" in proc.stdout
    assert "DISPATCH_SUITE:staging" in proc.stdout
    assert "DISPATCH_OVERRIDE:None" in proc.stdout


def test_ci2a_r1_staging_main_with_valid_override_reaches_dispatch_with_blocked_modules() -> None:
    valid_id = "sha256:" + "c" * 64
    proc = _run_main_staging_probe(["--smoke-image-reference", valid_id])
    assert proc.returncode == 42, f"stdout: {proc.stdout}, stderr: {proc.stderr}"
    assert "DISPATCH_COUNT:1" in proc.stdout
    assert "DISPATCH_SUITE:staging" in proc.stdout
    assert f"DISPATCH_OVERRIDE:{valid_id}" in proc.stdout


def test_ci2a_r1_staging_main_with_invalid_override_fails_before_dispatch() -> None:
    proc = _run_main_staging_probe(["--smoke-image-reference", "invalid:tag"])
    assert proc.returncode == 2, f"stdout: {proc.stdout}, stderr: {proc.stderr}"
    assert "DISPATCH_COUNT:0" in proc.stdout
    assert "ERROR: --smoke-image-reference override must be" in proc.stderr
