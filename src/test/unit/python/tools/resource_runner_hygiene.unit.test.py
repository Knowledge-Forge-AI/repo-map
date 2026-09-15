"""TEST-HYGIENE3A allocating-runner profile, refusal, and quota contracts."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_tests

from repomap_test_support.resource_hygiene_policy import (
    HygieneConfig,
    HygieneConfigError,
    HygieneProfile,
)
from repomap_test_support.resource_retention import TerminalOutcome


def _layout(tmp_path: Path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    return SimpleNamespace(run_root=run_root, allocated=True)


def test_cli_profile_is_not_silently_downgraded(tmp_path):
    layout = _layout(tmp_path)
    config = HygieneConfig(requested_profile=HygieneProfile.QUALIFICATION)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(run_tests, "load_hygiene_config", return_value=config),
        patch.object(run_tests.TestResourceRun, "start", return_value=None) as start,
        patch.object(run_tests, "run_selected_suites", return_value=0),
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(
            [
                "--suite",
                "unit",
                "--hygiene-profile",
                "qualification",
                "--declared-complete-gates",
                "1",
                "--campaign-plan-id",
                "TEST-CAMPAIGN1",
                "--operator-attest-exclusive",
            ]
        )

    assert result == 0
    assert start.call_args.kwargs["profile"] is HygieneProfile.QUALIFICATION


def test_invalid_configuration_refuses_before_work_and_cleans_exact_layout(tmp_path):
    layout = _layout(tmp_path)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(
            run_tests,
            "load_hygiene_config",
            side_effect=HygieneConfigError("invalid"),
        ),
        patch.object(run_tests, "cleanup_unadmitted_layout") as cleanup,
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run") as finalize,
    ):
        result = run_tests.main(["--suite", "unit"])

    assert result == 2
    cleanup.assert_called_once_with(layout)
    work.assert_not_called()
    finalize.assert_called_once()


def test_borrower_configuration_failure_never_cleans_owner_layout(tmp_path):
    layout = _layout(tmp_path)
    layout.allocated = False
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(
            run_tests,
            "load_hygiene_config",
            side_effect=HygieneConfigError("invalid"),
        ),
        patch.object(run_tests, "cleanup_unadmitted_layout") as cleanup,
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run") as finalize,
    ):
        result = run_tests.main(["--suite", "unit"])

    assert result == 2
    cleanup.assert_not_called()
    work.assert_not_called()
    finalize.assert_called_once()


def test_entry_quota_refusal_skips_work_but_still_closes_owner(tmp_path):
    layout = _layout(tmp_path)
    resource_run = Mock()
    resource_run.quota_exceeded = True
    resource_run.bounded_subprocess.return_value = nullcontext()
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(
            run_tests,
            "load_hygiene_config",
            return_value=HygieneConfig(),
        ),
        patch.object(run_tests.TestResourceRun, "start", return_value=resource_run),
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(["--suite", "unit"])

    assert result == 2
    work.assert_not_called()
    resource_run.close.assert_called_once_with(TerminalOutcome.FAILED)
