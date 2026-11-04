"""Callback gate for W5 baseline arms.

The baseline-capture runner is the common path for the FTS callback as well as
the ArmContext callbacks.  Keep this small adapter independent from semantic
experiment modules: it only turns a freshly recomputed admission decision into
the existing four-field evaluator outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import perf_counter_ns
from typing import TypeVar

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    MatchSurface,
    OmissionRecord,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryMode,
    QueryScope,
    refused_envelope,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_admission_w5 import (
    AdmissionState,
    AdmissionVerificationError,
    BindingDisposition,
    PublicationPin,
    W5AdmissionDecision,
    admit_w5_task,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask

P = TypeVar("P", bound=PublicationPin)
TaskOutcome = tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]


def _retain_admission_elapsed(error: BaseException, elapsed_ns: int) -> None:
    """Attach measured precheck work without masking the callback exception."""
    try:
        prior = getattr(error, "admission_elapsed_ns", 0)
    except Exception:
        prior = 0
    if type(prior) is not int or prior < 0:
        prior = 0
    total = prior + elapsed_ns
    for name in ("w5_admission_elapsed_ns", "admission_elapsed_ns"):
        try:
            setattr(error, name, total)
        except Exception:
            pass


def observed_backend_for_arm(arm_id: str) -> str:
    if arm_id == "native_tools_baseline":
        return "native_filesystem"
    if arm_id.startswith("captured_projection_reference:"):
        return "captured_reference"
    if arm_id.endswith(":sqlite"):
        return "sqlite"
    if arm_id.endswith(":postgresql"):
        return "postgresql"
    raise ValueError("unsupported evaluation arm")


def _failed_outcome(
    task: EvaluationTask, arm_id: str, reason: str, admission_elapsed_ns: int,
) -> TaskOutcome:
    mode = QueryMode(task.requested_mode)
    backend = observed_backend_for_arm(arm_id)
    envelope = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=mode,
        effective_mode=mode,
        match_surface=MatchSurface.NONE,
        scope=QueryScope(graph_id=task.graph_id, backend=backend),
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.FAILED,
        provenance={
            "adapter_id": arm_id,
            "failure_type": reason,
            "evaluator_precheck": True,
            "backend_policy_enforcement_observed": False,
            "admission_elapsed_ns": admission_elapsed_ns,
            "admission_elapsed_overlapping": True,
        },
    ).validate()
    return ExecutionState.FAILED, envelope, admission_elapsed_ns, ByteLayerAccounting()


def _blocked_outcome(
    task: EvaluationTask,
    arm_id: str,
    decision: W5AdmissionDecision,
    admission_elapsed_ns: int,
) -> TaskOutcome:
    identity = dict(decision.publication_identity or {})
    scope = QueryScope(
        graph_id=decision.graph_id,
        backend=decision.observed_backend,
        publication_bundle_id=identity.get("publication_bundle_id"),
        snapshot_manifest_id=identity.get("snapshot_manifest_id"),
        selected_binding_ids=decision.selected_binding_ids,
        source_path_prefix=task.source_path_prefix,
    ).validate()
    omissions = tuple(
        OmissionRecord(
            binding_id=item.binding_id,
            source_relative_path=None,
            reason_code=(
                item.reason_code
                or decision.reason_category
                or "w5_admission_refused"
            ),
            detail=f"evaluator precheck: {item.disposition.value}",
        ).validate()
        for item in decision.bindings
        if item.disposition is not BindingDisposition.ADMITTED_PUBLIC
    )
    provenance = {
        "adapter_id": arm_id,
        "evaluator_precheck": True,
        "admission_schema": "cloe-w5-admission-v1",
        "admission_state": decision.state.value,
        "admission_reason_category": decision.reason_category,
        "policy_enforcement_layer": decision.policy_enforcement_layer,
        "backend_policy_enforcement_observed": False,
        "selected_binding_ids": list(decision.selected_binding_ids),
        "admission_elapsed_ns": admission_elapsed_ns,
        "admission_elapsed_overlapping": True,
    }
    if decision.state is AdmissionState.REFUSED:
        envelope = refused_envelope(
            requested_mode=QueryMode(task.requested_mode),
            scope=scope,
            refusal_code=decision.refusal_code or "w5_admission_refused",
            omissions=omissions,
            provenance=provenance,
        )
        state = ExecutionState.REFUSED
    else:
        envelope = QueryEnvelope(
            contract_version=QUERY_CONTRACT_VERSION,
            requested_mode=QueryMode(task.requested_mode),
            effective_mode=QueryMode(task.requested_mode),
            match_surface=MatchSurface.NONE,
            scope=scope,
            ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
            capability_state=CapabilityState.UNAVAILABLE,
            omissions=omissions,
            unavailable_reason=decision.reason_category or "w5_admission_unavailable",
            provenance=provenance,
        ).validate()
        state = ExecutionState.UNAVAILABLE
    return state, envelope, admission_elapsed_ns, ByteLayerAccounting(observed_output_payload_bytes=0)


def execute_w5_callback(
    *,
    arm_id: str,
    task: EvaluationTask,
    publication_pin: P,
    policy: BodyProjectionPolicy,
    callback: Callable[[P], TaskOutcome],
    frozen_policy_digest: str | None = None,
    on_blocked: Callable[[W5AdmissionDecision, TaskOutcome], None] | None = None,
) -> TaskOutcome:
    """Admit against the live pin before allowing the arm callback to run."""
    started = perf_counter_ns()
    try:
        decision = admit_w5_task(
            task,
            policy=policy,
            publication_pin=publication_pin,
            observed_backend=observed_backend_for_arm(arm_id),
            frozen_policy_digest=frozen_policy_digest,
        )
    except AdmissionVerificationError as error:
        elapsed = max(0, perf_counter_ns() - started)
        return _failed_outcome(task, arm_id, error.code, elapsed)
    admission_elapsed = max(0, perf_counter_ns() - started)
    if not decision.execution_allowed:
        outcome = _blocked_outcome(task, arm_id, decision, admission_elapsed)
        if on_blocked is not None:
            try:
                on_blocked(decision, outcome)
            except BaseException as error:
                _retain_admission_elapsed(error, admission_elapsed)
                raise
        return outcome
    try:
        state, envelope, elapsed, accounting = callback(publication_pin)
    except BaseException as error:
        _retain_admission_elapsed(error, admission_elapsed)
        raise
    provenance = dict(envelope.provenance)
    prior_elapsed = provenance.get("admission_elapsed_ns", 0)
    if type(prior_elapsed) is not int or prior_elapsed < 0:
        prior_elapsed = 0
    provenance.update({
        "admission_elapsed_ns": prior_elapsed + admission_elapsed,
        "admission_elapsed_outer_ns": admission_elapsed,
        "admission_elapsed_overlapping": True,
    })
    return (
        state,
        replace(envelope, provenance=provenance).validate(),
        max(0, elapsed) + admission_elapsed,
        accounting,
    )


__all__ = ["TaskOutcome", "execute_w5_callback", "observed_backend_for_arm"]
