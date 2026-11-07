"""W4 evaluation capability proof and separately selected retained calibration."""

from __future__ import annotations

from pathlib import Path
import sys

from repomap_test_support.context_assertions import build_postgres_context_fixture
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from retrieval_evaluation_context import (
    _run_arm_observation, execute_context_v1_calibration, prepare_context_v1_evaluation,
)
from retrieval_evaluation_context_catalog import EVALUATION_ARMS, build_default_context_v1_catalog
from retrieval_evaluation_context_transport import emit_context_attempt_archive


def test_context_v1_bounded_real_native_sqlite_and_postgres_observations(tmp_path: Path) -> None:
    """Check three calibration tasks across real backends without running the collector."""
    require_postgres_binaries()
    preparation = prepare_context_v1_evaluation(tmp_path / "sqlite")
    catalog = build_default_context_v1_catalog()
    tasks = tuple(
        next(task for task in catalog.calibration_tasks() if task.task_family == family)
        for family in ("definition", "tests", "messages")
    )
    with temporary_postgres() as postgres:
        _home, pg_adapter = build_postgres_context_fixture(tmp_path / "postgres", postgres)
        with preparation.sqlite_adapter as sq_adapter:
            observations = [
                _run_arm_observation(
                    arm, task, sqlite_adapter=sq_adapter, postgres_adapter=pg_adapter,
                    native_view=preparation.native_view,
                )
                for task in tasks for arm in EVALUATION_ARMS
            ]
    assert len(observations) == 21
    for observation in observations:
        assert observation["status"] in {"complete", "partial", "completed"}
        assert observation["gold_locator_rank"] is not None
        if observation["canonical_identity_claimed"]:
            assert observation["budget_compliant"] is True
            assert observation["sql_statements_executed"] > 0
        else:
            assert observation["sql_statements_executed"] is None
            assert observation["returned_keys"] == []


def test_context_v1_seven_arm_calibration_with_live_postgres_and_sqlite(
    tmp_path: Path,
) -> None:
    """Execute 7-arm × 20-task × 3-repetition calibration (420 observations) over live SQLite and PostgreSQL."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        pg_dir = tmp_path / "pg_eval"
        pg_dir.mkdir(parents=True, exist_ok=True)
        _pg_home, pg_adapter = build_postgres_context_fixture(pg_dir, postgres)

        attempts_root = tmp_path / "eval_run"
        attempt_id = "w4-context-functional-attempt-7"
        try:
            summary = execute_context_v1_calibration(
                attempts_root=attempts_root, attempt_id=attempt_id,
                postgres_adapter=pg_adapter, pg_port=postgres.port,
            )
        finally:
            attempt = attempts_root / attempt_id
            if (attempt / "terminal.json").is_file():
                emit_context_attempt_archive(attempt, stream=sys.stdout)
        assert summary["schema_version"] == "cloe-context-evaluation-summary-v1"
        assert summary["observation_count"] == 420
        assert summary["held_out_context_v1_tasks_executed"] == 0
        assert summary["held_out_mixed_v1_tasks_executed"] == 0
        assert len(summary["arms"]) == 7
        assert summary["intent_rank_improved_task_count"] > 0

        falsification = summary["falsification_checks"]
        assert falsification["scan_limit_not_routinely_exceeded"] is True
        assert falsification["postgres_destination_identity_present"] is True
        assert falsification["budget_and_actual_bytes_exact"] is True
        assert falsification["tests_and_messages_located"] is True
        assert falsification["intent_rank_improves_over_canonical_key_asc"] is True
        assert summary["all_falsification_checks_passed"] is True
