"""Evaluator-owned W5 admission from a live publication and frozen policy.

This module uses token-issued publication provenance without loading a model
runtime. It recomputes every selected binding classification from the supplied
policy and returns a decision before an arm callback is allowed to run.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Callable

from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.projection_policy import (
    ALLOWED_BINDING_PRIVACY,
    ALLOWED_EVIDENCE_RETENTION,
    ALLOWED_GRAPH_PRIVACY,
    BodyProjectionPolicy,
    ExclusionReason,
    _is_email_role_or_path,
    _is_feed_role_or_path,
)
from retrieval_evaluation_admission_w5_contracts import (
    AdmissionState,
    AdmissionVerificationError,
    BindingAdmission,
    BindingDisposition,
    PublicationPin,
    W5AdmissionDecision,
    W5AdmissionRuntime,
    W5_ADMISSION_SCHEMA,
    target_backend_for_arm,
)
from retrieval_semantic_provenance import VerifiedPublicationPin


def _is_body_task(task: Any) -> bool:
    def value(item: Any) -> str:
        return str(getattr(item, "value", item))

    return (
        value(getattr(task, "intended_match_surface", "")) == "captured_text"
        or value(getattr(task, "comparability_stratum", "")) == "body"
        or value(getattr(task, "requested_mode", "")) == "literal_captured_text"
    )


def _policy_denial(policy: BodyProjectionPolicy, binding_id: str, *, body: bool) -> str | None:
    """Read only policy declarations; role names and task labels never authorize access."""
    binding = policy.bindings.get(binding_id)
    if binding is None:
        return None
    if "inherit" in {
        binding.original_graph_privacy,
        binding.resolved_graph_privacy,
        binding.original_binding_privacy,
        binding.resolved_binding_privacy,
        binding.original_evidence_retention,
        binding.resolved_evidence_retention,
    }:
        return ExclusionReason.UNRESOLVED_INHERIT_POLICY.value
    if (
        binding.original_graph_privacy != ALLOWED_GRAPH_PRIVACY
        or binding.resolved_graph_privacy != ALLOWED_GRAPH_PRIVACY
    ):
        return ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value
    if (
        binding.original_binding_privacy != ALLOWED_BINDING_PRIVACY
        or binding.resolved_binding_privacy != ALLOWED_BINDING_PRIVACY
    ):
        return ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value
    if body and (
        binding.original_evidence_retention != ALLOWED_EVIDENCE_RETENTION
        or binding.resolved_evidence_retention != ALLOWED_EVIDENCE_RETENTION
    ):
        return ExclusionReason.RETENTION_NOT_AUTHORIZED.value
    if body and _is_email_role_or_path(
        binding.role, binding.source_kind, binding.alias, None
    ):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN.value
    if body and _is_feed_role_or_path(
        binding.role, binding.source_kind, binding.alias, None
    ):
        return ExclusionReason.FEED_BODY_FORBIDDEN.value
    return None


def _pin_identity(pin: PublicationPin) -> dict[str, Any]:
    required = ("graph_id", "backend", "run_id", "generation", "policy_digest")
    if any(not hasattr(pin, name) for name in required):
        raise AdmissionVerificationError("publication_pin_identity_incomplete")
    for name in required:
        if name in {"run_id", "generation"}:
            if type(getattr(pin, name)) is not int or getattr(pin, name) < 1:
                raise AdmissionVerificationError("publication_pin_identity_invalid")
        elif type(getattr(pin, name)) is not str or not getattr(pin, name):
            raise AdmissionVerificationError("publication_pin_identity_invalid")
    admitted = getattr(pin, "admitted_public_bindings", None)
    denied = getattr(pin, "denied_bindings", None)
    if (
        not isinstance(admitted, Collection)
        or isinstance(admitted, (str, bytes))
        or not isinstance(denied, Mapping)
    ):
        raise AdmissionVerificationError("publication_pin_bindings_invalid")
    admitted_ids = tuple(sorted(admitted))
    denied_map = dict(sorted(denied.items()))
    if any(type(item) is not str or not item for item in admitted_ids) or any(
        type(key) is not str or not key or type(value) is not str or not value
        for key, value in denied_map.items()
    ):
        raise AdmissionVerificationError("publication_pin_bindings_invalid")
    if set(admitted_ids) & set(denied_map):
        raise AdmissionVerificationError("publication_pin_bindings_overlap")
    identity: dict[str, Any] = {
        "graph_id": pin.graph_id,
        "backend": pin.backend,
        "run_id": pin.run_id,
        "generation": pin.generation,
        "policy_digest": pin.policy_digest,
        "admitted_public_bindings": admitted_ids,
        "denied_bindings": denied_map,
    }
    for name in (
        "publication_bundle_id", "snapshot_manifest_id", "extraction_receipt_id",
        "receipt_identity", "graph_candidate_id",
    ):
        value = getattr(pin, name, None)
        if value is not None:
            if type(value) is not str or not value:
                raise AdmissionVerificationError("publication_pin_identity_invalid")
            identity[name] = value
    return identity


def _revalidate_pin(pin: PublicationPin) -> tuple[PublicationPin, dict[str, Any]]:
    required = (
        "graph_id", "backend", "run_id", "generation", "policy_digest",
        "admitted_public_bindings", "denied_bindings",
    )
    if (
        not isinstance(pin, VerifiedPublicationPin)
        or not all(hasattr(pin, name) for name in required)
        or not callable(getattr(pin, "revalidate_current", None))
    ):
        raise AdmissionVerificationError("publication_pin_required")
    if not VerifiedPublicationPin.is_factory_issued(pin):
        raise AdmissionVerificationError("publication_pin_not_issued")
    try:
        current = pin.revalidate_current()
    except Exception as exc:
        raise AdmissionVerificationError("publication_pin_revalidation_failed") from exc
    if (
        not isinstance(current, VerifiedPublicationPin)
        or not all(hasattr(current, name) for name in required)
        or not callable(getattr(current, "revalidate_current", None))
    ):
        raise AdmissionVerificationError("publication_pin_revalidation_invalid")
    if not VerifiedPublicationPin.is_factory_issued(current):
        raise AdmissionVerificationError("publication_pin_not_issued")
    return current, _pin_identity(current)


def _selected_binding_ids(task: Any) -> tuple[str, ...]:
    graph_id = getattr(task, "graph_id", None)
    raw = getattr(task, "selected_bindings", None)
    if (
        type(graph_id) is not str
        or not graph_id
        or not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes))
        or not raw
    ):
        raise AdmissionVerificationError("unknown_w5_selection")
    result: list[str] = []
    for value in raw:
        if type(value) is not str or not value:
            raise AdmissionVerificationError("unknown_w5_selection")
        try:
            binding_id = value if value.startswith("bind1:") else graph_source_binding_id(graph_id, value)
        except (TypeError, ValueError) as exc:
            raise AdmissionVerificationError("unknown_w5_selection") from exc
        result.append(binding_id)
    if len(result) != len(set(result)):
        raise AdmissionVerificationError("duplicate_w5_selection")
    return tuple(result)


def _required_task_text(task: Any, field: str) -> str:
    value: object = getattr(task, field, None)
    if type(value) is not str or not value:
        raise AdmissionVerificationError("w5_task_identity_invalid")
    return value


def admit_w5_task(
    task: Any,
    *,
    policy: BodyProjectionPolicy,
    publication_pin: PublicationPin,
    observed_backend: str,
    frozen_policy_digest: str | None = None,
    post_publication_pin: PublicationPin | None = None,
) -> W5AdmissionDecision:
    """Recompute admission from the live pin and policy before any arm callback."""
    if not isinstance(policy, BodyProjectionPolicy):
        raise AdmissionVerificationError("w5_policy_required")
    policy.validate()
    task_id = _required_task_text(task, "task_id")
    requested_mode = _required_task_text(task, "requested_mode")
    if type(observed_backend) is not str or not observed_backend:
        raise AdmissionVerificationError("w5_task_identity_invalid")
    if policy.graph_id != getattr(task, "graph_id", None):
        raise AdmissionVerificationError("w5_policy_graph_mismatch")
    if observed_backend not in {"sqlite", "postgresql", "captured_reference", "native_filesystem"}:
        raise AdmissionVerificationError("w5_observed_backend_invalid")
    current_pin, before_identity = _revalidate_pin(publication_pin)
    if current_pin.graph_id != policy.graph_id:
        raise AdmissionVerificationError("publication_graph_mismatch")
    if (
        getattr(task, "split", None) != "calibration"
        or type(getattr(task, "generation", None)) is not int
        or task.generation != current_pin.generation
    ):
        raise AdmissionVerificationError("w5_task_publication_scope_mismatch")
    if observed_backend in {"sqlite", "native_filesystem"}:
        target_backend = "sqlite"
    elif observed_backend == "postgresql":
        target_backend = "postgresql"
    elif observed_backend == "captured_reference":
        target_backend = current_pin.backend
        if target_backend not in {"sqlite", "postgresql"}:
            raise AdmissionVerificationError("captured_reference_backend_invalid")
    else:
        target_backend = None
    if target_backend is None:
        raise AdmissionVerificationError("w5_observed_backend_invalid")
    if current_pin.backend != target_backend:
        raise AdmissionVerificationError("publication_pin_backend_mismatch")
    if current_pin.policy_digest != policy.policy_digest():
        raise AdmissionVerificationError("policy_digest_drift")
    if frozen_policy_digest is not None and frozen_policy_digest != current_pin.policy_digest:
        raise AdmissionVerificationError("frozen_policy_digest_mismatch")
    if post_publication_pin is not None:
        _post_pin, after_identity = _revalidate_pin(post_publication_pin)
        if before_identity != after_identity:
            raise AdmissionVerificationError("publication_pin_drift")

    selected = _selected_binding_ids(task)
    body = _is_body_task(task)
    admitted = set(current_pin.admitted_public_bindings)
    observed_denied = dict(current_pin.denied_bindings)
    bindings: list[BindingAdmission] = []
    for binding_id in selected:
        policy_reason = _policy_denial(policy, binding_id, body=body)
        if policy_reason is not None:
            disposition = BindingDisposition.DENIED_DECLARED
            reason = policy_reason
        elif binding_id not in policy.bindings:
            disposition = (
                BindingDisposition.FOREIGN_PUBLIC
                if binding_id in admitted
                else BindingDisposition.UNDECLARED
            )
            reason = (
                "binding_not_declared"
                if disposition is BindingDisposition.UNDECLARED
                else "binding_not_declared_in_policy"
            )
        elif binding_id in observed_denied:
            disposition = BindingDisposition.DENIED_OBSERVED
            reason = observed_denied[binding_id]
        elif binding_id in admitted:
            disposition, reason = BindingDisposition.ADMITTED_PUBLIC, None
        else:
            disposition, reason = BindingDisposition.DECLARED_PUBLIC_ABSENT, "binding_absent_from_accepted_publication"
        bindings.append(BindingAdmission(binding_id, disposition, reason))

    denied = [
        item for item in bindings
        if item.disposition in {
            BindingDisposition.DENIED_OBSERVED,
            BindingDisposition.DENIED_DECLARED,
        }
    ]
    unknown = [
        item for item in bindings
        if item.disposition in {
            BindingDisposition.UNDECLARED,
            BindingDisposition.DECLARED_PUBLIC_ABSENT,
            BindingDisposition.FOREIGN_PUBLIC,
        }
    ]
    if denied:
        state = AdmissionState.REFUSED
        refusal_code = denied[0].reason_code or ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value
        reason_category = "authorization_denial"
        layer = "evaluator_precheck"
    elif unknown:
        state = AdmissionState.UNAVAILABLE
        refusal_code = None
        first = unknown[0]
        reason_category = first.disposition.value
        layer = None
    else:
        state = AdmissionState.ADMITTED
        refusal_code = None
        reason_category = None
        layer = None
    return W5AdmissionDecision(
        task_id=task_id,
        graph_id=policy.graph_id,
        requested_mode=requested_mode,
        observed_backend=observed_backend,
        selected_binding_ids=selected,
        bindings=tuple(bindings),
        state=state,
        reason_category=reason_category,
        refusal_code=refusal_code,
        policy_digest=current_pin.policy_digest,
        policy_enforcement_layer=layer,
        publication_identity=before_identity,
    ).validate()


def execute_after_admission(
    task: Any,
    *,
    policy: BodyProjectionPolicy,
    publication_pin: PublicationPin,
    observed_backend: str,
    execute: Callable[[W5AdmissionDecision], Any],
    frozen_policy_digest: str | None = None,
    post_publication_pin: PublicationPin | None = None,
) -> tuple[W5AdmissionDecision, Any | None]:
    """Run an arm callback only for a freshly admitted decision."""
    decision = admit_w5_task(
        task,
        policy=policy,
        publication_pin=publication_pin,
        observed_backend=observed_backend,
        frozen_policy_digest=frozen_policy_digest,
        post_publication_pin=post_publication_pin,
    )
    if not decision.execution_allowed:
        return decision, None
    return decision, execute(decision)


__all__ = [
    "AdmissionState",
    "AdmissionVerificationError",
    "BindingAdmission",
    "BindingDisposition",
    "PublicationPin",
    "W5AdmissionDecision",
    "W5AdmissionRuntime",
    "W5_ADMISSION_SCHEMA",
    "admit_w5_task",
    "execute_after_admission",
    "target_backend_for_arm",
]
