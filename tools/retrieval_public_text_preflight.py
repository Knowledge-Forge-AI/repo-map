"""Frozen estimate and transition gates for public-text native admission (study sections 13 and 19).

Pure data validation: the old raw timing basis is frozen here, the estimate is
recomputed from actual request counts, and the source-bound functional
transition observation is validated. Nothing here observes a run, executes a
model, mutates a ledger or grants native authority; the private host still
establishes actual operator, source and receipt provenance.
"""

from __future__ import annotations

from typing import cast

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import re

PHASE = "REPOMAP-CLOE-PUBLIC-TEXT1"
PARTITIONS = ("v1.document", "ptx.document", "v1.query", "ptx.query")
DIMENSIONS = 384
MODEL_SECONDS = 550
MODEL_HEADROOM_SECONDS = 60
TRANSITION_SECONDS = 600
TRANSITION_HEADROOM_SECONDS = 120
MAX_G1_QUERIES = 4
RUNTIME_SHA256 = "sha256:80b6861e5732ac04988212b8601275dfb664f0363cb371bf59441fa34fcb69f8"
PAIRED_REPORT_SHA256 = "sha256:3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f"
ESTIMATE_SCHEMA = "cloe-public-text-estimate-gate-v1"
OBSERVATION_SCHEMA = "cloe-public-text-functional-transition-v1"
TRANSITION_SCHEMA = "cloe-public-text-transition-gate-v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTITY_FIELDS = ("q_source_closure_identity", "task_pins_identity", "selected_task_set_identity",
                    "artifact_profile_identity")


