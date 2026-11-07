"""Unit tests for retrieval evaluation schemas, freeze manifests, and attempt declarations (S3)."""

from __future__ import annotations

import pytest

from common_lore_index.retrieval.query_contracts import EvaluationLocator
from retrieval_evaluation_schema import (
    AttemptDeclaration,
    EvaluationTask,
    FreezeManifest,
    GoldTarget,
    TASK_FAMILIES,
    TaskCatalog,
)


def _make_dummy_task(task_id: str, family: str, split: str, index: int) -> EvaluationTask:
    return EvaluationTask(
        task_id=task_id,
        family=family,
        split=split,
        question=f"Question for {task_id}",
        permitted_query_plan={"query": f"token_{index}", "limit": 10},
        graph_id="mixed-v1",
        generation=1,
        selected_bindings=("core", "companion"),
        source_path_prefix=None,
        requested_mode="literal_captured_text",
        intended_match_surface="captured_text",
        comparability_stratum="body",
        comparator_exposure={"native": "authorized_bodies", "graph": "metadata", "reference": "projected_bodies"},
        gold_targets=(
            GoldTarget(
                locator=EvaluationLocator(
                    binding_id="bind1:core",
                    source_relative_path=f"pkg/mod_{index}.py",
                    start_line=1,
                    end_line=5,
                ),
                relevance_grade=3,
                rationale="primary definition",
            ),
        ),
        expected_capability_state="available",
        expected_refusal_code=None,
        grading_rule="ranked_positive",
    ).validate()


def _build_valid_36_task_catalog() -> TaskCatalog:
    tasks: list[EvaluationTask] = []
    idx = 1
    for family, (total, cal_count, held_count) in TASK_FAMILIES.items():
        assert total == cal_count + held_count
        for c in range(cal_count):
            tasks.append(_make_dummy_task(f"cal-{idx:02d}", family, "calibration", idx))
            idx += 1
        for h in range(held_count):
            tasks.append(_make_dummy_task(f"hold-{idx:02d}", family, "held_out", idx))
            idx += 1
    return TaskCatalog(
        schema_version="cloe-retrieval-task-catalog-v1",
        fixture_id="mixed-v1",
        tasks=tuple(tasks),
    ).validate()


def test_task_family_distribution_enforces_exact_36_24_12_split() -> None:
    """TaskCatalog validates the exact 36-task (24 calibration, 12 held-out) 10-family table."""
    catalog = _build_valid_36_task_catalog()
    assert len(catalog.tasks) == 36
    assert len(catalog.calibration_tasks()) == 24
    assert len(catalog.held_out_tasks()) == 12
    assert catalog.catalog_digest().startswith("sha256:")
    assert TaskCatalog.from_mapping(catalog.to_dict()) == catalog

    # Dropping one task or changing a split must fail validation
    with pytest.raises(ValueError, match="36 tasks"):
        TaskCatalog(
            schema_version="cloe-retrieval-task-catalog-v1",
            fixture_id="mixed-v1",
            tasks=catalog.tasks[:-1],
        ).validate()


def test_gold_target_rejects_invalid_grades_and_duplicate_locators() -> None:
    """GoldTarget grades must be integers 0..3 and unique per task."""
    loc = EvaluationLocator(binding_id="bind1:core", source_relative_path="pkg/a.py", start_line=1, end_line=2)
    for bad_grade in (-1, 4, True):
        with pytest.raises(ValueError, match="relevance_grade"):
            GoldTarget(locator=loc, relevance_grade=bad_grade, rationale="bad").validate()

    t = _make_dummy_task("cal-01", "exact_symbol_and_partial_name", "calibration", 1)
    dup_gold = [t.gold_targets[0].to_dict(), t.gold_targets[0].to_dict()]
    with pytest.raises(ValueError, match="duplicate gold locator"):
        EvaluationTask.from_mapping({**t.to_dict(), "gold_targets": dup_gold})


def test_attempt_declaration_refuses_held_out_split_and_validates_calibration() -> None:
    """AttemptDeclaration requires calibration split in W2 and pins freeze/catalog/closure digests."""
    catalog = _build_valid_36_task_catalog()
    cal_ids = tuple(t.task_id for t in catalog.calibration_tasks())
    decl = AttemptDeclaration(
        schema_version="cloe-retrieval-attempt-declaration-v1",
        attempt_id="calibration-attempt-1",
        phase_id="REPOMAP-CLOE-RETRIEVAL1",
        split="calibration",
        freeze_sha256="sha256:" + "a" * 64,
        catalog_sha256=catalog.catalog_digest(),
        ordered_task_ids=cal_ids,
        arms=(
            "native_tools_baseline",
            "current_graph_baseline:sqlite",
            "current_graph_baseline:postgresql",
            "captured_projection_reference:sqlite",
            "captured_projection_reference:postgresql",
        ),
        repetitions_per_task=3,
        stopping_rule="complete_all_24_calibration_tasks_3_repetitions_no_early_stop",
        replacement_policy="retain_failed_attempts_require_new_attempt_id_on_instrument_bug",
        candidate_closure_digests={"tools/retrieval_evaluation.py": "sha256:" + "b" * 64},
        runner_profile={"container": "repomap-ci-static", "pg_port": 55433},
    ).validate()
    assert AttemptDeclaration.from_mapping(decl.to_dict()) == decl

    with pytest.raises(ValueError, match="held_out"):
        AttemptDeclaration.from_mapping({**decl.to_dict(), "split": "held_out"})


def test_freeze_manifest_roundtrip_and_digest() -> None:
    """FreezeManifest serializes and hashes deterministically."""
    fm = FreezeManifest(
        schema_version="cloe-retrieval-freeze-v1",
        fixture_id="mixed-v1",
        catalog_sha256="sha256:" + "1" * 64,
        committed_fixture_files={"companion/flake.nix": "sha256:" + "2" * 64},
        generation_1_files={"core/pkg/pipeline.py": {"sha256": "sha256:" + "3" * 64, "size_bytes": 120}},
        generation_2_files={"core/pkg/pipeline.py": {"sha256": "sha256:" + "4" * 64, "size_bytes": 140}},
        representation_version="lf-utf8-v1",
        policy_digest="sha256:" + "5" * 64,
    ).validate()
    assert fm.freeze_digest().startswith("sha256:")
    assert FreezeManifest.from_mapping(fm.to_dict()) == fm
