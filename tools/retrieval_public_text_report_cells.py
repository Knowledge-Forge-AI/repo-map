"""Closed cell grammar and population algebra for ``cloe-public-text-calibration-v1`` (study section 11).

Twelve closed ordered arms x 24 pinned tasks x 3 repetitions = 864 cells. A
cell's ``task_sha256`` is the registered retained (ASCII-scheme) pin; the v1
UTF-8 query digest is a different scheme and never substitutes for it. Every
cell carries exactly one closed state; missing, unknown or refused work is
never zero, and unavailable cells are never dropped.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math
import re
from typing import Any

from retrieval_public_text_fusion import METRIC_KEYS
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_tasks import SELECTED_TASKS
from retrieval_semantic_experiment_contracts import EXPERIMENT_ARMS

INCUMBENT_ARMS = EXPERIMENT_ARMS[:6]
LEARNED_ARMS = tuple(f"{kind}:{rep}" for rep in (ARM_V1, ARM_PTX) for kind in ("exact_vector", "hnsw_vector", "hybrid_rrf"))
ARMS = INCUMBENT_ARMS + LEARNED_ARMS
HNSW_ARMS = frozenset(arm for arm in LEARNED_ARMS if arm.startswith("hnsw_vector:"))
REPETITIONS = (1, 2, 3)
STATES = ("completed", "refused", "unavailable", "failed", "not_run", "unknown")
REASON_SOURCES = frozenset({"v1_decision", "public_text_decision", "study", "sql", "fusion", "native", "experiment"})
DECISION_SOURCES = frozenset({"v1_decision", "public_text_decision"})
STUDY_CODES = frozenset({
    "v1_own_record_truncated", "study_seal_refused", "study_not_reached", "study_import_refused",
    "study_relation_changed", "index_not_selected", "temp_privilege_absent", "ann_output_shape",
    "ann_result_malformed", "ann_sql_failed", "exact_sql_failed", "generation_document_only",
    "cleanup_failed", "worker_not_run", "worker_failed",
})
CELL_FIELDS = frozenset({
    "generation", "task_id", "task_sha256", "arm", "repetition", "state", "reason", "capability", "incomplete",
    "truncated", "retrieval_truncated", "publication_coverage", "metrics", "result", "plan", "file_grading",
})
# File grading is independent of execution state (study section 19.4).
FILE_GRADING_STATES = ("verified", "not_applicable", "gap", "not_run")
NOT_COMPLETED_GRADING = ("not_run", "execution_not_completed")
TOTAL_CELLS = len(SELECTED_TASKS) * len(ARMS) * len(REPETITIONS)
_CODE = re.compile(r"[a-z0-9_.:-]{1,96}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_LENGTH = 32 * 1024 * 1024


class ReportCellRefusal(ValueError):
    """Closed refusal; the code names the violated grammar or algebra rule."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("cell_") or _CODE.fullmatch(code) is None:
            raise ValueError("unknown report cell code")
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReportCellRefusal(code)


def expected_cell_keys(tasks: Sequence[tuple[str, int, str]] = SELECTED_TASKS) -> tuple[tuple[int, str, str, str, int], ...]:
    """Canonical order: generation, pinned task order, arm order, repetition."""
    return tuple((generation, task_id, digest, arm, repetition)
                 for gen in (1, 2) for task_id, generation, digest in tasks if generation == gen
                 for arm in ARMS for repetition in REPETITIONS)


def _binding(value: object, code: str, extra: frozenset[str] = frozenset()) -> None:
    """Closed ``{sha256, length}`` (plus ``extra`` keys), strict digest and non-bool bounded length."""
    _require(isinstance(value, Mapping) and set(value) == {"sha256", "length"} | extra
             and type(value["sha256"]) is str and _DIGEST.fullmatch(value["sha256"]) is not None
             and type(value["length"]) is int and 0 <= value["length"] <= _MAX_LENGTH, code)


def _plan(value: object) -> None:
    _binding(value, "cell_plan", frozenset({"index_selected"}))
    assert isinstance(value, Mapping)
    _require(type(value["index_selected"]) is bool, "cell_plan")


