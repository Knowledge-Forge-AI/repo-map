"""Integration tests for the declared 24-task calibration baseline across all 5 arms (S3)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_criteria import derive_future_criteria_proposal
from retrieval_evaluation_harness import (
    DEFAULT_ARMS,
    declare_calibration_attempt,
    execute_calibration_baseline,
    verify_fixture_freeze_guard,
)
from retrieval_evaluation_schema import load_freeze_manifest, load_task_catalog


def test_calibration_baseline_end_to_end_across_all_five_arms_and_criteria_derivation(
    tmp_path: Path,
) -> None:
    """Execute the 24-task calibration baseline across native, SQLite/PG graph, and SQLite/PG projection arms."""
    catalog_path = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"
    freeze_path = MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"

    catalog = load_task_catalog(catalog_path)
    freeze = load_freeze_manifest(freeze_path)
    verify_fixture_freeze_guard(catalog, freeze, work_dir=tmp_path / "guard")

    with temporary_postgres() as pg_db:
        declaration = declare_calibration_attempt(
            catalog,
            freeze,
            attempt_id="functional-" + uuid.uuid4().hex,
            split="calibration",
            repetitions_per_task=3,
            arms=DEFAULT_ARMS,
            pg_port=pg_db.port,
        )
        report = execute_calibration_baseline(
            catalog,
            freeze,
            declaration,
            work_dir=tmp_path / "run",
            pg_host=pg_db.host,
            pg_port=pg_db.port,
            pg_database=pg_db.database,
            pg_user=pg_db.user,
            pg_password=pg_db.password,
            psql_command=pg_db.psql_command,
            include_postgres=True,
        )

    assert report["split"] == "calibration"
    assert report["held_out_executed"] is False
    assert tuple(report["arms"].keys()) == DEFAULT_ARMS
    assert_canary_free(report)

    assert report["execution_purpose"] == "functional_check"
    assert report["status"] == "completed"
    assert report["divergent_task_count"] == 0
    assert len(report["repetition_observations"]) == 24 * 5 * 3
    assert len(report["setup_byte_accounting"]) == 4
    assert all(item["projected_body_input_bytes_read"] > 0 for item in report["setup_byte_accounting"].values())
    assert all(item["total_artifact_store_bytes_read"] is None for item in report["setup_byte_accounting"].values())
    assert all(
        item["byte_accounting"]["artifact_store_bytes_read"] == 0
        for item in report["repetition_observations"]
        if item["arm_id"].startswith("captured_projection_reference:")
    )
    expected_ids = [task.task_id for task in catalog.calibration_tasks()]
    for arm_id in DEFAULT_ARMS:
        arm = report["arms"][arm_id]
        assert arm["whole_split_denominator"] == 24
        assert [slot["task_id"] for slot in arm["slots"]] == expected_ids
        assert sum(group["whole_split_denominator"] for group in arm["exposure_strata"].values()) == 24
        assert all(slot["comparator_exposure"] == arm["comparator_exposure_by_task"][slot["task_id"]] for slot in arm["slots"])
        for stratum in arm["strata"].values():
            for key in ("mean_recall_at_5", "mean_mrr_at_5", "mean_ndcg_at_5"):
                value = stratum[key]
                assert value is None if stratum["graded_count"] == 0 else 0.0 <= value <= 1.0

    proposal = derive_future_criteria_proposal(
        report,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
        allow_functional=True,
    )
    assert proposal.status == "proposed_for_parent_review"
    assert proposal.baseline_execution_purpose == "functional_check"
    assert_canary_free(proposal.to_dict())

    # Functional evidence stays in the test-owned temporary experiment.
    journal_dir = tmp_path / "run" / "functional-attempts" / declaration.attempt_id
    terminal = json.loads((journal_dir / "terminal.json").read_text())
    assert terminal["status"] == report["status"]
    assert terminal["observation_count"] == 2 + 24 * 5 * (3 * 2 + 1)
    assert (journal_dir / "sources.zip").is_file()

    tasks_by_id = {task.task_id: task for task in catalog.calibration_tasks()}
    for line in (journal_dir / "observations.jsonl").read_text().splitlines():
        record = json.loads(line)
        if record["event"] != "query_observed":
            continue
        envelope = record["envelope"]
        task = tasks_by_id[record["task_id"]]
        assert envelope["requested_mode"] == task.requested_mode
        if envelope["requested_mode"] != envelope["effective_mode"]:
            assert envelope["fallback"]["caller_selected"] is True
            assert envelope["fallback"]["from_mode"] == task.requested_mode
            assert envelope["fallback"]["to_mode"] == envelope["effective_mode"]
        if (record["arm_id"].startswith("current_graph_baseline:")
                and task.requested_mode == "ranked_discovery"
                and envelope["capability_state"] == "available"):
            assert envelope["match_surface"] == "stored_metadata"
            assert all(hit["match_surface"] == "stored_metadata" for hit in envelope["hits"])
