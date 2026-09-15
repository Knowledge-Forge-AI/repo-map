"""TEST-HYGIENE3A-FIX1 complete-suite profile regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_tests
import pytest

from repomap_test_support.resource_hygiene_policy import HygieneConfig, HygieneProfile
from repomap_test_support.resource_runner_profile import (
    RunnerProfileError,
    resolve_runner_profile,
)


def _layout(tmp_path: Path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    return SimpleNamespace(run_root=run_root, allocated=True)


def test_staging_without_explicit_heavy_or_qualification_refuses(tmp_path: Path):
    layout = _layout(tmp_path)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(run_tests, "load_hygiene_config", return_value=HygieneConfig()),
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=None),
        patch.object(run_tests.TestResourceRun, "start", return_value=None) as start,
        patch.object(run_tests, "run_selected_suites", return_value=0) as work,
        patch.object(run_tests, "cleanup_unadmitted_layout") as cleanup,
        patch.object(run_tests, "finalize_run") as finalize,
    ):
        result = run_tests.main(
            [
                "--suite",
                "staging",
                "--smoke-image-reference",
                "sha256:" + "a" * 64,
            ]
        )

    assert result == 2
    start.assert_not_called()
    work.assert_not_called()
    cleanup.assert_called_once_with(layout)
    finalize.assert_called_once()


def test_default_cli_invocation_requires_an_explicit_suite() -> None:
    with (
        patch.object(run_tests, "establish_test_scratch") as establish,
        pytest.raises(SystemExit) as raised,
    ):
        run_tests.main([])

    assert raised.value.code == 2
    establish.assert_not_called()


@pytest.mark.parametrize(
    ("suite", "expected"),
    [
        ("unit", HygieneProfile.ORDINARY),
        ("int", HygieneProfile.INTEGRATION),
        ("smoke", HygieneProfile.INTEGRATION),
    ],
)
def test_bounded_suites_use_closed_defaults(suite, expected):
    selection = resolve_runner_profile(
        suite,
        requested_profile=None,
        declared_complete_gates=0,
        campaign_plan_id=None,
        operator_attested_exclusive=False,
        operator_attested_pressure_degradation=False,
    )
    assert selection.selected_profile is expected


def test_heavy_complete_work_requires_exactly_one_declared_gate():
    selection = resolve_runner_profile(
        "staging",
        requested_profile=HygieneProfile.HEAVY,
        declared_complete_gates=1,
        campaign_plan_id=None,
        operator_attested_exclusive=True,
        operator_attested_pressure_degradation=False,
    )
    assert selection.declared_complete_gates == 1
    with pytest.raises(RunnerProfileError, match="exactly one"):
        resolve_runner_profile(
            "staging",
            requested_profile=HygieneProfile.HEAVY,
            declared_complete_gates=2,
            campaign_plan_id=None,
            operator_attested_exclusive=True,
            operator_attested_pressure_degradation=False,
        )


def test_qualification_authorities_are_independent_and_preserved():
    selection = resolve_runner_profile(
        "staging",
        requested_profile=HygieneProfile.QUALIFICATION,
        declared_complete_gates=2,
        campaign_plan_id="TEST-CAMPAIGN1",
        operator_attested_exclusive=True,
        operator_attested_pressure_degradation=True,
    )
    assert selection.campaign_plan_id == "TEST-CAMPAIGN1"
    assert selection.operator_attested_exclusive is True
    assert selection.operator_attested_pressure_degradation is True


def test_build_work_requires_explicit_build_profile():
    with pytest.raises(RunnerProfileError, match="explicit"):
        resolve_runner_profile(
            "build",
            requested_profile=None,
            declared_complete_gates=0,
            campaign_plan_id=None,
            operator_attested_exclusive=False,
            operator_attested_pressure_degradation=False,
        )
    assert resolve_runner_profile(
        "build",
        requested_profile=HygieneProfile.BUILD,
        declared_complete_gates=0,
        campaign_plan_id=None,
        operator_attested_exclusive=False,
        operator_attested_pressure_degradation=False,
    ).selected_profile is HygieneProfile.BUILD
