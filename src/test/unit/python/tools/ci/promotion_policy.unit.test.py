"""Main-source policy: only same-repository staging may promote to main."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from ci.promotion_policy import (
    MAIN_BRANCH,
    PROMOTION_SOURCE_BRANCH,
    PromotionSource,
    evaluate_promotion,
)

ROOT = Path(__file__).resolve().parents[6]
TOOLS_CI = ROOT / "tools/ci"
ENTRYPOINT = TOOLS_CI / "promotion_policy.py"
REPOSITORY = "lair001/repo-map_dev"


def event_payload(
    *, base: str = MAIN_BRANCH, head: str = PROMOTION_SOURCE_BRANCH, repo: str | None = REPOSITORY
) -> dict[str, Any]:
    return {
        "pull_request": {
            "base": {"ref": base},
            "head": {"ref": head, "repo": None if repo is None else {"full_name": repo}},
        }
    }


def source(**kwargs: Any) -> PromotionSource:
    return PromotionSource.from_event_payload(event_payload(**kwargs))


def test_same_repository_staging_to_main_is_accepted() -> None:
    assert evaluate_promotion(source(), REPOSITORY) == ()


def test_only_staging_may_promote_to_main() -> None:
    violations = evaluate_promotion(source(head="feature/whatever"), REPOSITORY)

    assert any("may promote to" in violation for violation in violations)


def test_forked_head_is_refused() -> None:
    violations = evaluate_promotion(source(repo="attacker/repo-map_dev"), REPOSITORY)

    assert any("head must come from" in violation for violation in violations)


def test_head_without_a_repository_is_refused() -> None:
    violations = evaluate_promotion(source(repo=None), REPOSITORY)

    assert any("head must come from" in violation for violation in violations)


def test_policy_applies_only_to_pull_requests_targeting_main() -> None:
    violations = evaluate_promotion(source(base="staging"), REPOSITORY)

    assert any("applies only to pull requests targeting" in v for v in violations)


def test_event_payload_without_a_pull_request_is_refused() -> None:
    with pytest.raises(ValueError, match="pull_request"):
        PromotionSource.from_event_payload({"action": "opened"})


def run_cli(tmp_path: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-S",
            "-E",
            str(ENTRYPOINT),
            "--repository",
            REPOSITORY,
            "--event-path",
            str(event_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_command_line_accepts_the_bootstrap_promotion(tmp_path: Path) -> None:
    completed = run_cli(tmp_path, event_payload())

    assert completed.returncode == 0, completed.stderr
    assert "accepted" in completed.stdout


def test_command_line_refuses_any_other_source(tmp_path: Path) -> None:
    completed = run_cli(tmp_path, event_payload(head="ci/pipeline-tiering"))

    assert completed.returncode == 1
    assert "main-source policy refused" in completed.stderr


def test_command_line_refuses_an_event_without_a_pull_request(tmp_path: Path) -> None:
    completed = run_cli(tmp_path, {"action": "workflow_dispatch"})

    assert completed.returncode == 1
    assert "main-source policy refused" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_command_line_requires_a_repository_and_an_event(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-S", "-E", str(ENTRYPOINT), "--repository", "", "--event-path", ""],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
