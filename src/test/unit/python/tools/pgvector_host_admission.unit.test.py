"""Unit tests for host-side pgvector selector admission before sandbox dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_ROOT = REPO_ROOT / "tools"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"

for extra_path in (REPO_ROOT, TOOLS_ROOT, TEST_SUPPORT_ROOT):
    if str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))

import run_tests
from runner_arguments import (
    forwarded_selection_args,
    validate_pgvector_forwarded_selections,
)
from runner_sandbox import validate_sandbox_profile_options


def _pgvector_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "suite": "int",
        "no_coverage": True,
        "report": False,
        "jobs": "1",
        "pg_container_runtime": "docker",
        "pg_test_profile": "pgvector",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.parametrize(
    ("argv", "expected_error"),
    [
        (
            ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector"],
            "canonical pgvector profile requires scoped test selector(s) after '--'",
        ),
        (
            ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector", "--"],
            "canonical pgvector profile requires scoped test selector(s) after '--'",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "-m",
                "requires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "-mrequires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "--markexpr",
                "requires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "--markexpr=requires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "src/test/unit/python/tools/pgvector_profile.unit.test.py",
            ],
            "outside selected suite root(s): src/test/int/python",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "README.md",
            ],
            "outside selected suite root(s): src/test/int/python",
        ),
        (
            [
                "--suite",
                "int",
                "--pg-test-profile",
                "pgvector",
                "--",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "--pg-test-profile pgvector requires scoped int --no-coverage",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-container-runtime",
                "podman",
                "--pg-test-profile",
                "pgvector",
                "--",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "integration sandbox execution requires --pg-container-runtime docker",
        ),
    ],
)
def test_pgvector_invalid_invocations_rejected_on_host_before_sandbox_dispatch(
    argv: list[str],
    expected_error: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=99) as dispatch_spy,
        patch.object(run_tests, "establish_test_scratch") as scratch_spy,
    ):
        exit_code = run_tests.main(argv)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_error in captured.err
    assert dispatch_spy.call_count == 0
    assert scratch_spy.call_count == 0


@pytest.mark.parametrize(
    "forwarded",
    [
        ["src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py"],
        [
            "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py"
            "::test_selected_candidate_capability_boundary"
        ],
        ["-k", "candidate"],
        ["-k", "candidate", "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py"],
    ],
)
def test_pgvector_valid_scoped_and_keyword_invocations_reach_sandbox_dispatch_unchanged(
    forwarded: list[str],
) -> None:
    argv = ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector", "--", *forwarded]
    if forwarded == ["-k", "candidate"]:
        assert forwarded_selection_args(forwarded) == ()

    with patch.object(run_tests, "integration_sandbox_dispatch", return_value=0) as dispatch_spy:
        exit_code = run_tests.main(argv)

    assert exit_code == 0
    assert dispatch_spy.call_count == 1
    dispatched_args, dispatched_raw_argv = dispatch_spy.call_args.args
    assert dispatched_args.pg_test_profile == "pgvector"
    assert dispatched_raw_argv == argv


def test_core_profile_host_admission_remains_unchanged_without_selectors() -> None:
    argv = ["--suite", "int", "--no-coverage"]
    with patch.object(run_tests, "integration_sandbox_dispatch", return_value=0) as dispatch_spy:
        exit_code = run_tests.main(argv)

    assert exit_code == 0
    assert dispatch_spy.call_count == 1
    dispatched_args, dispatched_raw_argv = dispatch_spy.call_args.args
    assert dispatched_args.pg_test_profile == "core"
    assert dispatched_raw_argv == argv


def test_direct_profile_and_admission_validators_enforce_selector_and_marker_rules() -> None:
    args = _pgvector_args()
    validate_sandbox_profile_options(args)
    validate_sandbox_profile_options(args, ["-k", "candidate"])
    with pytest.raises(
        RuntimeError,
        match="canonical pgvector profile requires scoped test selector\\(s\\) after '--'",
    ):
        validate_sandbox_profile_options(args, [])

    with pytest.raises(
        RuntimeError,
        match="canonical pgvector profile requires scoped test selector\\(s\\) after '--'",
    ):
        validate_pgvector_forwarded_selections(args, [])

    validate_pgvector_forwarded_selections(args, ["-k", "candidate"], repo_root=REPO_ROOT)