def _reason(value: object) -> Mapping[str, str] | None:
    if value is None:
        return None
    _require(isinstance(value, Mapping) and set(value) == {"source", "code"} and value["source"] in REASON_SOURCES
             and type(value["code"]) is str and _CODE.fullmatch(value["code"]) is not None, "cell_reason")
    assert isinstance(value, Mapping)
    if value["source"] == "study":
        code = value["code"].split(":", 1)[0]
        _require(code in STUDY_CODES, "cell_study_reason")
    return value


def _metrics(value: object) -> None:
    _require(isinstance(value, Mapping) and set(value) == set(METRIC_KEYS) and all(
        type(item) is float and math.isfinite(item) and 0.0 <= item <= 1.0 for item in value.values()),
        "cell_metrics")


def _file_grading(value: object, *, learned: bool, completed: bool) -> str:
    """Closed ``{state, reason}``; reason is null iff verified; learned completion needs verified grading."""
    _require(isinstance(value, Mapping) and set(value) == {"state", "reason"}
             and value["state"] in FILE_GRADING_STATES, "cell_file_grading")
    assert isinstance(value, Mapping)
    state, reason = value["state"], value["reason"]
    if state == "verified":
        _require(reason is None, "cell_file_grading")
    else:
        _require(type(reason) is str and _CODE.fullmatch(reason) is not None, "cell_file_grading")
    if not completed:
        _require((state, reason) == NOT_COMPLETED_GRADING, "cell_file_grading_state")
    elif learned:
        _require(state == "verified", "cell_file_grading_state")
    else:
        _require(state != "not_run", "cell_file_grading_state")
    return state


def validate_cell(cell: object) -> None:
    """Closed fields, strict types, closed state/reason grammar, hnsw-only plan and learned-only capability."""
    _require(isinstance(cell, Mapping) and set(cell) == CELL_FIELDS, "cell_fields")
    assert isinstance(cell, Mapping)
    _require(type(cell["generation"]) is int and cell["generation"] in (1, 2) and type(cell["task_id"]) is str
             and type(cell["task_sha256"]) is str and _DIGEST.fullmatch(cell["task_sha256"]) is not None
             and cell["arm"] in ARMS and type(cell["repetition"]) is int and cell["repetition"] in REPETITIONS,
             "cell_identity")
    _require(cell["state"] in STATES, "cell_state")
    for name in ("incomplete", "truncated", "retrieval_truncated"):
        _require(type(cell[name]) is bool, "cell_flag_type")
    _require(cell["publication_coverage"] in ("complete", "partial", "unknown"), "cell_publication_coverage")
    reason = _reason(cell["reason"])
    learned, completed = cell["arm"] in LEARNED_ARMS, cell["state"] == "completed"
    _require((reason is None) == completed, "cell_reason_state")
    _require(cell["capability"] in ((None, "complete", "partial") if learned else (None,)), "cell_capability")
    _require(cell["capability"] is not None or not (learned and completed), "cell_capability_state")
    if cell["capability"] == "partial":
        _require(cell["incomplete"] is True and cell["truncated"] is True, "cell_partial_flags")
    if cell["truncated"]:
        _require(cell["incomplete"] is True, "cell_partial_flags")
    grading = _file_grading(cell["file_grading"], learned=learned, completed=completed)
    if grading == "verified":
        _metrics(cell["metrics"])
    else:
        _require(cell["metrics"] is None, "cell_metrics_state")
    if completed:
        _binding(cell["result"], "cell_result")
    elif cell["result"] is not None:
        _binding(cell["result"], "cell_result")
    if cell["state"] == "unknown":
        _require(cell["result"] is None and cell["plan"] is None, "cell_unknown_state")
    plan = cell["plan"]
    if cell["arm"] not in HNSW_ARMS:
        _require(plan is None, "cell_plan_arm")
    elif completed or (reason is not None and reason["code"] == "index_not_selected"):
        _plan(plan)
        assert isinstance(plan, Mapping)
        _require(plan["index_selected"] is completed, "cell_plan_index")
    elif plan is not None:
        _plan(plan)


