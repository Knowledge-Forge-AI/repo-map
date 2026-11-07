"""Comparator populations preserve explicit exposure and task denominators."""

from __future__ import annotations

from dataclasses import replace

import pytest

from common_lore_index.retrieval.query_contracts import QueryMode, QueryScope, unavailable_envelope
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_comparability import describe_comparability
from retrieval_evaluation_grading import ExecutionState, grade_task_execution
from retrieval_evaluation_schema import load_task_catalog


def test_distinct_exposures_cannot_be_pooled_or_lose_unavailable_tasks() -> None:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    tasks = [replace(task, comparator_exposure={**task.comparator_exposure, "native": exposure})
             for task, exposure in zip(catalog.calibration_tasks()[:2], ("full_file", "bounded_excerpt"), strict=True)]
    envelope = unavailable_envelope(requested_mode=QueryMode.RANKED_DISCOVERY,
                                   scope=QueryScope(graph_id="fixture", backend="native_filesystem"))
    slots = [grade_task_execution(task, execution_state=ExecutionState.UNAVAILABLE, envelope=envelope) for task in tasks]
    result = describe_comparability("native_tools_baseline", "native_filesystem", slots, tasks)
    assert set(result["exposure_strata"]) == {"full_file", "bounded_excerpt"}
    for group in result["exposure_strata"].values():
        assert group["whole_split_denominator"] == group["unavailable_count"] == 1
        assert group["graded_denominator"] == 0
        assert group["strata"]["body"]["mean_recall_at_5"] is None
    with pytest.raises(ValueError, match="preserve every declared task"):
        describe_comparability("native_tools_baseline", "native_filesystem", slots[:1], tasks)
