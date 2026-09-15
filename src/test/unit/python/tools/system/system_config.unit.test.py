"""Unit tests for containerized system gate configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.config import (
    DEFAULT_CANDIDATE_TAG_PREFIX,
    MAX_SYSTEM_TIMEOUT_SECONDS,
    SYSTEM_CLEANUP_RESERVE_SECONDS,
    SYSTEM_DESIGN_TARGET_SECONDS,
    SYSTEM_TOTAL_BUDGET_SECONDS,
    SYSTEM_WATCHDOG_TIMEOUT_SECONDS,
    SystemDeadline,
    SystemTestConfig,
    SystemTestError,
)


def test_hosted_system_timeout_ceiling_allows_the_main_gate_deadline() -> None:
    assert MAX_SYSTEM_TIMEOUT_SECONDS == 3600
    assert SYSTEM_WATCHDOG_TIMEOUT_SECONDS == 3600
    assert SYSTEM_DESIGN_TARGET_SECONDS == 1800


SAMPLE_TREE = "a" * 40
SAMPLE_COMMIT = "b" * 40


def test_system_config_defaults() -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha=SAMPLE_TREE,
        run_id="run-12345",
    )
    assert config.timeout_seconds == SYSTEM_TOTAL_BUDGET_SECONDS
    assert config.candidate_tree_sha == SAMPLE_TREE
    assert config.candidate_tag == f"{DEFAULT_CANDIDATE_TAG_PREFIX}:{SAMPLE_TREE[:12]}"
    assert config.run_id == "run-12345"
    assert config.report_dir is None
    assert config.gate_kind == "main-system"


def test_system_config_with_candidate_identities() -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha=SAMPLE_TREE,
        candidate_commit_sha=SAMPLE_COMMIT,
        approval_id="app-123",
        pr_number="21",
        repository="owner/repo",
        approved_base_sha="c" * 40,
        approved_head_sha="d" * 40,
        candidate_base_parent="c" * 40,
        candidate_head_parent="d" * 40,
        run_id="run-bound",
    )
    assert config.candidate_commit_sha == SAMPLE_COMMIT
    assert config.approval_id == "app-123"
    assert config.pr_number == "21"
    assert config.approved_base_sha == "c" * 40


def test_system_config_custom_timeout() -> None:
    config = SystemTestConfig.create(
        timeout_seconds=600,
        report_dir=Path("/tmp/report"),
        candidate_tree_sha=SAMPLE_TREE,
        run_id="run-custom",
    )
    assert config.timeout_seconds == 600
    assert config.report_dir == Path("/tmp/report")


def test_system_config_rejects_out_of_bounds_timeout() -> None:
    with pytest.raises(SystemTestError, match="must be between"):
        SystemTestConfig.create(
            timeout_seconds=SYSTEM_CLEANUP_RESERVE_SECONDS - 1,
            candidate_tree_sha=SAMPLE_TREE,
            run_id="run-err",
        )

    with pytest.raises(SystemTestError, match="must be between"):
        SystemTestConfig.create(
            timeout_seconds=MAX_SYSTEM_TIMEOUT_SECONDS + 1,
            candidate_tree_sha=SAMPLE_TREE,
            run_id="run-err",
        )


def test_system_config_rejects_invalid_tree_sha() -> None:
    with pytest.raises(SystemTestError, match="invalid candidate tree SHA"):
        SystemTestConfig.create(
            candidate_tree_sha="invalid-sha",
            run_id="run-err",
        )

    with pytest.raises(SystemTestError, match="invalid candidate tree SHA"):
        SystemTestConfig.create(
            candidate_tree_sha="a" * 39,  # too short
            run_id="run-err",
        )


def test_system_deadline_budget_and_env_export() -> None:
    deadline = SystemDeadline(total_budget_seconds=300.0, cleanup_reserve_seconds=120.0)
    assert deadline.remaining_total_seconds() > 0
    assert deadline.remaining_test_seconds() <= 180.0
    exported = deadline.export_env()
    assert "_REPOMAP_SYSTEM_DEADLINE_EPOCH" in exported

    # Nested deadline cannot exceed parent deadline
    nested = SystemDeadline(
        total_budget_seconds=1000.0,
        cleanup_reserve_seconds=120.0,
        parent_deadline_epoch=deadline.deadline_epoch,
    )
    assert nested.deadline_epoch == deadline.deadline_epoch


def test_system_advisory_target_and_watchdog_semantics() -> None:
    assert SYSTEM_DESIGN_TARGET_SECONDS == 1800
    assert SYSTEM_WATCHDOG_TIMEOUT_SECONDS == 3600

    for mode in ("local_rehearsal", "hosted_qualification", "smoke_rehearsal"):
        cfg = SystemTestConfig.create(
            candidate_tree_sha=SAMPLE_TREE,
            run_id=f"run-{mode}",
            execution_mode=mode,
            timeout_seconds=3600,
        )
        assert cfg.timeout_seconds == 3600
        assert cfg.execution_mode == mode

    with pytest.raises(SystemTestError, match="must be between"):
        SystemTestConfig.create(
            candidate_tree_sha=SAMPLE_TREE,
            run_id="r",
            timeout_seconds=119,
        )
    with pytest.raises(SystemTestError, match="must be between"):
        SystemTestConfig.create(
            candidate_tree_sha=SAMPLE_TREE,
            run_id="r",
            timeout_seconds=3601,
        )