class PreflightRefusal(ValueError):
    """Closed refusal; never an inferred model result or a released allocation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TimingBasis:
    """One original raw native generation, frozen from its retained report."""

    generation: int
    records: int
    before_limit_tokens: int
    inference_seconds: float
    load_seconds: float
    raw_component_report_sha256: str


BASIS = {
    1: TimingBasis(1, 84, 4972, 21.906863506, 0.103777409,
                   "sha256:7a0cc613f9d2d1a2ba01ac4f1e517a306ab216a773fcbbd45982aff20757dedc"),
    2: TimingBasis(2, 80, 4861, 20.993532145, 0.100966081,
                   "sha256:4376c2ec254c854346d928b539d3609c3d4fdd1dfcaf3006f104dca0cdfd0efd"),
}


def _identity(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("ascii")).hexdigest()


def checked_counts(value: object, generation: object) -> dict[str, int]:
    """Exact non-bool partition counts; g1 has 1..4 admitted queries per arm, g2 none."""
    if type(generation) is not int or generation not in (1, 2):
        raise PreflightRefusal("preflight_generation")
    if not isinstance(value, Mapping) or set(value) != set(PARTITIONS):
        raise PreflightRefusal("preflight_count_fields")
    if any(type(value[name]) is not int or not 0 <= value[name] <= 500 for name in PARTITIONS):
        raise PreflightRefusal("preflight_count_type_or_bounds")
    counts = {name: value[name] for name in PARTITIONS}
    if not 1 <= sum(counts.values()) <= 500 or not 1 <= counts["ptx.document"] <= counts["v1.document"]:
        raise PreflightRefusal("preflight_document_floor_or_request_cap")
    if generation == 1:
        if not 1 <= counts["ptx.query"] <= counts["v1.query"] <= MAX_G1_QUERIES:
            raise PreflightRefusal("preflight_query_floor_or_fixed_candidate_cap")
    elif (counts["v1.query"], counts["ptx.query"]) != (0, 0):
        raise PreflightRefusal("preflight_generation_two_query_refused")
    return counts


def estimate_generation(generation: int, counts: Mapping[str, int], *,
                        runtime_sha256: str = RUNTIME_SHA256) -> dict[str, object]:
    """Recompute the disclosed conservative estimate and require ``E + 60 <= 550``.

    The retained runtime already pads to 512-token tensors; S is an additional
    conservative policy allowance, not measured tensor-width scaling or a
    runtime guarantee.
    """
    actual = checked_counts(counts, generation)
    if runtime_sha256 != RUNTIME_SHA256:
        raise PreflightRefusal("preflight_timing_runtime_changed")
    basis = BASIS[generation]
    t0 = basis.before_limit_tokens / basis.records
    u_meta = basis.inference_seconds / basis.records
    factor = 512 * (12 * DIMENSIONS + 1024) / (t0 * (12 * DIMENSIONS + 2 * t0))
    u_ptx = 2 * factor * u_meta
    estimate = (basis.load_seconds + (actual["v1.document"] + actual["v1.query"]) * u_meta
                + (actual["ptx.document"] + actual["ptx.query"]) * u_ptx)
    if not math.isfinite(estimate) or estimate + MODEL_HEADROOM_SECONDS > MODEL_SECONDS:
        raise PreflightRefusal("preflight_model_estimate_over_budget")
    result: dict[str, object] = {
        "schema": ESTIMATE_SCHEMA, "phase": PHASE, "generation": generation, "counts": actual,
        "runtime_sha256": RUNTIME_SHA256, "paired_report_sha256": PAIRED_REPORT_SHA256,
        "raw_component_report_sha256": basis.raw_component_report_sha256,
        "basis_records": basis.records, "basis_before_limit_tokens": basis.before_limit_tokens,
        "basis_inference_seconds": basis.inference_seconds, "basis_load_seconds": basis.load_seconds,
        "policy_factor": factor, "estimated_model_seconds": estimate,
        "headroom_seconds": MODEL_HEADROOM_SECONDS, "model_budget_seconds": MODEL_SECONDS,
        "disclosure": "conservative_policy_allowance_not_measured_tensor_width_scaling_or_runtime_guarantee",
    }
    return {**result, "estimate_gate_identity": _identity(result)}


def _identities(values: Mapping[str, object]) -> dict[str, str]:
    if set(values) != set(_IDENTITY_FIELDS):
        raise PreflightRefusal("preflight_transition_fields")
    result = {name: values[name] for name in _IDENTITY_FIELDS}
    if not all(type(value) is str and _DIGEST.fullmatch(value) for value in result.values()):
        raise PreflightRefusal("preflight_transition_identity")
    return cast(dict[str, str], result)


def _finite_interval(seconds: object) -> float:
    if type(seconds) not in (int, float) or not math.isfinite(cast(int | float, seconds)) or cast(int | float, seconds) < 0:
        raise PreflightRefusal("preflight_transition_interval")
    return float(cast(int | float, seconds))


def transition_observation(*, interval_seconds: float, counts: Mapping[str, Mapping[str, int]],
                           **identities: str) -> dict[str, object]:
    """Record what one genuine functional run observed; it is functional evidence only."""
    if not isinstance(counts, Mapping) or set(counts) != {"1", "2"}:
        raise PreflightRefusal("preflight_transition_count_generations")
    return {"schema": OBSERVATION_SCHEMA, "phase": PHASE, "functional_only": True,
            "counts": {key: checked_counts(counts[key], int(key)) for key in ("1", "2")},
            "interval_seconds": _finite_interval(interval_seconds), **_identities(identities)}


def check_transition_observation(observation: object, *, actual_counts: Mapping[str, Mapping[str, int]],
                                 **expected: str) -> dict[str, object]:
    """Require the same source/tasks/profile/counts and ``interval + 120 <= 600``.

    This validates data only; it establishes no authentic run, canonical
    result, source preservation, allocation, model origin or cleanup authority.
    """
    identities = _identities(expected)
    fields = frozenset({"schema", "phase", "functional_only", "counts", "interval_seconds", *_IDENTITY_FIELDS})
    if not isinstance(observation, Mapping) or set(observation) != fields:
        raise PreflightRefusal("preflight_transition_fields")
    if (observation["schema"], observation["phase"]) != (OBSERVATION_SCHEMA, PHASE) \
            or observation["functional_only"] is not True:
        raise PreflightRefusal("preflight_transition_mode")
    if any(observation[name] != value for name, value in identities.items()):
        raise PreflightRefusal("preflight_transition_source_or_task_changed")
    for candidate in (actual_counts, observation["counts"]):
        if not isinstance(candidate, Mapping) or set(candidate) != {"1", "2"}:
            raise PreflightRefusal("preflight_transition_count_generations")
    counts = {key: checked_counts(actual_counts[key], int(key)) for key in ("1", "2")}
    observed = {key: checked_counts(observation["counts"][key], int(key)) for key in ("1", "2")}
    if observed != counts:
        raise PreflightRefusal("preflight_transition_counts_changed")
    seconds = _finite_interval(observation["interval_seconds"])
    if seconds + TRANSITION_HEADROOM_SECONDS > TRANSITION_SECONDS:
        raise PreflightRefusal("preflight_transition_over_budget")
    result = {
        "schema": TRANSITION_SCHEMA, "phase": PHASE, **identities, "counts": counts,
        "functional_observation_identity": _identity(dict(observation)), "observed_interval_seconds": seconds,
        "headroom_seconds": TRANSITION_HEADROOM_SECONDS, "transition_budget_seconds": TRANSITION_SECONDS,
        "disclosure": "source_bound_functional_observation_not_model_timing_or_native_authority",
    }
    return {**result, "transition_gate_identity": _identity(result)}


__all__ = [
    "BASIS", "MAX_G1_QUERIES", "PARTITIONS", "PreflightRefusal", "TimingBasis", "check_transition_observation",
    "checked_counts", "estimate_generation", "transition_observation",
]
