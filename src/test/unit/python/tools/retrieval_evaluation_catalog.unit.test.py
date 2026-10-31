"""Unit tests for the frozen mixed-v1 36-task catalog and pre-query freeze manifest (S2/S3)."""

from __future__ import annotations

from pathlib import Path

from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_ALIAS_BY_BINDING_ID,
    MIXED_V1_FIXTURE_ROOT,
    compute_working_copy_digests,
    materialize_mixed_v1_working_copy,
)
from retrieval_evaluation_schema import (
    TASK_FAMILIES,
    load_freeze_manifest,
    load_task_catalog,
)


def test_frozen_catalog_v1_matches_36_task_family_and_split_contract() -> None:
    """The committed catalog-v1.json validates against the 10-family 24/12 split contract."""
    catalog_path = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"
    catalog = load_task_catalog(catalog_path)
    assert len(catalog.tasks) == 36
    assert len(catalog.calibration_tasks()) == 24
    assert len(catalog.held_out_tasks()) == 12

    for family, (total, cal_expected, hold_expected) in TASK_FAMILIES.items():
        fam_tasks = [t for t in catalog.tasks if t.family == family]
        cal_tasks = [t for t in fam_tasks if t.split == "calibration"]
        hold_tasks = [t for t in fam_tasks if t.split == "held_out"]
        assert len(fam_tasks) == total, family
        assert len(cal_tasks) == cal_expected, family
        assert len(hold_tasks) == hold_expected, family


def test_frozen_gold_locators_exist_in_materialized_working_copies(tmp_path: Path) -> None:
    """Every positive gold locator in catalog-v1.json resolves to an actual fixture file and valid line range."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    gen1_root = materialize_mixed_v1_working_copy(tmp_path / "gen1", generation=1)
    gen2_root = materialize_mixed_v1_working_copy(tmp_path / "gen2", generation=2)
    by_gen = {1: gen1_root, 2: gen2_root}

    alias_by_binding = MIXED_V1_ALIAS_BY_BINDING_ID

    for task in catalog.tasks:
        gen_root = by_gen[task.generation]
        for gold in task.gold_targets:
            if gold.relevance_grade == 0:
                continue
            alias = alias_by_binding[gold.locator.binding_id]
            target_file = gen_root / alias / gold.locator.source_relative_path
            assert target_file.is_file(), (task.task_id, gold.locator)
            if gold.locator.start_line is not None:
                raw_lines = target_file.read_bytes().splitlines()
                assert 1 <= gold.locator.start_line <= len(raw_lines), (task.task_id, gold.locator)
                if gold.locator.end_line is not None:
                    assert gold.locator.start_line <= gold.locator.end_line <= len(raw_lines), (
                        task.task_id,
                        gold.locator,
                    )


def test_freeze_v1_manifest_matches_catalog_and_working_copy_digests(tmp_path: Path) -> None:
    """freeze-v1.json matches catalog-v1.json and both materialized fixture generations."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    assert freeze.catalog_sha256 == catalog.catalog_digest()

    gen1_root = materialize_mixed_v1_working_copy(tmp_path / "gen1", generation=1)
    gen2_root = materialize_mixed_v1_working_copy(tmp_path / "gen2", generation=2)
    d1 = {f"{alias}/{rel}": info for (alias, rel), info in compute_working_copy_digests(gen1_root).items()}
    d2 = {f"{alias}/{rel}": info for (alias, rel), info in compute_working_copy_digests(gen2_root).items()}
    assert dict(freeze.generation_1_files) == d1
    assert dict(freeze.generation_2_files) == d2
