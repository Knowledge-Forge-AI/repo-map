"""Source-bound evaluation summary v2 preserving mode, fallback, surface, style, and exposure (Unit 3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_slots_v2 import upgrade_slot_to_v2

BASELINE_REPORT_SCHEMA_V2 = "cloe-retrieval-baseline-report-v2"

W3_DEFAULT_ARMS: tuple[str, ...] = (
    "native_tools_baseline",
    "current_graph_baseline:sqlite",
    "current_graph_baseline:postgresql",
    "captured_projection_reference:sqlite",
    "captured_projection_reference:postgresql",
    "postgres_native_fts:postgresql",
)


def _fallback_group_key(fb: Mapping[str, Any] | None) -> tuple[str, str, str, bool] | None:
    if not isinstance(fb, Mapping):
        return None
    return (
        str(fb.get("from_mode") or ""),
        str(fb.get("to_mode") or ""),
        str(fb.get("reason_code") or ""),
        bool(fb.get("caller_selected", False)),
    )


def _summarize_slot_group(
    arm_id: str,
    backend: str,
    stratum: str,
    exposure: str,
    req_mode: str,
    eff_mode: str,
    fb_dict: dict[str, Any] | None,
    surface: str,
    style: str,
    group_slots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    pos_graded = [
        s
        for s in group_slots
        if s.get("grading_rule") in {"ranked_positive", "direct_handoff"}
        and s.get("grading_state") in {"correct", "partial", "incorrect"}
    ]
    n_pos = len(pos_graded)
    unavail = sum(1 for s in group_slots if s.get("execution_state") == "unavailable")
    refused = sum(1 for s in group_slots if s.get("execution_state") == "refused")
    failed = sum(1 for s in group_slots if s.get("execution_state") == "failed")
    safety_slots = [s for s in group_slots if s.get("grading_rule") == "safety_refusal"]
    safety_ok = sum(1 for s in safety_slots if s.get("safety_refusal_correct") is True)
    absent_slots = [s for s in group_slots if s.get("grading_rule") == "absent_answer"]
    absent_ok = sum(1 for s in absent_slots if s.get("absent_answer_correct") is True)
    return {
        "arm_id": arm_id,
        "backend": backend,
        "comparability_stratum": stratum,
        "comparator_exposure": exposure,
        "requested_mode": req_mode,
        "effective_mode": eff_mode,
        "fallback": dict(fb_dict) if fb_dict is not None else None,
        "match_surface": surface,
        "query_style": style,
        "slot_count": len(group_slots),
        "supported_count": len(group_slots) - unavail,
        "graded_count": n_pos,
        "unavailable_count": unavail,
        "refused_count": refused,
        "failed_count": failed,
        "safety_refusal_correct_count": safety_ok,
        "safety_refusal_total": len(safety_slots),
        "absent_answer_correct_count": absent_ok,
        "absent_answer_total": len(absent_slots),
        "mean_recall_at_5": (
            round(sum(float(s["metrics"]["recall@5"]) for s in pos_graded) / n_pos, 6)
            if n_pos > 0
            else None
        ),
        "mean_mrr_at_5": (
            round(sum(float(s["metrics"]["mrr@5"]) for s in pos_graded) / n_pos, 6)
            if n_pos > 0
            else None
        ),
        "mean_ndcg_at_5": (
            round(sum(float(s["metrics"]["ndcg@5"]) for s in pos_graded) / n_pos, 6)
            if n_pos > 0
            else None
        ),
        "task_ids": [str(s["task_id"]) for s in group_slots],
    }


def build_mode_surface_style_strata(
    arm_id: str,
    backend: str,
    slots_v2: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group v2 slots by stratum, exposure, requested/effective mode, fallback, surface, and style."""
    groups: dict[
        tuple[str, str, str, str, tuple[str, str, str, bool] | None, str, str],
        tuple[dict[str, Any] | None, list[Mapping[str, Any]]],
    ] = {}
    for slot in slots_v2:
        raw_fb = slot.get("fallback")
        fb_dict = dict(raw_fb) if isinstance(raw_fb, Mapping) else None
        key = (
            str(slot["comparability_stratum"]),
            str(slot["comparator_exposure"]),
            str(slot["requested_mode"]),
            str(slot["effective_mode"]),
            _fallback_group_key(fb_dict),
            str(slot["match_surface"]),
            str(slot["query_style"]),
        )
        if key not in groups:
            groups[key] = (fb_dict, [])
        groups[key][1].append(slot)

    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (k[0], k[1], k[2], k[3], k[5], k[6], str(k[4])),
    )
    out: list[dict[str, Any]] = []
    for key in ordered_keys:
        stratum, exposure, req_mode, eff_mode, _fb_key, surface, style = key
        fb_dict, group_slots = groups[key]
        out.append(
            _summarize_slot_group(
                arm_id,
                backend,
                stratum,
                exposure,
                req_mode,
                eff_mode,
                fb_dict,
                surface,
                style,
                group_slots,
            )
        )
    return out


def upgrade_arm_summary_to_v2(
    arm_dict: Mapping[str, Any],
    tasks_by_id: Mapping[str, EvaluationTask],
    *,
    envelopes_by_task: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Upgrade a single arm summary dictionary to v2 with source-bound slot and stratum metadata."""
    out = dict(arm_dict)
    arm_id = str(out["arm_id"])
    backend = str(out["backend"])
    exposures_by_task = dict(out.get("comparator_exposure_by_task", {}))

    slots_v2: list[dict[str, Any]] = []
    for raw_slot in out.get("slots", ()):
        if not isinstance(raw_slot, Mapping):
            continue
        t_id = str(raw_slot["task_id"])
        task = tasks_by_id[t_id]
        exposure = str(
            raw_slot.get("comparator_exposure")
            or exposures_by_task.get(t_id)
            or "unknown"
        )
        env_dict = envelopes_by_task.get(t_id) if envelopes_by_task is not None else None
        slots_v2.append(
            upgrade_slot_to_v2(
                raw_slot,
                task,
                arm_id=arm_id,
                backend=backend,
                comparator_exposure=exposure,
                envelope_dict=env_dict,
            )
        )

    out["slots"] = slots_v2
    out["mode_surface_style_strata"] = build_mode_surface_style_strata(
        arm_id, backend, slots_v2
    )

    exp_strata_raw = out.get("exposure_strata")
    if isinstance(exp_strata_raw, Mapping):
        new_exp_strata: dict[str, Any] = {}
        for exp_name, exp_val in sorted(exp_strata_raw.items()):
            if not isinstance(exp_val, Mapping):
                continue
            exp_copy = dict(exp_val)
            exp_slots = [s for s in slots_v2 if s["comparator_exposure"] == exp_name]
            exp_copy["mode_surface_style_strata"] = build_mode_surface_style_strata(
                arm_id, backend, exp_slots
            )
            new_exp_strata[exp_name] = exp_copy
        out["exposure_strata"] = new_exp_strata

    return out


__all__ = [
    "BASELINE_REPORT_SCHEMA_V2",
    "W3_DEFAULT_ARMS",
    "build_mode_surface_style_strata",
    "upgrade_arm_summary_to_v2",
]
