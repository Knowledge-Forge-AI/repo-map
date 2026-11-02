"""Unit tests for W4 retrieval_evaluation_context and context-v1 catalog (§7)."""

from __future__ import annotations

from pathlib import Path
import pytest

import retrieval_evaluation_context as context_evaluation
from repomap_test_support.context_fixture import build_sqlite_context_fixture
from retrieval_evaluation_context import (
    verify_context_v1_freeze,
    write_context_v1_freeze_artifacts,
)
from retrieval_evaluation_context_catalog import (
    CONTEXT_DECLARATION_SCHEMA_VERSION,
    EVALUATION_ARMS,
    TASK_FAMILIES,
    ContextAttemptDeclaration,
    build_default_context_v1_catalog,
)


def test_context_v1_catalog_freeze_and_held_out_guard(tmp_path: Path) -> None:
    cat = build_default_context_v1_catalog()
    assert len(cat.tasks) == 30
    assert len(cat.calibration_tasks()) == 20
    assert len(cat.held_out_tasks()) == 10
    assert {t.task_family for t in cat.tasks} == set(TASK_FAMILIES)

    # Verify committed freeze artifacts in repo (read-only)
    v_cat, v_freeze, v_decl = verify_context_v1_freeze()
    assert len(v_cat.tasks) == 30
    assert v_decl.arms == EVALUATION_ARMS
    assert v_decl.repetitions_per_task == 3

    # Materialize into tmp_path and verify roundtrip
    tmp_ctx = tmp_path / "context-v1"
    w_cat, w_freeze, w_decl = write_context_v1_freeze_artifacts(context_fixture_root=tmp_ctx)
    assert w_freeze.catalog_sha256 == v_freeze.catalog_sha256
    assert w_decl.attempt_id == "w4-context-calibration-attempt-1"

    # Held-out split is rejected in attempt declaration
    with pytest.raises(ValueError, match="held_out"):
        ContextAttemptDeclaration(
            schema_version=CONTEXT_DECLARATION_SCHEMA_VERSION,
            attempt_id="bad-held-out",
            phase_id="REPOMAP-CLOE-CONTEXT1",
            split="held_out",
            freeze_sha256=v_decl.freeze_sha256,
            catalog_sha256=v_decl.catalog_sha256,
            ordered_task_ids=v_decl.ordered_task_ids,
            arms=EVALUATION_ARMS,
            repetitions_per_task=3,
            budget_tiers=(4096, 16384, 65536),
        ).validate()


def test_calibration_refuses_missing_postgres_before_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_admission(*args: object, **kwargs: object) -> None:
        raise AssertionError("Missing PostgreSQL must be refused before admission")

    monkeypatch.setattr(context_evaluation, "admit_attempt", forbidden_admission)
    with pytest.raises(ValueError, match="(?i)postgres"):
        context_evaluation.execute_context_v1_calibration(attempts_root=tmp_path / "attempts")
    assert not (tmp_path / "attempts").exists()


def test_native_arm_never_substitutes_graph_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_graph(*args: object, **kwargs: object) -> None:
        raise AssertionError("Native evidence must never be synthesized by graph navigation")

    monkeypatch.setattr(context_evaluation, "build_compact_context", forbidden_graph)
    task = build_default_context_v1_catalog().calibration_tasks()[0]
    _, _, _, _, port = build_sqlite_context_fixture(tmp_path)
    observation = context_evaluation._run_arm_observation(
        "native_tools_baseline", task, sqlite_adapter=port, postgres_adapter=port,
    )
    assert observation["status"] == "unavailable"
    assert observation["gold_locator_rank"] is None


def test_execution_closure_binds_corpus_and_measurement_owners() -> None:
    files = context_evaluation.context_candidate_source_files()
    assert {
        "src/test/support/python/repomap_test_support/context_fixture.py",
        "src/test/support/python/repomap_test_support/context_assertions.py",
        "tools/retrieval_evaluation_attempts.py",
        "tools/retrieval_evaluation_admission.py",
        "tools/retrieval_evaluation_native.py",
        "src/main/python/common_lore_index/cli/dispatch.py",
    } <= files.keys()


@pytest.mark.parametrize("defect", [None, "missing", "unavailable", "duplicate"])
def test_postgres_identity_reconciles_only_supported_population(defect: str | None) -> None:
    tasks = build_default_context_v1_catalog().calibration_tasks()
    supported = {"definition", "docs", "tests", "messages"}
    observations = [
        {"task_id": task.task_id, "task_family": task.task_family,
         "arm": arm, "repetition": repetition, "status": "complete", "gold_locator_rank": 1}
        for task in tasks for arm in EVALUATION_ARMS if arm.endswith("_postgres")
        for repetition in (1, 2, 3)
    ]
    selected = next(i for i, row in enumerate(observations) if row["task_family"] in supported)
    if defect == "missing":
        observations.pop(selected)
    elif defect == "unavailable":
        observations[selected]["status"] = "unavailable"
    elif defect == "duplicate":
        observations[selected] = dict(observations[selected + 1])
    report = context_evaluation._postgres_capability_report(observations, tasks, 3)
    assert report["expected_observation_count"] == 99
    assert report["known_unsupported_observation_count"] == 81
    assert report["all_declared_supported_families_compatible"] is (defect is None)
    assert report["missing_observation_count"] == (1 if defect in {"missing", "duplicate"} else 0)
