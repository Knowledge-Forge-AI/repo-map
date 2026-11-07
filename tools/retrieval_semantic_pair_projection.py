"""Bounded projections shared by the per-cell pair builder."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from retrieval_semantic_pair_artifacts import refuse
from retrieval_semantic_pair_rational import rational_records
from retrieval_semantic_pair_values import grade_values_equal, unit_interval

Identity = tuple[str, str, int]
GradeSummary = Callable[[Mapping[str, object], str], dict[str, object]]


def choose_grade(
    observed: Mapping[str, object] | None,
    graded: Mapping[str, object] | None,
    summarize: GradeSummary,
) -> dict[str, object] | None:
    """Select one stored slot, refusing divergent dual sources."""

    query_grade = (
        summarize(observed, "query_observed.slot")
        if observed is not None and isinstance(observed.get("slot"), Mapping)
        else None
    )
    task_grade = (
        summarize(graded, "task_graded.slot")
        if graded is not None and isinstance(graded.get("slot"), Mapping)
        else None
    )
    if query_grade is not None and task_grade is not None:
        if not grade_values_equal(query_grade, task_grade):
            raise refuse("pair_dual_grade_mismatch")
        merged = dict(task_grade)
        merged["grade_source"] = "task_graded.slot+query_observed.slot"
        return merged
    return task_grade or query_grade


def observed_summary(event: Mapping[str, object] | None) -> dict[str, object] | None:
    """Copy stored observation values while retaining source and omission state."""

    if event is None:
        return None
    envelope = event.get("envelope")
    env = envelope if isinstance(envelope, Mapping) else {}
    slot_value = event.get("slot")
    slot = slot_value if isinstance(slot_value, Mapping) else {}
    hits = env.get("hits") if type(env.get("hits")) is list else event.get("candidates")
    hit_count = len(hits) if type(hits) is list else None
    omissions = env.get("omissions")
    omission_count = len(omissions) if type(omissions) is list else None
    recall = unit_interval(event.get("exact_reference_recall"), "pair_ann_recall")
    return {
        "execution_state": event.get("execution_state"), "reason": event.get("reason"),
        "elapsed_ns": event.get("elapsed_ns"), "query_bytes": event.get("query_bytes"),
        "capability_state": env.get("capability_state") or slot.get("capability_state"),
        "unavailable_reason": env.get("unavailable_reason"),
        "refusal_code": env.get("refusal_code"), "scope_complete": env.get("scope_complete"),
        "omission_count": omission_count,
        "omissions_status": "recorded" if type(omissions) is list else "not_recorded",
        "returned_hit_count": hit_count,
        "available_empty": (
            (env.get("capability_state") or slot.get("capability_state")) == "available"
            and hit_count == 0
        ),
        "ann_exact_reference_recall": recall,
        "byte_accounting": event.get("byte_accounting", env.get("byte_accounting")),
        "byte_accounting_source": (
            "event.byte_accounting" if "byte_accounting" in event
            else "envelope.byte_accounting" if "byte_accounting" in env
            else "not_recorded"
        ),
        "timing_source": "event.elapsed_ns" if "elapsed_ns" in event else "not_recorded",
    }


def cell_rational_records(
    event: Mapping[str, object] | None,
    cell: Mapping[str, object] | None,
    identity: Identity,
) -> list[dict[str, object]]:
    """Retain exact rational values from both journal and V2 cell sources."""

    sources: list[tuple[str, object]] = []
    if event is not None:
        sources.append(("journal", event))
    if cell is not None:
        cell_value = cell.get("cell")
        if not isinstance(cell_value, Mapping):
            raise refuse("pair_result_cell")
        sources.append(("result_v2.cell", cell_value))
    records: list[dict[str, object]] = []
    for source, value in sources:
        for measurement in rational_records(value, source):
            records.append({
                "cell_identity": {
                    "task_id": identity[0],
                    "arm_id": identity[1],
                    "repetition": identity[2],
                },
                "source": source,
                "measurement": measurement,
            })
    return records


__all__ = ["cell_rational_records", "choose_grade", "observed_summary"]
