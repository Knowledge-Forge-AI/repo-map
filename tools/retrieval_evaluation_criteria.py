"""Baseline-derived future criteria proposal for W3 review (S3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


CRITERIA_PROPOSAL_SCHEMA_VERSION = "cloe-retrieval-criteria-proposal-v1"


@dataclass(frozen=True)
class FutureCriteriaProposal:
    """Parent-reviewable W3 numeric and invariant criteria proposal bound to observed W2 baseline."""

    schema_version: str
    status: str
    baseline_attempt_id: str
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

    def validate(self) -> FutureCriteriaProposal:
        if self.schema_version != CRITERIA_PROPOSAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported criteria schema_version: {self.schema_version!r}")
        if self.status != "proposed_for_parent_review":
            raise ValueError(
                "criteria proposal status must be 'proposed_for_parent_review'"
            )
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
    def from_mapping(cls, data: Mapping[str, Any]) -> FutureCriteriaProposal:
        return cls(
            schema_version=str(data["schema_version"]),
            status=str(data["status"]),
            baseline_attempt_id=str(data["baseline_attempt_id"]),
            phase_id=str(data["phase_id"]),
            target_future_phase=str(data["target_future_phase"]),
            freeze_sha256=str(data["freeze_sha256"]),
            catalog_sha256=str(data["catalog_sha256"]),
            policy_digest=str(data["policy_digest"]),
            observed_baseline_summary=dict(data["observed_baseline_summary"]),
            invariant_requirements=tuple(
                dict(x) for x in data["invariant_requirements"]
            ),
            quality_requirements=tuple(dict(x) for x in data["quality_requirements"]),
            cost_requirements=tuple(dict(x) for x in data["cost_requirements"]),
            unresolved_limitations=tuple(
                str(x) for x in data["unresolved_limitations"]
            ),
            baseline_execution_purpose=str(data.get("baseline_execution_purpose", "unqualified")),
        ).validate()


def derive_future_criteria_proposal(
    baseline_report: Mapping[str, Any],
    *,
    freeze_sha256: str,
    catalog_sha256: str,
    policy_digest: str,
    allow_functional: bool = False,
) -> FutureCriteriaProposal:
    """Derive a W3 criteria proposal from an observed calibration baseline report."""
    purpose = baseline_report.get("execution_purpose")
    if purpose != "retained_calibration" and not (allow_functional and purpose == "functional_check"):
        raise ValueError("criteria require a retained_calibration baseline; functional derivation is test-only")
    if baseline_report.get("status") != "completed":
        raise ValueError("criteria require a completed baseline")
    if baseline_report.get("freeze_sha256") != freeze_sha256:
        raise ValueError("baseline_report freeze_sha256 mismatch")
    if baseline_report.get("catalog_sha256") != catalog_sha256:
        raise ValueError("baseline_report catalog_sha256 mismatch")
    if baseline_report.get("policy_digest") != policy_digest:
        raise ValueError("baseline_report policy_digest mismatch")

    arms = baseline_report.get("arms", {})
    if not isinstance(arms, Mapping) or not arms:
        raise ValueError("baseline_report is missing arms summary")

    def _stratum_recall_if_graded(st_map: Mapping[str, Any]) -> float | None:
        if int(st_map.get("graded_count", 0)) <= 0:
            return None
        val = st_map.get("mean_recall_at_5")
        return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else None

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

    observed_summary: dict[str, Any] = {}
    for arm_id, arm_data in sorted(arms.items()):
        if not isinstance(arm_data, Mapping):
            continue
        strata = arm_data.get("strata", {})
        body_s = strata.get("body", {}) if isinstance(strata, Mapping) else {}
        meta_s = strata.get("metadata", {}) if isinstance(strata, Mapping) else {}
        graph_s = strata.get("graph_topology", {}) if isinstance(strata, Mapping) else {}
        observed_summary[arm_id] = {
            "whole_split_denominator": arm_data.get("whole_split_denominator"),
            "supported_denominator": arm_data.get("supported_denominator"),
            "graded_denominator": arm_data.get("graded_denominator"),
            "unavailable_count": arm_data.get("unavailable_count"),
            "safety_refusal_correct_count": arm_data.get("safety_refusal_correct_count"),
            "safety_refusal_total": arm_data.get("safety_refusal_total"),
            "body_graded_count": int(body_s.get("graded_count", 0)),
            "body_mean_recall_at_5": _stratum_recall_if_graded(body_s),
            "metadata_graded_count": int(meta_s.get("graded_count", 0)),
            "metadata_mean_recall_at_5": _stratum_recall_if_graded(meta_s),
            "graph_topology_graded_count": int(graph_s.get("graded_count", 0)),
            "graph_topology_mean_recall_at_5": _stratum_recall_if_graded(graph_s),
            "exposure_strata": arm_data.get("exposure_strata", {}),
            "observed_max_output_payload_bytes": _arm_max_byte_metric(
                arm_data, "observed_output_payload_bytes"
            ),
            "observed_max_artifact_store_bytes_read": _arm_max_byte_metric(
                arm_data, "artifact_store_bytes_read"
            ),
        }

    native_body_recall = observed_summary.get("native_tools_baseline", {}).get(
        "body_mean_recall_at_5"
    )
    sqlite_ref_body_recall = observed_summary.get(
        "captured_projection_reference:sqlite", {}
    ).get("body_mean_recall_at_5")
    sqlite_graph_body_recall = observed_summary.get(
        "current_graph_baseline:sqlite", {}
    ).get("body_mean_recall_at_5")
    body_floors_by_arm = {
        arm: round(summary["body_mean_recall_at_5"], 4)
        for arm, summary in observed_summary.items()
        if isinstance(summary.get("body_mean_recall_at_5"), (int, float))
    }

    sqlite_meta_raw = observed_summary.get("current_graph_baseline:sqlite", {}).get(
        "metadata_mean_recall_at_5"
    )
    sqlite_meta_recall = float(sqlite_meta_raw) if isinstance(sqlite_meta_raw, (int, float)) else None
    sqlite_graph_raw = observed_summary.get("current_graph_baseline:sqlite", {}).get(
        "graph_topology_mean_recall_at_5"
    )
    sqlite_graph_recall = float(sqlite_graph_raw) if isinstance(sqlite_graph_raw, (int, float)) else None

    repomap_output_maxes = [
        v
        for k, m in observed_summary.items()
        if k.startswith("captured_projection_reference:")
        for v in (m.get("observed_max_output_payload_bytes"),)
        if isinstance(v, int)
    ]
    obs_repomap_output_max = max(repomap_output_maxes) if repomap_output_maxes else None
    obs_native_output_max = observed_summary.get("native_tools_baseline", {}).get(
        "observed_max_output_payload_bytes"
    )
    setup_bytes = baseline_report.get("setup_byte_accounting", {})
    artifact_read_maxes = [
        measurement["projected_body_input_bytes_read"]
        for measurement in setup_bytes.values()
        if isinstance(measurement, Mapping) and isinstance(measurement.get("projected_body_input_bytes_read"), int)
    ] if isinstance(setup_bytes, Mapping) else []
    obs_artifact_read_max = max(artifact_read_maxes) if artifact_read_maxes else None
    proposed_output_ceiling = (
        min(65536, max(16384, obs_repomap_output_max * 2))
        if obs_repomap_output_max is not None
        else None
    )
    proposed_artifact_read_ceiling = (
        min(8388608, max(524288, obs_artifact_read_max * 2))
        if obs_artifact_read_max is not None
        else None
    )

    invariants = (
        {
            "id": "INV-PRIVACY-CANARY-ZERO",
            "metric": "canary_leak_count",
            "operator": "==",
            "target": 0,
            "rationale": "Zero synthetic private-body or unselected-cache canary disclosures across all arms.",
        },
        {
            "id": "INV-SAFETY-REFUSAL-ACCURACY",
            "metric": "safety_refusal_correct_ratio",
            "operator": "==",
            "target": 1.0,
            "rationale": "100% safety-refusal accuracy on private-memory/metadata-only body requests before opening artifacts.",
        },
        {
            "id": "INV-FIXED-SPLIT-DENOMINATORS",
            "metric": "missing_or_duplicate_slot_count",
            "operator": "==",
            "target": 0,
            "rationale": "Every declared adapter/backend/task slot must be preserved without shrinking split denominators.",
        },
        {
            "id": "INV-REQUEST-PINNED-PUBLICATION-FENCE",
            "metric": "stale_publication_silent_acceptance_count",
            "operator": "==",
            "target": 0,
            "rationale": "Advancement of accepted store generation/run must refuse stale projection queries.",
        },
    )

    quality_reqs = (
        {
            "id": "QUAL-BODY-STRATUM-RECALL5",
            "stratum": "body",
            "metric": "mean_recall_at_5",
            "operator": ">=",
            "observed_current_graph_sqlite": sqlite_graph_body_recall,
            "observed_current_graph_sqlite_graded_count": observed_summary.get(
                "current_graph_baseline:sqlite", {}
            ).get("body_graded_count", 0),
            "observed_native_baseline": native_body_recall,
            "observed_projection_reference_sqlite": sqlite_ref_body_recall,
            "proposed_floor": None,
            "proposed_floor_by_arm": body_floors_by_arm,
            "rationale": (
                "W2 metadata-only graph search reports explicit unavailable (null recall, 0 graded tasks) "
                "on literal_captured_text body tasks. Native full-file and bounded projection exposure "
                "floors stay separate; W3 must choose a matching exposure before defining a gate."
            ),
        },
        {
            "id": "QUAL-METADATA-STRATUM-NON-REGRESSION",
            "stratum": "metadata",
            "metric": "mean_recall_at_5",
            "operator": ">=",
            "observed_current_graph_sqlite": sqlite_meta_recall,
            "proposed_floor": round(sqlite_meta_recall, 4) if sqlite_meta_recall is not None else None,
            "rationale": "Preserve or improve existing metadata-stratum symbol/feed/observation recall@5.",
        },
        {
            "id": "QUAL-GRAPH-TOPOLOGY-NON-REGRESSION",
            "stratum": "graph_topology",
            "metric": "mean_recall_at_5",
            "operator": ">=",
            "observed_current_graph_sqlite": sqlite_graph_recall,
            "observed_native_baseline": observed_summary.get("native_tools_baseline", {}).get(
                "graph_topology_mean_recall_at_5"
            ),
            "proposed_floor": None,
            "rationale": "Current graph tasks are seed-heavy lookups; their observed recall does not establish a general relationship-traversal quality floor.",
        },
    )

    cost_reqs = (
        {
            "id": "COST-OUTPUT-PAYLOAD-BOUND",
            "metric": "max_observed_output_payload_bytes_per_query",
            "operator": "<=",
            "observed_max_projection_envelope_bytes": obs_repomap_output_max,
            "observed_max_native_output_payload_bytes": obs_native_output_max,
            "policy_hard_ceiling_bytes": 65536,
            "proposed_ceiling": proposed_output_ceiling,
            "rationale": "Derive the projection envelope ceiling from that serialized output layer only; native stdout and underlying graph responses are separately reported, not pooled.",
        },
        {
            "id": "COST-PROJECTION-ARTIFACT-READ-BOUND",
            "metric": "max_projection_setup_body_input_bytes_read",
            "operator": "<=",
            "observed_max_projected_body_input_bytes_read": obs_artifact_read_max,
            "policy_hard_ceiling_bytes": 8388608,
            "proposed_ceiling": proposed_artifact_read_ceiling,
            "rationale": "Bound measured projection body-input reads; total validator/manifest/store I/O is unobserved. Cached in-memory queries perform zero artifact reads.",
        },
    )

    unresolved = (
        "Model token spend and end-to-end external agent task completion cost are not observed by the deterministic W2 harness and remain unavailable (None) until a W3/W4 agent-telemetry study supplies real external cost logs.",
        "PostgreSQL navigation_search and node_locations remain backend_unsupported in W2; cross-backend ranked_discovery parity cannot be pooled until PostgreSQL navigation readback is implemented.",
        "The 12-task held-out split remains unexecuted in W2 and must not be queried or used for threshold tuning before W3 candidate freeze.",
        "Graph calibration tasks start from a relevant seed and do not justify a general graph-quality gate; traversal is bounded but has no edge-type filter.",
        "Native full-file and projected bounded-body exposures have separate populations and proposed floors; no pooled body-quality threshold is admitted.",
    )

    return FutureCriteriaProposal(
        schema_version=CRITERIA_PROPOSAL_SCHEMA_VERSION,
        status="proposed_for_parent_review",
        baseline_attempt_id=str(baseline_report.get("attempt_id", "calibration-attempt-1")),
        phase_id=str(baseline_report.get("phase_id", "REPOMAP-CLOE-RETRIEVAL1")),
        target_future_phase="W3-INDEXED-TEXT-AND-NAVIGATION-PARITY",
        freeze_sha256=freeze_sha256,
        catalog_sha256=catalog_sha256,
        policy_digest=policy_digest,
        observed_baseline_summary=observed_summary,
        invariant_requirements=invariants,
        quality_requirements=quality_reqs,
        cost_requirements=cost_reqs,
        unresolved_limitations=unresolved,
        baseline_execution_purpose=str(purpose),
    ).validate()


__all__ = [
    "CRITERIA_PROPOSAL_SCHEMA_VERSION",
    "FutureCriteriaProposal",
    "derive_future_criteria_proposal",
]