def state_counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(cell["state"] for cell in cells)
    return {state: counts.get(state, 0) for state in STATES}


def file_grading_counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Recomputed separately from execution states; the two families never substitute."""
    counts = Counter(cell["file_grading"]["state"] for cell in cells)
    return {state: counts.get(state, 0) for state in FILE_GRADING_STATES}


def validate_cells(cells: object, *, tasks: Sequence[tuple[str, int, str]] = SELECTED_TASKS) -> dict[str, int]:
    """Exact 864-tuple population in canonical order; returns the state counts (summing to the total)."""
    _require(type(cells) is list, "cell_population")
    assert isinstance(cells, list)
    for cell in cells:
        validate_cell(cell)
    keys = [(c["generation"], c["task_id"], c["task_sha256"], c["arm"], c["repetition"]) for c in cells]
    expected = expected_cell_keys(tasks)
    _require(len(keys) == len(set(keys)), "cell_duplicate")
    _require(set(keys) <= set(expected), "cell_extra")
    _require(set(keys) >= set(expected), "cell_missing")
    _require(tuple(keys) == expected, "cell_order")
    groups = Counter((c["generation"], c["arm"]) for c in cells)
    per_generation = Counter(generation for _task, generation, _digest in tasks)
    _require(all(groups[(g, arm)] == per_generation[g] * len(REPETITIONS) for g in (1, 2) for arm in ARMS),
             "cell_group_count")
    generation_two = {task_id for task_id, generation, _digest in tasks if generation == 2}
    for cell in cells:
        if cell["task_id"] in generation_two and cell["arm"] in LEARNED_ARMS:
            reason = cell["reason"]
            _require(cell["state"] in ("refused", "unavailable") and reason is not None
                     and reason["source"] in DECISION_SOURCES, "cell_generation_two_decision")
    counts = state_counts(cells)
    _require(sum(counts.values()) == len(expected), "cell_state_total")
    return counts


def cell(*, generation: int, task_id: str, task_sha256: str, arm: str, repetition: int, state: str,
         reason: tuple[str, str] | None = None, capability: str | None = None, incomplete: bool = False,
         truncated: bool = False, retrieval_truncated: bool = False, publication_coverage: str = "unknown",
         metrics: Mapping[str, float] | None = None, result: Mapping[str, Any] | None = None,
         plan: Mapping[str, Any] | None = None, file_grading: tuple[str, str | None] | None = None) -> dict[str, Any]:
    """Build one validated cell; ``reason`` is ``(source, code)``.

    ``file_grading`` defaults to ``verified`` when metrics are supplied and to
    ``not_run/execution_not_completed`` for a non-completed cell; a completed
    incumbent without verified metrics must name its actual grading state.
    """
    if file_grading is None:
        file_grading = ("verified", None) if metrics is not None else NOT_COMPLETED_GRADING
    value = {
        "generation": generation, "task_id": task_id, "task_sha256": task_sha256, "arm": arm,
        "repetition": repetition, "state": state,
        "reason": None if reason is None else {"source": reason[0], "code": reason[1]},
        "capability": capability, "incomplete": incomplete, "truncated": truncated,
        "retrieval_truncated": retrieval_truncated, "publication_coverage": publication_coverage,
        "metrics": None if metrics is None else dict(metrics), "result": None if result is None else dict(result),
        "plan": None if plan is None else dict(plan),
        "file_grading": {"state": file_grading[0], "reason": file_grading[1]},
    }
    validate_cell(value)
    return value


__all__ = [
    "ARMS", "CELL_FIELDS", "DECISION_SOURCES", "FILE_GRADING_STATES", "HNSW_ARMS", "INCUMBENT_ARMS", "LEARNED_ARMS",
    "NOT_COMPLETED_GRADING", "REASON_SOURCES", "REPETITIONS", "ReportCellRefusal", "STATES", "STUDY_CODES",
    "TOTAL_CELLS", "cell", "expected_cell_keys", "file_grading_counts", "state_counts", "validate_cell",
    "validate_cells",
]
