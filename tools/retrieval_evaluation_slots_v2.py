"""Per-slot v2 schema and envelope/historical metadata extraction for CLOE W3 (Unit 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from retrieval_evaluation_schema import EvaluationTask


def infer_slot_query_style(
    arm_id: str,
    task: EvaluationTask,
    envelope_dict: Mapping[str, Any] | None = None,
) -> str:
    """Resolve the deterministic query_style label for one (arm_id, task, envelope) slot."""
    if envelope_dict is not None:
        prov = envelope_dict.get("provenance")
        if isinstance(prov, Mapping):
            style = prov.get("query_style")
            if isinstance(style, str) and style:
                return style
    plan = task.permitted_query_plan
    is_handoff = (
        str(plan.get("workflow") or "") == "direct_handoff"
        or task.intended_match_surface == "direct_handoff"
    )
    if arm_id == "postgres_native_fts:postgresql":
        if is_handoff or task.requested_mode in {"graph_investigation", "semantic_discovery"}:
            return "unsupported"
        if (
            set(task.selected_bindings).issubset({"feeds", "mailbox"})
            and task.intended_match_surface != "captured_text"
        ):
            return "unsupported"
        if task.requested_mode in {"literal_captured_text", "current_literal_enumeration"}:
            return "literal_captured_text"
        raw_style = plan.get("lexical_query_style")
        if raw_style in {"ranked_terms", "normalized_phrase", "literal_captured_text"}:
            return str(raw_style)
        return "ranked_terms"

    if arm_id.startswith("captured_projection_reference:"):
        if is_handoff or task.requested_mode in {"graph_investigation", "semantic_discovery"}:
            return "unsupported"
        if (
            set(task.selected_bindings).issubset({"feeds", "mailbox"})
            and task.intended_match_surface != "captured_text"
        ):
            return "unsupported"
        return "literal_captured_text"

    if arm_id == "native_tools_baseline":
        if task.requested_mode == "graph_investigation":
            return "unsupported"
        if is_handoff:
            return "direct_handoff_recheck"
        return (
            "git_grep_fixed_strings"
            if bool(plan.get("fixed_strings", True))
            else "git_grep_extended_regex"
        )

    if arm_id.startswith("current_graph_baseline:"):
        if task.requested_mode in {"literal_captured_text", "semantic_discovery"}:
            return "unsupported"
        if is_handoff:
            return "node_locations_direct"
        if task.requested_mode == "ranked_discovery":
            return "navigation_search"
        if task.requested_mode == "graph_investigation":
            return "neighborhood_traversal"
        return "observation_substring_search"

    return "unknown"


def upgrade_slot_to_v2(
    slot_dict: Mapping[str, Any],
    task: EvaluationTask,
    *,
    arm_id: str,
    backend: str,
    comparator_exposure: str,
    envelope_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a source-bound v2 slot dictionary preserving mode, fallback, surface, style, and exposure."""
    out = dict(slot_dict)
    out["arm_id"] = arm_id
    out["backend"] = backend
    out["comparator_exposure"] = comparator_exposure

    if envelope_dict is not None:
        raw_fb = envelope_dict.get("fallback")
        if raw_fb is not None and not isinstance(raw_fb, Mapping):
            raise ValueError("envelope fallback must be a mapping or None")
        fb = dict(raw_fb) if isinstance(raw_fb, Mapping) else None
        if fb is not None:
            if fb.get("caller_selected") is not True:
                raise ValueError("envelope fallback requires caller_selected=True")
            if (fb.get("from_mode"), fb.get("to_mode")) != (
                envelope_dict.get("requested_mode"), envelope_dict.get("effective_mode")
            ) or not isinstance(fb.get("reason_code"), str) or not fb["reason_code"]:
                raise ValueError("envelope fallback must preserve actual modes and reason")
        raw_omissions = envelope_dict.get("omissions", ())
        if not isinstance(raw_omissions, (list, tuple)):
            raise ValueError("envelope omissions must be a list or tuple")
        omission_count = len(raw_omissions)
        req_mode_val = envelope_dict.get("requested_mode")
        eff_mode_val = envelope_dict.get("effective_mode")
        surface_val = envelope_dict.get("match_surface")
        ord_ver_val = envelope_dict.get("ordering_policy_version")
        scope_comp_val = envelope_dict.get("scope_complete")
        if not isinstance(req_mode_val, str) or not req_mode_val:
            raise ValueError("envelope requested_mode must be a non-empty string")
        if not isinstance(eff_mode_val, str) or not eff_mode_val:
            raise ValueError("envelope effective_mode must be a non-empty string")
        if not isinstance(surface_val, str) or not surface_val:
            raise ValueError("envelope match_surface must be a non-empty string")
        if not isinstance(ord_ver_val, str) or not ord_ver_val:
            raise ValueError("envelope ordering_policy_version must be a non-empty string")
        if not isinstance(scope_comp_val, bool):
            raise ValueError("envelope scope_complete must be a boolean")
        out.update(
            {
                "requested_mode": req_mode_val,
                "effective_mode": eff_mode_val,
                "fallback": fb,
                "match_surface": surface_val,
                "query_style": infer_slot_query_style(arm_id, task, envelope_dict),
                "ordering_policy_version": ord_ver_val,
                "scope_complete": scope_comp_val,
                "omission_count": omission_count,
                "omissions": [dict(omission) for omission in raw_omissions],
                "query_provenance": dict(envelope_dict.get("provenance", {})),
                "refusal_code": envelope_dict.get("refusal_code"),
                "unavailable_reason": envelope_dict.get("unavailable_reason"),
            }
        )
    else:
        raise ValueError("v2 slots require retained query envelope evidence")
    return out


__all__ = ["infer_slot_query_style", "upgrade_slot_to_v2"]
