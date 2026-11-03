"""Strict evaluator-only baseline correspondence verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import (
    CorrespondenceRefusal,
    ProjectionInputs,
    check_correspondence,
)
from common_lore_index.retrieval.query_contracts import CapabilityState, MatchSurface, QueryEnvelope
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_views import (
    MaterializedNativeView,
    NativeMaterializationWitness,
    verify_native_materialization_witness,
)
from retrieval_semantic_baseline_capture import (
    IssuedBaselineCapture, _VERIFICATION_TOKEN, _record_verified_sidecar,
)
from retrieval_semantic_arm_validation import _pins_match, _verify_envelope_against_pin
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_representation import RepresentationValidationError
from retrieval_semantic_baseline_work import (
    CorrespondenceVerificationFailure, _CostClock, _MeteredArtifactStore,
)
def _accepted_matches_pin(accepted: Any, pin: VerifiedPublicationPin) -> bool:
    return (
        accepted.graph_id == pin.graph_id
        and accepted.repository_id == pin.repository_identity
        and accepted.backend == pin.backend
        and str(accepted.run_id) == str(pin.run_id)
        and accepted.publication_bundle_id == pin.publication_bundle_id
        and accepted.job_id == str(pin.receipt.attempt.job_id)
        and accepted.attempt == pin.receipt.attempt.attempt
        and type(accepted.accepted_generation) is int
        and accepted.accepted_generation == pin.generation
        and accepted.snapshot_manifest_id == pin.snapshot_manifest_id
        and accepted.extraction_receipt_id == pin.extraction_receipt_id
    )
def _verify_actual_inputs(
    inputs: Any,
    policy: Any,
    pin: VerifiedPublicationPin,
    clock: _CostClock,
) -> Any:
    if not isinstance(inputs, ProjectionInputs) or not isinstance(policy, BodyProjectionPolicy):
        raise ExperimentRefusal("projection_inputs_incomplete")
    try:
        policy.validate()
        if policy.graph_id != pin.graph_id or policy.policy_digest() != pin.policy_digest:
            raise ExperimentRefusal("projection_policy_mismatch")
        if set(policy.selected_binding_ids) != set(pin.admitted_public_bindings):
            raise ExperimentRefusal("projection_binding_policy_mismatch")
        metered = replace(inputs, store=_MeteredArtifactStore(inputs.store, clock))
        checked = check_correspondence(metered)
    except CorrespondenceRefusal as exc:
        raise ExperimentRefusal(exc.code.value) from exc
    except ExperimentRefusal:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ExperimentRefusal("projection_correspondence_failed") from exc
    if not _accepted_matches_pin(checked, pin):
        raise ExperimentRefusal("projection_pin_mismatch")
    return inputs

def _verify_envelope_scope(
    envelope: QueryEnvelope,
    task: EvaluationTask,
    pin: VerifiedPublicationPin,
    *,
    arm_backend: str,
    select_bindings: Callable[[EvaluationTask], tuple[str, ...]],
) -> None:
    try:
        envelope.validate()
    except Exception as exc:
        raise ExperimentRefusal("invalid_query_envelope") from exc
    scope = envelope.scope
    selected = select_bindings(task)
    if scope.graph_id != task.graph_id:
        raise ExperimentRefusal("envelope_graph_id_mismatch")
    if scope.backend != arm_backend:
        raise ExperimentRefusal("envelope_observed_backend_mismatch")
    if len(scope.selected_binding_ids) != len(set(scope.selected_binding_ids)) or set(scope.selected_binding_ids) != set(selected):
        raise ExperimentRefusal("baseline_envelope_scope_mismatch")
    if scope.source_path_prefix != task.source_path_prefix:
        raise ExperimentRefusal("envelope_source_scope_mismatch")
    if scope.publication_bundle_id is not None and scope.publication_bundle_id != pin.publication_bundle_id:
        raise ExperimentRefusal("envelope_publication_bundle_mismatch")
    if scope.snapshot_manifest_id is not None and scope.snapshot_manifest_id != pin.snapshot_manifest_id:
        raise ExperimentRefusal("envelope_snapshot_manifest_mismatch")
    for hit in envelope.hits:
        loc = hit.locator
        if loc.binding_id not in selected:
            raise ExperimentRefusal("envelope_hit_binding_scope_mismatch")
        if task.source_path_prefix is not None and not loc.source_relative_path.startswith(task.source_path_prefix):
            raise ExperimentRefusal("envelope_hit_path_scope_mismatch")
    provenance = envelope.provenance
    if not isinstance(provenance, Mapping):
        raise ExperimentRefusal("invalid_query_envelope")
    for key, expected, code in (
        ("graph_id", pin.graph_id, "envelope_graph_id_mismatch"),
        ("generation", pin.generation, "envelope_generation_mismatch"),
        ("publication_bundle_id", pin.publication_bundle_id, "envelope_publication_bundle_mismatch"),
        ("snapshot_manifest_id", pin.snapshot_manifest_id, "envelope_snapshot_manifest_mismatch"),
        ("extraction_receipt_id", pin.extraction_receipt_id, "envelope_extraction_receipt_mismatch"),
        ("graph_candidate_id", pin.graph_candidate_id, "envelope_candidate_mismatch"),
        ("repository_identity", pin.repository_identity, "envelope_repository_identity_mismatch"),
    ):
        if key in provenance and (type(provenance[key]) is not type(expected) or provenance[key] != expected):
            raise ExperimentRefusal(code)
    run_ids = []
    for key in ("accepted_run_id", "run_id"):
        if key not in provenance:
            continue
        value = provenance[key]
        if type(value) is not int or value < 1:
            raise ExperimentRefusal("envelope_run_id_invalid")
        run_ids.append(value)
    if run_ids and (len(set(run_ids)) != 1 or run_ids[0] != pin.run_id):
        raise ExperimentRefusal("envelope_run_id_mismatch")

def _verify_issued_capture(
    sidecar: Any,
    *,
    task: EvaluationTask,
    arm_id: str,
    envelope: QueryEnvelope,
    target_pin: VerifiedPublicationPin,
    target_backend: str,
    clock: _CostClock,
) -> IssuedBaselineCapture:
    """Require the sidecar to carry the factory-issued capture for this call."""
    capture = getattr(sidecar, "capture", None)
    if not isinstance(capture, IssuedBaselineCapture):
        raise ExperimentRefusal("baseline_capture_required")
    capture.validate()
    if capture.arm_id != arm_id or capture.task_id != task.task_id:
        raise ExperimentRefusal("baseline_capture_identity_mismatch")
    if capture.envelope_digest != digest_json(envelope.to_dict()):
        raise ExperimentRefusal("baseline_capture_envelope_mismatch")
    try:
        generation_aliases = tuple(sidecar.generation_aliases)
        pre_pin = capture.pre.target_for_arm(arm_id)
        post_pin = capture.post.target_for_arm(arm_id)
    except (AttributeError, TypeError, ExperimentRefusal) as exc:
        raise ExperimentRefusal("baseline_capture_binding_invalid") from exc
    if generation_aliases != capture.generation_aliases:
        raise ExperimentRefusal("baseline_capture_alias_scope_mismatch")
    if capture.read_attempts != 4:
        raise ExperimentRefusal("baseline_capture_reads_incomplete")
    if (
        sidecar.sqlite_pin is not capture.pre.sqlite
        or sidecar.postgres_pin is not capture.pre.postgres
        or sidecar.pre_query_pin is not pre_pin
        or sidecar.post_query_pin is not post_pin
        or target_pin is not pre_pin
        or pre_pin.backend != target_backend
        or post_pin.backend != target_backend
    ):
        raise ExperimentRefusal("baseline_capture_pin_binding_mismatch")
    if pre_pin is post_pin:
        raise ExperimentRefusal("baseline_capture_pre_post_not_independent")
    clock.include_capture(capture)
    return capture

def _verify_native_scope(
    sidecar: Any,
    task: EvaluationTask,
    state: ExecutionState,
    envelope: QueryEnvelope,
    pin: VerifiedPublicationPin,
    clock: _CostClock,
    *,
    select_bindings: Callable[[EvaluationTask], tuple[str, ...]],
) -> None:
    witness = sidecar.native_witness
    view = sidecar.native_view
    if not isinstance(witness, NativeMaterializationWitness):
        raise ExperimentRefusal("native_materialization_witness_required")
    if not isinstance(view, MaterializedNativeView):
        raise ExperimentRefusal("native_materialization_view_required")
    inputs = sidecar.projection_inputs
    _verify_actual_inputs(inputs, sidecar.projection_policy, pin, clock)
    aliases = tuple(sidecar.generation_aliases)
    manifest_aliases = tuple(binding.alias for binding in inputs.manifest.bindings)
    if (
        not aliases
        or len(aliases) != len(set(aliases))
        or tuple(sorted(aliases)) != tuple(sorted(manifest_aliases))
    ):
        raise ExperimentRefusal("native_generation_alias_scope_mismatch")
    try:
        expected, verified_bytes, _ = verify_native_materialization_witness(
            view,
            witness,
            manifest=inputs.manifest,
            bundle=inputs.bundle,
            store=_MeteredArtifactStore(inputs.store, clock),
            policy=sidecar.projection_policy,
            selected_aliases=aliases,
            include_extracted_metadata_for_non_body=witness.include_extracted_metadata_for_non_body,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ExperimentRefusal("native_materialization_witness_invalid") from exc
    clock.known_materialized_bytes += verified_bytes
    if (
        expected.graph_id != pin.graph_id
        or expected.publication_bundle_id != pin.publication_bundle_id
        or expected.snapshot_manifest_id != pin.snapshot_manifest_id
        or expected.graph_candidate_id != pin.graph_candidate_id
        or expected.policy_digest != pin.policy_digest
        or expected.snapshot_vector != pin.snapshot_vector
        or any(expected.excluded_bindings.get(b) != r for b, r in pin.denied_bindings.items()
               if b in {binding.binding_id for binding in inputs.manifest.bindings})
        or any(f.binding_id not in pin.admitted_public_bindings or f.binding_id in pin.denied_bindings for f in expected.files)
    ):
        raise ExperimentRefusal("native_witness_pin_mismatch")
    if set(expected.selected_aliases) != set(aliases):
        raise ExperimentRefusal("native_witness_alias_scope_mismatch")
    global_ids = {binding.binding_id for binding in inputs.manifest.bindings if binding.alias in aliases}
    classified_ids = set(pin.admitted_public_bindings) | set(pin.denied_bindings)
    if global_ids - classified_ids or not set(pin.admitted_public_bindings).issubset(global_ids):
        raise ExperimentRefusal("native_global_binding_scope_mismatch")
    if any(file.binding_id in pin.denied_bindings for file in expected.files):
        raise ExperimentRefusal("native_denied_binding_exposed")
    expected_surfaces = {file.view_relative_path: MatchSurface(file.match_surface) for file in expected.files}
    if dict(view.path_to_surface) != expected_surfaces:
        raise ExperimentRefusal("native_path_surface_mapping_mismatch")
    paths_by_identity: dict[tuple[str, str], str] = {}
    for view_path, identity in view.path_to_binding.items():
        if identity in paths_by_identity:
            raise ExperimentRefusal("native_path_binding_mapping_ambiguous")
        paths_by_identity[identity] = view_path
    expected_identities = {(file.binding_id, file.source_relative_path) for file in expected.files}
    if set(paths_by_identity) != expected_identities:
        raise ExperimentRefusal("native_path_binding_mapping_mismatch")
    if state == ExecutionState.COMPLETED and task.grading_rule != "direct_handoff":
        for hit in envelope.hits:
            identity = (hit.locator.binding_id, hit.locator.source_relative_path)
            hit_view_path = paths_by_identity.get(identity)
            if hit_view_path is None:
                raise ExperimentRefusal("native_hit_unwitnessed_file")
            if view.path_to_surface.get(hit_view_path) != hit.match_surface:
                raise ExperimentRefusal("native_hit_surface_mismatch")
def _verify_projection_scope(
    sidecar: Any,
    pin: VerifiedPublicationPin,
    clock: _CostClock,
) -> None:
    projection = sidecar.projection
    if not isinstance(projection, CapturedTextProjection):
        raise ExperimentRefusal("projection_reference_required")
    inputs = sidecar.projection_inputs
    _verify_actual_inputs(inputs, sidecar.projection_policy, pin, clock)
    if (
        projection.accepted_reference != inputs.accepted_reference
        or projection.publication_bundle_id != pin.publication_bundle_id
        or projection.snapshot_manifest_id != pin.snapshot_manifest_id
        or projection.extraction_receipt_id != pin.extraction_receipt_id
        or projection.candidate_id != pin.graph_candidate_id
        or projection.policy_digest != pin.policy_digest
    ):
        raise ExperimentRefusal("projection_pin_mismatch")
def _verify_cross_store_pin_scope(sidecar: Any, task: EvaluationTask) -> None:
    sqlite_pin = sidecar.sqlite_pin
    postgres_pin = sidecar.postgres_pin
    if sqlite_pin is None or postgres_pin is None:
        return
    if sqlite_pin.backend != "sqlite" or postgres_pin.backend != "postgresql":
        raise ExperimentRefusal("cross_store_pin_backend_mismatch")
    if (
        sqlite_pin.graph_id != task.graph_id
        or postgres_pin.graph_id != task.graph_id
        or sqlite_pin.generation != task.generation
        or postgres_pin.generation != task.generation
    ):
        raise ExperimentRefusal("cross_store_publication_mismatch")
    if sqlite_pin.snapshot_vector != postgres_pin.snapshot_vector:
        raise ExperimentRefusal("cross_store_snapshot_vector_mismatch")
    if (
        sqlite_pin.admitted_public_bindings != postgres_pin.admitted_public_bindings
        or dict(sqlite_pin.denied_bindings) != dict(postgres_pin.denied_bindings)
        or sqlite_pin.policy_digest != postgres_pin.policy_digest
    ):
        raise ExperimentRefusal("cross_store_binding_policy_mismatch")


def _revalidate_query_pins(
    sidecar: Any,
    task: EvaluationTask,
    target_pin: VerifiedPublicationPin,
    target_backend: str,
) -> VerifiedPublicationPin:
    pre_pin, post_pin = sidecar.pre_query_pin, sidecar.post_query_pin
    if not isinstance(pre_pin, VerifiedPublicationPin) or not isinstance(post_pin, VerifiedPublicationPin):
        raise ExperimentRefusal("baseline_pre_post_pins_required")
    if pre_pin is post_pin:
        raise ExperimentRefusal("baseline_pre_post_pins_not_independent")
    if pre_pin.backend != target_backend or post_pin.backend != target_backend:
        raise ExperimentRefusal("baseline_pre_post_backend_mismatch")
    revalidated = target_pin.revalidate_current()
    if revalidated.graph_id != task.graph_id or revalidated.generation != task.generation:
        raise ExperimentRefusal("pin_task_mismatch")
    if _pins_match(pre_pin, revalidated) is not None:
        raise ExperimentRefusal("pre_query_pin_mismatch")
    if _pins_match(post_pin, revalidated) is not None:
        raise ExperimentRefusal("post_query_pin_mismatch")
    if sidecar.capture.pre.sqlite is sidecar.capture.post.sqlite or sidecar.capture.pre.postgres is sidecar.capture.post.postgres:
        raise ExperimentRefusal("baseline_capture_pre_post_not_independent")
    non_target_pre = sidecar.capture.pre.postgres if target_backend == "sqlite" else sidecar.capture.pre.sqlite
    non_target_post = sidecar.capture.post.postgres if target_backend == "sqlite" else sidecar.capture.post.sqlite
    if _pins_match(non_target_pre, non_target_post) is not None:
        raise ExperimentRefusal("baseline_non_target_post_pin_mismatch")
    return revalidated


def verify_strict_baseline_correspondence_sidecar(
    sidecar: Any,
    *,
    task: EvaluationTask,
    arm_id: str,
    state: ExecutionState,
    envelope: QueryEnvelope,
    sidecar_type: type[Any],
    schema_version: str,
    observed_backends: Mapping[str, str],
    target_backends: Mapping[str, str],
    select_bindings: Callable[[EvaluationTask], tuple[str, ...]],
    cost_type: Callable[..., Any],
) -> tuple[VerifiedPublicationPin, Any]:
    """Verify complete artifact/native/projection correspondence and preserve refusal cost."""
    clock = _CostClock()
    try:
        if not isinstance(sidecar, sidecar_type):
            raise ExperimentRefusal("baseline_correspondence_sidecar_required")
        if sidecar.schema != schema_version:
            raise ExperimentRefusal("invalid_correspondence_sidecar_schema")
        if sidecar.arm_id != arm_id or sidecar.task_id != task.task_id:
            raise ExperimentRefusal("correspondence_sidecar_identity_mismatch")
        if arm_id not in target_backends:
            raise ExperimentRefusal("unsupported_baseline_correspondence_arm")
        if sidecar.caller_mapping_identity is not None:
            raise ExperimentRefusal("caller_mapping_not_admitted_for_identity")
        target_backend = target_backends[arm_id]
        target_pin = sidecar.sqlite_pin if target_backend == "sqlite" else sidecar.postgres_pin
        if not isinstance(target_pin, VerifiedPublicationPin) or target_pin.backend != target_backend:
            raise ExperimentRefusal(f"{target_backend}_pin_required_for_arm")
        _verify_issued_capture(
            sidecar,
            task=task,
            arm_id=arm_id,
            envelope=envelope,
            target_pin=target_pin,
            target_backend=target_backend,
            clock=clock,
        )
        _verify_cross_store_pin_scope(sidecar, task)
        revalidated = _revalidate_query_pins(
            sidecar, task, target_pin, target_backend
        )
        if state != ExecutionState.COMPLETED or envelope.capability_state not in {CapabilityState.AVAILABLE, CapabilityState.PARTIAL}:
            raise ExperimentRefusal("baseline_execution_not_creditable")
        _verify_envelope_scope(
            envelope, task, revalidated, arm_backend=observed_backends[arm_id], select_bindings=select_bindings
        )
        if arm_id == "native_tools_baseline":
            _verify_native_scope(sidecar, task, state, envelope, revalidated, clock, select_bindings=select_bindings)
        elif arm_id.startswith("captured_projection_reference:"):
            _verify_projection_scope(sidecar, revalidated, clock)
        elif arm_id.startswith("current_graph_baseline:"):
            if sidecar.fenced_observation_run_id is not None or sidecar.fenced_observation_repository_identity is not None:
                if sidecar.fenced_observation_run_id != revalidated.run_id or sidecar.fenced_observation_repository_identity != revalidated.repository_identity:
                    raise ExperimentRefusal("graph_observation_fence_mismatch")
        elif arm_id == "postgres_native_fts:postgresql":
            envelope_error, *_ = _verify_envelope_against_pin(envelope, revalidated)
            if envelope_error is not None:
                raise ExperimentRefusal(envelope_error)
        cost = clock.sample(cost_type, failures=0)
        _record_verified_sidecar(sidecar, revalidated, cost, _token=_VERIFICATION_TOKEN)
        return revalidated, cost
    except CorrespondenceVerificationFailure:
        raise
    except (ExperimentRefusal, RepresentationValidationError) as exc:
        code = getattr(exc, "code", "baseline_correspondence_refused")
        raise CorrespondenceVerificationFailure(str(code), clock.sample(cost_type, failures=1)) from exc
    except Exception as exc:
        raise CorrespondenceVerificationFailure("baseline_correspondence_unresolved", clock.sample(cost_type, failures=1)) from exc

__all__ = [
    "CorrespondenceVerificationFailure", "verify_strict_baseline_correspondence_sidecar",
]
