"""File-level gold-target collapsing, snapshot-bound file projection, and file metrics for W5 (ADR 0137)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Any

from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.query_contracts import EvaluationLocator
from retrieval_evaluation_schema import EvaluationTask, GoldTarget
from retrieval_semantic_fusion import (
    CollapsedArmFileHit,
    FileIdentityTuple,
    FusedFileHit,
)
from retrieval_semantic_representation import (
    RepresentationValidationError,
    VerifiedPublicationPin,
    _require,
    _validate_representation_string,
    validate_relative_path,
)

DEFAULT_CUTOFFS: tuple[int, ...] = (1, 3, 5, 10)


def assert_calibration_split_only(task: EvaluationTask | Any) -> None:
    """Reject any non-calibration task in W5 foundation evaluation helpers."""
    split = getattr(task, "split", None)
    _require(
        split == "calibration",
        "held_out_execution_forbidden",
        f"task {getattr(task, 'task_id', '<unknown>')!r} has split={split!r}; only 'calibration' is permitted",
    )


@dataclass(frozen=True)
class CollapsedFileGoldTarget:
    """Unique file-level gold target collapsed by (binding_id, source_relative_path) with max grade."""

    binding_id: str
    source_relative_path: str
    relevance_grade: int
    source_gold_count: int
    canonical_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_relative_path": self.source_relative_path,
            "relevance_grade": self.relevance_grade,
            "source_gold_count": self.source_gold_count,
            "canonical_keys": list(self.canonical_keys),
        }


def _normalize_binding_id(binding_id: str, graph_id: str | None) -> str:
    if graph_id and not binding_id.startswith("bind1:"):
        return str(graph_source_binding_id(graph_id, binding_id))
    return binding_id


def collapse_gold_targets_to_files(
    gold_targets: Sequence[GoldTarget | Any],
    *,
    graph_id: str | None = None,
) -> tuple[CollapsedFileGoldTarget, ...]:
    """Collapse span/node gold targets to unique (binding_id, source_relative_path) using max grade."""
    grouped: dict[tuple[str, str], tuple[int, int, set[str]]] = {}
    order: list[tuple[str, str]] = []
    for gold in gold_targets:
        loc = getattr(gold, "locator", None)
        _require(loc is not None, "invalid_gold_target", "gold target missing locator")
        b_id = _normalize_binding_id(
            _validate_representation_string(getattr(loc, "binding_id", ""), "gold.binding_id"),
            graph_id,
        )
        rel_path = _validate_representation_string(
            getattr(loc, "source_relative_path", ""),
            "gold.source_relative_path",
        )
        try:
            validate_relative_path(rel_path, "gold.source_relative_path")
        except ValueError as exc:
            raise RepresentationValidationError("invalid_relative_path", str(exc)) from exc
        grade = getattr(gold, "relevance_grade", -1)
        _require(type(grade) is int and 0 <= grade <= 3, "invalid_gold_grade", f"invalid grade: {grade!r}")
        c_key = getattr(gold, "canonical_key", None)
        key = (b_id, rel_path)
        if key not in grouped:
            order.append(key)
            grouped[key] = (grade, 1, {str(c_key)} if isinstance(c_key, str) and c_key else set())
        else:
            prev_grade, cnt, c_keys = grouped[key]
            if isinstance(c_key, str) and c_key:
                c_keys.add(c_key)
            grouped[key] = (max(prev_grade, grade), cnt + 1, c_keys)
    return tuple(
        CollapsedFileGoldTarget(k[0], k[1], grouped[k][0], grouped[k][1], tuple(sorted(grouped[k][2])))
        for k in order
    )


def _resolve_task_selected_bindings(
    task: EvaluationTask | Any | None,
    verified_pin: VerifiedPublicationPin,
) -> frozenset[str] | None:
    if task is None:
        return None
    assert_calibration_split_only(task)
    t_graph, t_gen = getattr(task, "graph_id", None), getattr(task, "generation", None)
    _require(t_graph == verified_pin.graph_id, "graph_id_mismatch", f"task graph_id {t_graph!r} != pin {verified_pin.graph_id!r}")
    _require(t_gen == verified_pin.generation, "generation_mismatch", f"task generation {t_gen!r} != pin {verified_pin.generation!r}")
    raw_sel = getattr(task, "selected_bindings", ())
    return frozenset(_normalize_binding_id(str(b), str(t_graph)) for b in raw_sel) if raw_sel else None


def verify_and_project_returned_files(
    returned_items: Sequence[Any],
    *,
    verified_pin: VerifiedPublicationPin,
    task: EvaluationTask | Any | None = None,
    private_markers: Sequence[str] = (),
) -> tuple[tuple[str, str], ...]:
    """Verify snapshot/publication alignment for returned items and deduplicate in rank order."""
    _require(isinstance(verified_pin, VerifiedPublicationPin), "unverified_publication_pin", "VerifiedPublicationPin required")
    verified_pin.revalidate_current()
    selected_bindings = _resolve_task_selected_bindings(task, verified_pin)
    snapshots = verified_pin.snapshot_by_binding()
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in returned_items:
        if isinstance(item, FileIdentityTuple):
            f_tuple = item.validate(private_markers=private_markers)
        elif isinstance(item, (CollapsedArmFileHit, FusedFileHit)):
            f_tuple = item.file_identity.validate(private_markers=private_markers)
        else:
            loc = getattr(item, "locator", item)
            b_raw = getattr(loc, "source_binding_id", getattr(loc, "binding_id", None))
            s_raw, p_raw = getattr(loc, "snapshot_id", None), getattr(loc, "source_relative_path", None)
            _require(
                type(b_raw) is str and type(s_raw) is str and type(p_raw) is str,
                "missing_file_identity_fields",
                "returned item must provide (binding_id, snapshot_id, source_relative_path)",
            )
            f_tuple = FileIdentityTuple(str(b_raw), str(s_raw), str(p_raw)).validate(private_markers=private_markers)
        if f_tuple.binding_id in verified_pin.denied_bindings:
            raise RepresentationValidationError(verified_pin.denied_bindings[f_tuple.binding_id], f"denied binding {f_tuple.binding_id!r}")
        _require(f_tuple.binding_id in verified_pin.admitted_public_bindings, "unknown_source_binding", f"binding {f_tuple.binding_id!r} not admitted")
        expected_entry = snapshots.get(f_tuple.binding_id)
        expected_snap = expected_entry[1] if expected_entry is not None else None
        _require(expected_snap == f_tuple.snapshot_id, "snapshot_id_mismatch", f"binding {f_tuple.binding_id!r} snapshot {f_tuple.snapshot_id!r} != {expected_snap!r}")
        if selected_bindings is not None:
            _require(f_tuple.binding_id in selected_bindings, "out_of_scope_binding", f"binding {f_tuple.binding_id!r} not in task.selected_bindings")
        proj = f_tuple.file_key()
        if proj not in seen:
            seen.add(proj)
            deduped.append(proj)
    return tuple(deduped)


def _verify_span_locators(
    span_locators: Sequence[EvaluationLocator | Any],
    *,
    verified_pin: VerifiedPublicationPin,
    task: EvaluationTask | Any | None = None,
    private_markers: Sequence[str] = (),
) -> None:
    if not span_locators:
        return
    selected_bindings = _resolve_task_selected_bindings(task, verified_pin)
    snapshots = verified_pin.snapshot_by_binding()
    for raw_loc in span_locators:
        loc = getattr(raw_loc, "locator", raw_loc)
        b_raw = _validate_representation_string(
            getattr(loc, "source_binding_id", None) or getattr(loc, "binding_id", None),
            "span.binding_id",
            private_markers=private_markers,
        )
        b_id = _normalize_binding_id(b_raw, verified_pin.graph_id)
        rel_p = _validate_representation_string(
            getattr(loc, "source_relative_path", None),
            "span.source_relative_path",
            private_markers=private_markers,
        )
        try:
            validate_relative_path(rel_p, "span.source_relative_path")
        except ValueError as exc:
            raise RepresentationValidationError("invalid_relative_path", str(exc)) from exc
        if b_id in verified_pin.denied_bindings:
            raise RepresentationValidationError(verified_pin.denied_bindings[b_id], f"denied binding {b_id!r}")
        _require(b_id in verified_pin.admitted_public_bindings, "unknown_source_binding", f"binding {b_id!r} not admitted")
        snap_raw = getattr(loc, "snapshot_id", None)
        if snap_raw is not None:
            _require(snapshots.get(b_id, (0, ""))[1] == snap_raw, "snapshot_id_mismatch", "span locator snapshot mismatch")
        if selected_bindings is not None:
            _require(b_id in selected_bindings, "out_of_scope_binding", f"binding {b_id!r} not in task.selected_bindings")


def compute_file_level_ranking_metrics(
    returned_items: Sequence[Any],
    gold_targets: Sequence[GoldTarget | Any],
    *,
    verified_pin: VerifiedPublicationPin,
    task: EvaluationTask | Any | None = None,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    private_markers: Sequence[str] = (),
) -> dict[str, float]:
    """Compute file_recall@k, file_mrr@k, and file_ndcg@k over unique positive gold files."""
    projected_files = verify_and_project_returned_files(
        returned_items, verified_pin=verified_pin, task=task, private_markers=private_markers
    )
    collapsed_gold = collapse_gold_targets_to_files(gold_targets, graph_id=verified_pin.graph_id)
    positive_files = {
        (g.binding_id, g.source_relative_path): g.relevance_grade
        for g in collapsed_gold
        if g.relevance_grade > 0
    }
    metrics: dict[str, float] = {}
    if not positive_files:
        for k in cutoffs:
            metrics[f"file_recall@{k}"] = metrics[f"file_mrr@{k}"] = metrics[f"file_ndcg@{k}"] = 0.0
        return metrics
    rank_gains = [
        (rank_idx, positive_files[file_key])
        for rank_idx, file_key in enumerate(projected_files, start=1)
        if file_key in positive_files
    ]
    ideal_grades = sorted(positive_files.values(), reverse=True)
    total_positive = len(positive_files)
    for k in cutoffs:
        hits_at_k = [(r, rel) for r, rel in rank_gains if r <= k]
        recall_k = len(hits_at_k) / total_positive
        mrr_k = 1.0 / hits_at_k[0][0] if hits_at_k else 0.0
        dcg_k = sum(((2**rel) - 1.0) / math.log2(r + 1.0) for r, rel in hits_at_k)
        idcg_k = sum(((2**rel) - 1.0) / math.log2(idx + 2.0) for idx, rel in enumerate(ideal_grades[:k]))
        metrics[f"file_recall@{k}"] = round(recall_k, 6)
        metrics[f"file_mrr@{k}"] = round(mrr_k, 6)
        metrics[f"file_ndcg@{k}"] = round((dcg_k / idcg_k) if idcg_k > 0.0 else 0.0, 6)
    return metrics


__all__ = [
    "DEFAULT_CUTOFFS",
    "CollapsedFileGoldTarget",
    "_normalize_binding_id",
    "_resolve_task_selected_bindings",
    "_verify_span_locators",
    "assert_calibration_split_only",
    "collapse_gold_targets_to_files",
    "compute_file_level_ranking_metrics",
    "verify_and_project_returned_files",
]
