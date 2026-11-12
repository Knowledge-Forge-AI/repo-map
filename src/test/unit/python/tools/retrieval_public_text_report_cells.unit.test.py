"""Closed cell grammar and the exact 12 x 24 x 3 = 864 population algebra."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, cast

import pytest

from repomap_test_support.w5_semantic_support import make_w5_calibration_task
from retrieval_public_text_census import retained_task_sha256, task_sha256
from retrieval_public_text_fusion import METRIC_KEYS
from retrieval_public_text_report_cells import (
    ARMS, HNSW_ARMS, INCUMBENT_ARMS, LEARNED_ARMS, STATES, TOTAL_CELLS, ReportCellRefusal, cell,
    expected_cell_keys, state_counts, validate_cell, validate_cells,
)
from retrieval_public_text_tasks import SELECTED_TASKS

RESULT = {"sha256": "sha256:" + "e" * 64, "length": 10}
METRICS = {name: 0.5 for name in METRIC_KEYS}


def _cell(generation: int, task_id: str, digest: str, arm: str, repetition: int) -> dict[str, Any]:
    identity = {"generation": generation, "task_id": task_id, "task_sha256": digest, "arm": arm,
                "repetition": repetition}
    if generation == 2 and arm in LEARNED_ARMS:
        return cell(**cast(dict[str, Any], identity), state="unavailable",
                    reason=("v1_decision", "generation_document_only"))
    if arm in INCUMBENT_ARMS:
        return cell(**cast(dict[str, Any], identity), state="completed", metrics=METRICS, result=RESULT,
                    publication_coverage="complete")
    plan = {**RESULT, "index_selected": True} if arm in HNSW_ARMS else None
    return cell(**cast(dict[str, Any], identity), state="completed", capability="complete", metrics=METRICS,
                result=RESULT, plan=plan,
                publication_coverage="partial")


def _population() -> list[dict[str, Any]]:
    return [_cell(*key) for key in expected_cell_keys()]


def _code(call: Any, *args: Any) -> str:
    with pytest.raises(ReportCellRefusal) as error:
        call(*args)
    return error.value.code


def test_closed_arms_tasks_and_population_algebra() -> None:
    assert len(ARMS) == 12 and ARMS[:6] == INCUMBENT_ARMS and len(set(ARMS)) == 12
    assert ARMS[6:] == ("exact_vector:canonical-node-v1", "hnsw_vector:canonical-node-v1",
                        "hybrid_rrf:canonical-node-v1", "exact_vector:canonical-node-public-text-v2",
                        "hnsw_vector:canonical-node-public-text-v2", "hybrid_rrf:canonical-node-public-text-v2")
    assert TOTAL_CELLS == 864 and len(expected_cell_keys()) == 864
    assert sum(1 for key in expected_cell_keys() if key[0] == 1) == 23 * 12 * 3
    assert [key[1] for key in expected_cell_keys() if key[0] == 2] == ["cal-23"] * 36
    counts = validate_cells(_population())
    assert counts == {"completed": 846, "refused": 0, "unavailable": 18, "failed": 0, "not_run": 0, "unknown": 0}
    assert sum(counts.values()) == 864 and tuple(counts) == STATES


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda cells: cells.pop(100), "cell_missing"),
    (lambda cells: cells.append(copy.deepcopy(cells[0])), "cell_duplicate"),
    (lambda cells: cells.__setitem__(5, {**cells[5], "repetition": 2}), "cell_duplicate"),
    (lambda cells: cells.__setitem__(0, {**cells[0], "task_id": "cal-99"}), "cell_extra"),
    (lambda cells: cells.__setitem__(0, {**cells[0], "generation": 2}), "cell_extra"),
    (lambda cells: cells.insert(0, cells.pop(1)), "cell_order"),
    (lambda cells: cells.clear(), "cell_missing"),
])
def test_missing_duplicate_extra_and_reordered_tuples_refuse(mutate: Any, code: str) -> None:
    cells = _population()
    mutate(cells)
    assert _code(validate_cells, cells) == code


def test_unicode_v1_scheme_digest_never_substitutes_for_the_retained_pin() -> None:
    task = make_w5_calibration_task(task_id="cal-20", graph_id="mixed-v1")
    unicode_task = replace(task, question="Où est défini le pipeline — café?").validate()
    assert task_sha256(unicode_task) != retained_task_sha256(unicode_task)
    cells = _population()
    index = next(i for i, c in enumerate(cells) if c["task_id"] == "cal-20")
    pinned = dict((task_id, digest) for task_id, _g, digest in SELECTED_TASKS)["cal-20"]
    assert cells[index]["task_sha256"] == pinned
    for substitute in (task_sha256(unicode_task), retained_task_sha256(unicode_task)):
        cells[index] = {**cells[index], "task_sha256": substitute}
        assert _code(validate_cells, cells) == "cell_extra"


def test_generation_two_learned_cells_keep_their_original_decision() -> None:
    cells = _population()
    index = next(i for i, c in enumerate(cells) if c["generation"] == 2 and c["arm"] == LEARNED_ARMS[0])
    for replacement in (
        _cell(1, "cal-01", "sha256:" + "0" * 64, LEARNED_ARMS[0], 1) | {"generation": 2, "task_id": "cal-23",
                                                                       "task_sha256": cells[index]["task_sha256"]},
        {**cells[index], "reason": {"source": "study", "code": "study_not_reached"}},
        {**cells[index], "state": "failed"},
    ):
        mutated = list(cells)
        mutated[index] = replacement
        assert _code(validate_cells, mutated) == "cell_generation_two_decision"


@pytest.mark.parametrize(("arm", "change", "code"), [
    (INCUMBENT_ARMS[0], {"extra": 1}, "cell_fields"),
    (INCUMBENT_ARMS[0], {"repetition": 4}, "cell_identity"),
    (INCUMBENT_ARMS[0], {"repetition": True}, "cell_identity"),
    (INCUMBENT_ARMS[0], {"arm": "hybrid_rrf"}, "cell_identity"),
    (INCUMBENT_ARMS[0], {"task_sha256": "sha256:" + "E" * 64}, "cell_identity"),
    (INCUMBENT_ARMS[0], {"state": "skipped"}, "cell_state"),
    (INCUMBENT_ARMS[0], {"incomplete": 0}, "cell_flag_type"),
    (INCUMBENT_ARMS[0], {"publication_coverage": "full"}, "cell_publication_coverage"),
    (INCUMBENT_ARMS[0], {"reason": {"source": "sql", "code": "x"}}, "cell_reason_state"),
    (INCUMBENT_ARMS[0], {"capability": "complete"}, "cell_capability"),
    (INCUMBENT_ARMS[0], {"metrics": {**METRICS, "file_recall@1": 0}}, "cell_metrics"),
    (INCUMBENT_ARMS[0], {"metrics": {**METRICS, "file_recall@1": float("nan")}}, "cell_metrics"),
    (INCUMBENT_ARMS[0], {"metrics": {**METRICS, "file_mrr@10": 1.5}}, "cell_metrics"),
    (INCUMBENT_ARMS[0], {"metrics": {k: v for k, v in METRICS.items() if k != "file_ndcg@10"}}, "cell_metrics"),
    (INCUMBENT_ARMS[0], {"metrics": None}, "cell_metrics"),
    (INCUMBENT_ARMS[0], {"result": {"sha256": "sha256:bad", "length": 1}}, "cell_result"),
    (INCUMBENT_ARMS[0], {"result": None}, "cell_result"),
    (INCUMBENT_ARMS[0], {"plan": {**RESULT, "index_selected": True}}, "cell_plan_arm"),
    (LEARNED_ARMS[0], {"capability": None}, "cell_capability_state"),
    (LEARNED_ARMS[0], {"capability": "partial"}, "cell_partial_flags"),
    (LEARNED_ARMS[0], {"truncated": True}, "cell_partial_flags"),
    (LEARNED_ARMS[1], {"plan": None}, "cell_plan"),
    (LEARNED_ARMS[1], {"plan": {**RESULT, "index_selected": False}}, "cell_plan_index"),
    (LEARNED_ARMS[1], {"plan": {**RESULT, "index_selected": 1}}, "cell_plan"),
])
def test_each_cell_field_rule_refuses(arm: str, change: dict[str, Any], code: str) -> None:
    value = {**_cell(1, "cal-01", "sha256:" + "0" * 64, arm, 1), **change}
    assert _code(validate_cell, value) == code


@pytest.mark.parametrize(("state", "reason"), [
    ("refused", ("public_text_decision", "public_text_projection_truncated")),
    ("unavailable", ("sql", "enrichment_unavailable")),
    ("failed", ("study", "ann_output_shape")),
    ("not_run", ("study", "study_not_reached")),
    ("unknown", ("native", "worker_response_absent")),
])
def test_every_non_completed_state_is_explicit_and_never_scored(state: str, reason: tuple[str, str]) -> None:
    value = cell(generation=1, task_id="cal-01", task_sha256="sha256:" + "0" * 64, arm=LEARNED_ARMS[3],
                 repetition=1, state=state, reason=reason)
    assert value["metrics"] is None and value["reason"] == {"source": reason[0], "code": reason[1]}
    assert _code(validate_cell, {**value, "metrics": METRICS}) == "cell_metrics_state"
    assert _code(validate_cell, {**value, "reason": None}) == "cell_reason_state"
    if state == "unknown":
        assert _code(validate_cell, {**value, "result": RESULT}) == "cell_unknown_state"


def test_reason_grammar_and_closed_study_codes() -> None:
    base = {"generation": 1, "task_id": "cal-01", "task_sha256": "sha256:" + "0" * 64, "arm": LEARNED_ARMS[3],
            "repetition": 1, "state": "refused"}
    for reason in (("study", "made_up_code"), ("operator", "x"), ("sql", "Upper"), ("sql", "a" * 97), ("sql", "")):
        with pytest.raises(ReportCellRefusal) as error:
            cell(**cast(dict[str, Any], base), reason=reason)
        assert error.value.code in {"cell_reason", "cell_study_reason"}
    assert cell(**cast(dict[str, Any], base), reason=("study", "cleanup_failed:relation_identity_changed"))["reason"]["code"].startswith(
        "cleanup_failed")


def test_hnsw_plan_only_on_hnsw_arms_and_index_not_selected_is_not_credited() -> None:
    base = {"generation": 1, "task_id": "cal-01", "task_sha256": "sha256:" + "0" * 64, "repetition": 1}
    unselected = cell(**cast(dict[str, Any], base), arm=LEARNED_ARMS[4], state="unavailable",
                      reason=("sql", "index_not_selected"),
                      plan={**RESULT, "index_selected": False}, result=RESULT)
    assert unselected["metrics"] is None and unselected["capability"] is None
    assert _code(validate_cell, {**unselected, "plan": {**RESULT, "index_selected": True}}) == "cell_plan_index"
    assert _code(validate_cell, {**unselected, "plan": None}) == "cell_plan"
    exact = {**base, "arm": LEARNED_ARMS[3], "state": "unavailable", "reason": ("sql", "index_not_selected")}
    with pytest.raises(ReportCellRefusal):
        cell(**cast(dict[str, Any], exact), plan={**RESULT, "index_selected": False})


@pytest.mark.parametrize(("state", "reason"), [
    ("completed", None), ("unavailable", ("sql", "index_not_selected")), ("failed", ("study", "ann_sql_failed")),
    ("refused", ("study", "study_relation_changed")),
])
@pytest.mark.parametrize(("name", "value", "code"), [
    ("result", {**RESULT, "raw": "excerpt text"}, "cell_result"),
    ("result", {"sha256": RESULT["sha256"]}, "cell_result"),
    ("result", {**RESULT, "length": True}, "cell_result"),
    ("result", {**RESULT, "length": -1}, "cell_result"),
    ("result", {**RESULT, "sha256": "sha256:" + "E" * 64}, "cell_result"),
    ("plan", {**RESULT, "index_selected": False, "rows": []}, "cell_plan"),
    ("plan", {"sha256": RESULT["sha256"], "index_selected": False}, "cell_plan"),
    ("plan", {**RESULT, "length": 1.0, "index_selected": False}, "cell_plan"),
    ("plan", {**RESULT, "sha256": None, "index_selected": False}, "cell_plan"),
    ("plan", {**RESULT, "index_selected": "false"}, "cell_plan"),
])
def test_result_and_plan_maps_are_closed_and_strict_in_every_state(
        state: str, reason: tuple[str, str] | None, name: str, value: dict[str, Any], code: str) -> None:
    """F8: no extra key, missing key, bool length or malformed digest survives in any state."""
    completed = state == "completed"
    plan = {**RESULT, "index_selected": completed}
    base = cell(generation=1, task_id="cal-01", task_sha256="sha256:" + "0" * 64, arm=LEARNED_ARMS[1],
                repetition=1, state=state, reason=reason, capability="complete" if completed else None,
                metrics=METRICS if completed else None, result=RESULT, plan=plan)
    assert _code(validate_cell, {**base, name: value}) == code


def test_partial_capability_requires_incomplete_and_truncated_flags() -> None:
    value = cell(generation=1, task_id="cal-01", task_sha256="sha256:" + "0" * 64, arm=LEARNED_ARMS[3],
                 repetition=1, state="completed", capability="partial", incomplete=True, truncated=True,
                 metrics=METRICS, result=RESULT, publication_coverage="partial")
    assert value["capability"] == "partial"
    assert state_counts([value]) == {"completed": 1, "refused": 0, "unavailable": 0, "failed": 0, "not_run": 0,
                                     "unknown": 0}
    assert _code(validate_cell, {**value, "incomplete": False}) == "cell_partial_flags"


def test_population_with_every_state_still_sums_to_the_total() -> None:
    cells = _population()
    variants = {"refused": ("public_text_decision", "public_text_projection_truncated"),
                "failed": ("study", "ann_sql_failed"), "not_run": ("study", "worker_not_run"),
                "unknown": ("native", "worker_response_absent")}
    for offset, (state, reason) in enumerate(variants.items()):
        index = next(i for i, c in enumerate(cells) if c["arm"] == LEARNED_ARMS[3] and c["generation"] == 1) + offset * 3
        identity = {k: cells[index][k] for k in ("generation", "task_id", "task_sha256", "arm", "repetition")}
        cells[index] = cell(**identity, state=state, reason=reason)
    counts = validate_cells(cells)
    assert counts["unknown"] == 1 and counts["completed"] == 842 and sum(counts.values()) == 864
