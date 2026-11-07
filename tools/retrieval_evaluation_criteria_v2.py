"""Source-bound future criteria proposal v2 preserving mode, fallback, surface, style, and exposure (Unit 3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from retrieval_evaluation_summary_v2 import BASELINE_REPORT_SCHEMA_V2

CRITERIA_PROPOSAL_SCHEMA_V2 = "cloe-retrieval-criteria-proposal-v2"


@dataclass(frozen=True)
class FutureCriteriaProposalV2:
    """Parent-reviewable v2 criteria proposal bound to a v2 baseline report."""

    schema_version: str
    status: str
    baseline_attempt_id: str
    baseline_schema_version: str
    phase_id: str
    target_future_phase: str
    freeze_sha256: str
    catalog_sha256: str
    policy_digest: str
    observed_baseline_summary: Mapping[str, Any]
    invariant_requirements: tuple[Mapping[str, Any], ...]
    quality_requirements: tuple[Mapping[str, Any], ...]
    cost_requirements: tuple[Mapping[str, Any], ...]
    unresolved_limitations: tuple[str, ...]
    baseline_execution_purpose: str = "retained_calibration"

    def validate(self) -> FutureCriteriaProposalV2:
        if self.schema_version != CRITERIA_PROPOSAL_SCHEMA_V2:
            raise ValueError(f"unsupported v2 criteria schema_version: {self.schema_version!r}")
        if self.baseline_schema_version != BASELINE_REPORT_SCHEMA_V2:
            raise ValueError(
                f"v2 criteria require {BASELINE_REPORT_SCHEMA_V2!r}, got {self.baseline_schema_version!r}"
            )
        if self.status != "proposed_for_parent_review":
            raise ValueError("criteria proposal status must be 'proposed_for_parent_review'")
        for label, digest in (
            ("freeze_sha256", self.freeze_sha256),
            ("catalog_sha256", self.catalog_sha256),
            ("policy_digest", self.policy_digest),
        ):
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise ValueError(f"{label} must be a sha256: digest")
        if len(self.invariant_requirements) < 4:
            raise ValueError("invariant_requirements must declare at least 4 invariants")
        if len(self.quality_requirements) < 3:
            raise ValueError("quality_requirements must declare at least 3 requirements")
        if len(self.cost_requirements) < 2:
            raise ValueError("cost_requirements must declare at least 2 requirements")
        if len(self.unresolved_limitations) < 2:
            raise ValueError("unresolved_limitations must record at least 2 limitations")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "baseline_attempt_id": self.baseline_attempt_id,
            "baseline_schema_version": self.baseline_schema_version,
            "phase_id": self.phase_id,
            "target_future_phase": self.target_future_phase,
            "freeze_sha256": self.freeze_sha256,
            "catalog_sha256": self.catalog_sha256,
            "policy_digest": self.policy_digest,
            "observed_baseline_summary": dict(self.observed_baseline_summary),
            "invariant_requirements": [dict(r) for r in self.invariant_requirements],
            "quality_requirements": [dict(r) for r in self.quality_requirements],
            "cost_requirements": [dict(r) for r in self.cost_requirements],
            "unresolved_limitations": list(self.unresolved_limitations),
            "baseline_execution_purpose": self.baseline_execution_purpose,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FutureCriteriaProposalV2:
        return cls(
            schema_version=str(data["schema_version"]),
            status=str(data["status"]),
            baseline_attempt_id=str(data["baseline_attempt_id"]),
            baseline_schema_version=str(data["baseline_schema_version"]),
            phase_id=str(data["phase_id"]),
            target_future_phase=str(data["target_future_phase"]),
            freeze_sha256=str(data["freeze_sha256"]),
            catalog_sha256=str(data["catalog_sha256"]),
            policy_digest=str(data["policy_digest"]),
            observed_baseline_summary=dict(data["observed_baseline_summary"]),
            invariant_requirements=tuple(dict(x) for x in data["invariant_requirements"]),
            quality_requirements=tuple(dict(x) for x in data["quality_requirements"]),
            cost_requirements=tuple(dict(x) for x in data["cost_requirements"]),
            unresolved_limitations=tuple(str(x) for x in data["unresolved_limitations"]),
            baseline_execution_purpose=str(
                data.get("baseline_execution_purpose", "unqualified")
            ),
        ).validate()


def _arm_max_byte_metric(arm_map: Mapping[str, Any], key: str) -> int | None:
    slots = arm_map.get("slots")
    if not isinstance(slots, (list, tuple)):
        return None
    vals: list[int] = []
    for s in slots:
        if not isinstance(s, Mapping):
            continue
        ba = s.get("byte_accounting")
        if isinstance(ba, Mapping):
            v = ba.get(key)
            if isinstance(v, int) and not isinstance(v, bool):
                vals.append(v)
    return max(vals) if vals else None


def derive_future_criteria_proposal_v2(
    baseline_report: Mapping[str, Any],
    *,
    freeze_sha256: str,
    catalog_sha256: str,
    policy_digest: str,
    allow_functional: bool = False,
) -> FutureCriteriaProposalV2:
    """Derive a source-bound v2 criteria proposal without pooling across modes, fallbacks, or surfaces."""
    if baseline_report.get("schema_version") != BASELINE_REPORT_SCHEMA_V2:
        raise ValueError(
            f"derive_future_criteria_proposal_v2 requires {BASELINE_REPORT_SCHEMA_V2!r}"
        )
    purpose = baseline_report.get("execution_purpose")
    if purpose not in {"retained_calibration", "historical_journal_reprojection"} and not (
        allow_functional and purpose == "functional_check"
    ):
        raise ValueError(
            "v2 criteria require a retained_calibration or historical_journal_reprojection baseline; functional derivation is test-only"
        )
    if baseline_report.get("status") != "completed":
        raise ValueError("v2 criteria require a completed baseline")
    if baseline_report.get("freeze_sha256") != freeze_sha256:
        raise ValueError("baseline_report freeze_sha256 mismatch")
    if baseline_report.get("catalog_sha256") != catalog_sha256:
        raise ValueError("baseline_report catalog_sha256 mismatch")
    if baseline_report.get("policy_digest") != policy_digest:
        raise ValueError("baseline_report policy_digest mismatch")

    arms = baseline_report.get("arms", {})
    if not isinstance(arms, Mapping) or not arms:
        raise ValueError("baseline_report is missing arms summary")

    observed_summary: dict[str, Any] = {}
    quality_reqs_list: list[dict[str, Any]] = []
    cost_reqs_list: list[dict[str, Any]] = []

    for arm_id, arm_data in sorted(arms.items()):
        if not isinstance(arm_data, Mapping):
            continue
        backend = str(arm_data.get("backend") or "")
        output_layer = str(arm_data.get("observed_output_layer") or "unknown")
        mss_strata = arm_data.get("mode_surface_style_strata")
        if not isinstance(mss_strata, (list, tuple)) or not mss_strata:
            raise ValueError(f"arm {arm_id!r} is missing v2 mode_surface_style_strata")

        max_out_bytes = _arm_max_byte_metric(arm_data, "observed_output_payload_bytes")
        max_art_bytes = _arm_max_byte_metric(arm_data, "artifact_store_bytes_read")
        observed_summary[arm_id] = {
            "arm_id": arm_id,
            "backend": backend,
            "observed_output_layer": output_layer,
            "whole_split_denominator": arm_data.get("whole_split_denominator"),
            "supported_denominator": arm_data.get("supported_denominator"),
            "graded_denominator": arm_data.get("graded_denominator"),
            "unavailable_count": arm_data.get("unavailable_count"),
            "refused_count": arm_data.get("refused_count"),
            "failed_count": arm_data.get("failed_count"),
            "safety_refusal_correct_count": arm_data.get("safety_refusal_correct_count"),
            "safety_refusal_total": arm_data.get("safety_refusal_total"),
            "absent_answer_correct_count": arm_data.get("absent_answer_correct_count"),
            "absent_answer_total": arm_data.get("absent_answer_total"),
            "mode_surface_style_strata": [dict(entry) for entry in mss_strata],
            "observed_max_output_payload_bytes": max_out_bytes,
            "observed_max_artifact_store_bytes_read": max_art_bytes,
        }

        for idx, entry in enumerate(mss_strata, start=1):
            if not isinstance(entry, Mapping):
                continue
            graded_count = int(entry.get("graded_count", 0))
            raw_rec = entry.get("mean_recall_at_5")
            obs_rec = (
                float(raw_rec)
                if graded_count > 0
                and isinstance(raw_rec, (int, float))
                and not isinstance(raw_rec, bool)
                else None
            )
            fb = dict(entry["fallback"]) if isinstance(entry.get("fallback"), Mapping) else None
            stratum = str(entry["comparability_stratum"])
            is_graph_topo = stratum == "graph_topology"
            proposed_floor = (
                round(obs_rec, 4)
                if (obs_rec is not None and not is_graph_topo)
                else None
            )
            quality_reqs_list.append(
                {
                    "id": f"QUAL-V2-{arm_id.upper().replace(':', '-')}-{idx:02d}",
                    "arm_id": arm_id,
                    "backend": backend,
                    "comparability_stratum": stratum,
                    "comparator_exposure": str(entry["comparator_exposure"]),
                    "requested_mode": str(entry["requested_mode"]),
                    "effective_mode": str(entry["effective_mode"]),
                    "fallback": fb,
                    "match_surface": str(entry["match_surface"]),
                    "query_style": str(entry["query_style"]),
                    "metric": "mean_recall_at_5",
                    "operator": ">=",
                    "slot_count": int(entry.get("slot_count", 0)),
                    "graded_count": graded_count,
                    "observed_mean_recall_at_5": obs_rec,
                    "observed_mean_mrr_at_5": entry.get("mean_mrr_at_5"),
                    "observed_mean_ndcg_at_5": entry.get("mean_ndcg_at_5"),
                    "proposed_floor": proposed_floor,
                    "task_ids": list(entry.get("task_ids", ())),
                    "rationale": (
                        "Graph topology seed-heavy tasks do not establish a general traversal floor."
                        if is_graph_topo
                        else (
                            "Unaggraded/unavailable or refusal-only cell; no recall floor applies."
                            if obs_rec is None
                            else "Source-bound cell floor preserving exact mode, fallback, surface, style, backend, and exposure."
                        )
                    ),
                }
            )

        proposed_out_ceiling = (
            min(65536, max(16384, max_out_bytes * 2))
            if max_out_bytes is not None
            else None
        )
        cost_reqs_list.append(
            {
                "id": f"COST-OUTPUT-V2-{arm_id.upper().replace(':', '-')}",
                "arm_id": arm_id,
                "backend": backend,
                "observed_output_layer": output_layer,
                "metric": "max_observed_output_payload_bytes_per_query",
                "operator": "<=",
                "observed_max_output_payload_bytes": max_out_bytes,
                "policy_hard_ceiling_bytes": 65536,
                "proposed_ceiling": proposed_out_ceiling,
                "rationale": "Per-arm serialized output ceiling bound to this arm's exact output layer and backend.",
            }
        )

    setup_bytes = baseline_report.get("setup_byte_accounting", {})
    artifact_read_maxes = (
        [
            m["projected_body_input_bytes_read"]
            for m in setup_bytes.values()
            if isinstance(m, Mapping)
            and isinstance(m.get("projected_body_input_bytes_read"), int)
        ]
        if isinstance(setup_bytes, Mapping)
        else []
    )
    obs_art_max = max(artifact_read_maxes) if artifact_read_maxes else None
    cost_reqs_list.append(
        {
            "id": "COST-PROJECTION-SETUP-BODY-INPUT-BYTES-V2",
            "arm_id": "all_body_projection_and_lexical_arms",
            "backend": "sqlite_and_postgresql",
            "observed_output_layer": "setup_body_input_read",
            "metric": "max_projection_setup_body_input_bytes_read",
            "operator": "<=",
            "observed_max_projected_body_input_bytes_read": obs_art_max,
            "policy_hard_ceiling_bytes": 8388608,
            "proposed_ceiling": (
                min(8388608, max(524288, obs_art_max * 2))
                if obs_art_max is not None
                else None
            ),
            "rationale": "Bound setup body-input bytes read across projection and lexical build.",
        }
    )

    invariants = (
        {"id": "INV-PRIVACY-CANARY-ZERO", "metric": "canary_leak_count", "operator": "==", "target": 0, "rationale": "Zero synthetic private-body or unselected-cache canary disclosures across all arms."},
        {"id": "INV-SAFETY-REFUSAL-ACCURACY", "metric": "safety_refusal_correct_ratio", "operator": "==", "target": 1.0, "rationale": "100% safety-refusal accuracy on private-memory/metadata-only body requests."},
        {"id": "INV-FIXED-SPLIT-DENOMINATORS", "metric": "missing_or_duplicate_slot_count", "operator": "==", "target": 0, "rationale": "Every declared adapter/backend/task slot must be preserved without shrinking split denominators."},
        {"id": "INV-REQUEST-PINNED-PUBLICATION-FENCE", "metric": "stale_publication_silent_acceptance_count", "operator": "==", "target": 0, "rationale": "Advancement of accepted store generation/run must refuse stale projection or lexical queries."},
        {"id": "INV-NO-MODE-OR-SURFACE-POOLING", "metric": "pooled_cross_mode_or_cross_surface_criteria_count", "operator": "==", "target": 0, "rationale": "Every quality requirement binds to an exact (arm, backend, stratum, exposure, requested_mode, effective_mode, fallback, match_surface, query_style) cell."},
    )

    unresolved = (
        "Model token spend and end-to-end external agent task completion cost are not observed by the deterministic harness and remain None until an external agent-telemetry study supplies real logs.",
        "The 12-task held-out split remains unexecuted during calibration and requires a parent-accepted criteria artifact, frozen candidate closure digests, and an explicit parent authorization token before execution.",
        "Graph calibration tasks start from a relevant seed and do not justify a general relationship-traversal quality floor.",
        "Fallback-bearing cells (e.g. ranked_discovery -> literal_captured_text) remain strictly separated from native-mode cells (e.g. ranked_discovery -> ranked_discovery).",
    )

    return FutureCriteriaProposalV2(
        schema_version=CRITERIA_PROPOSAL_SCHEMA_V2,
        status="proposed_for_parent_review",
        baseline_attempt_id=str(baseline_report.get("attempt_id", "calibration-attempt-1")),
        baseline_schema_version=BASELINE_REPORT_SCHEMA_V2,
        phase_id=str(baseline_report.get("phase_id", "REPOMAP-CLOE-LEXICAL1")),
        target_future_phase="W3-CALIBRATION-AND-HELD-OUT-GATE",
        freeze_sha256=freeze_sha256,
        catalog_sha256=catalog_sha256,
        policy_digest=policy_digest,
        observed_baseline_summary=observed_summary,
        invariant_requirements=invariants,
        quality_requirements=tuple(quality_reqs_list),
        cost_requirements=tuple(cost_reqs_list),
        unresolved_limitations=unresolved,
        baseline_execution_purpose=str(purpose),
    ).validate()


__all__ = [
    "CRITERIA_PROPOSAL_SCHEMA_V2",
    "FutureCriteriaProposalV2",
    "derive_future_criteria_proposal_v2",
]
