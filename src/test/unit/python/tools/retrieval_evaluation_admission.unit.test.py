"""Focused W5 admission/refusal contracts (ADR 0144)."""

from __future__ import annotations

from dataclasses import replace
from copy import copy
from types import SimpleNamespace

import pytest

from repomap_test_support.w5_semantic_support import (
    BIND_COMP,
    BIND_CORE,
    BIND_PRIVATE,
    BIND_REDACTED,
    make_w5_calibration_task,
    make_w5_policy,
    make_w5_verified_pin,
)
from retrieval_evaluation_admission_w5 import (
    AdmissionState,
    AdmissionVerificationError,
    BindingDisposition,
    W5AdmissionDecision,
    W5AdmissionRuntime,
    admit_w5_task,
    execute_after_admission,
)
from retrieval_semantic_provenance import verify_publication_provenance_from_adapter


def _task(*selected: str, body: bool = True):
    task = make_w5_calibration_task(
        selected_bindings=tuple(selected),
        grading_rule="safety_refusal" if body and selected == (BIND_PRIVATE,) else "ranked_positive",
        gold_targets=() if body and selected == (BIND_PRIVATE,) else None,
        expected_refusal_code="binding_privacy_not_authorized" if body and selected == (BIND_PRIVATE,) else None,
    )
    return replace(
        task,
        intended_match_surface="captured_text" if body else "stored_metadata",
        comparability_stratum="body" if body else "metadata",
        requested_mode="literal_captured_text" if body else "ranked_discovery",
    ).validate()


def _pin():
    return make_w5_verified_pin(selected_binding_ids=None)


def _policy_with_core_binding(**changes):
    base = make_w5_policy()
    bindings = dict(base.bindings)
    bindings[BIND_CORE] = replace(bindings[BIND_CORE], **changes)
    return replace(base, bindings=bindings).validate()


def _pin_for_policy(policy):
    adapter = _pin()._readback_adapter
    assert adapter is not None
    return verify_publication_provenance_from_adapter(adapter, policy=policy)


def test_structural_pin_cannot_substitute_for_issued_publication_provenance() -> None:
    pin = _pin()
    called: list[str] = []
    fields = (
        "graph_id", "backend", "run_id", "generation", "policy_digest",
        "admitted_public_bindings", "denied_bindings",
    )
    spoof = SimpleNamespace(**{name: getattr(pin, name) for name in fields})

    def fake_revalidation():
        called.append("untrusted_revalidation")
        return pin

    spoof.revalidate_current = fake_revalidation
    with pytest.raises(AdmissionVerificationError, match="publication_pin_required"):
        execute_after_admission(
            _task(BIND_CORE), policy=make_w5_policy(), publication_pin=spoof,
            observed_backend="sqlite", execute=lambda _decision: called.append("candidate_access"),
        )
    assert called == []


@pytest.mark.parametrize(("field", "value"), [
    ("generation", 2), ("generation", None), ("generation", True),
    ("split", "held_out"), ("split", "unknown"),
])
def test_task_generation_and_calibration_scope_are_checked_before_access(field: str, value: object) -> None:
    called: list[object] = []
    task = replace(_task(BIND_CORE), **{field: value})
    with pytest.raises(AdmissionVerificationError, match="w5_task_publication_scope_mismatch"):
        execute_after_admission(
            task, policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite",
            execute=lambda decision: called.append(decision),
        )
    assert called == []


def test_policy_declared_private_absent_is_refused_before_access() -> None:
    decision = admit_w5_task(
        _task(BIND_PRIVATE), policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite"
    )

    assert decision.state is AdmissionState.REFUSED
    assert decision.execution_allowed is False
    assert decision.refusal_code == "binding_privacy_not_authorized"
    assert decision.bindings[0].disposition is BindingDisposition.DENIED_DECLARED
    assert decision.policy_enforcement_layer == "evaluator_precheck"
    assert decision.backend_policy_enforcement_observed is False


def test_mixed_denied_scope_refuses_without_executing_public_subset() -> None:
    called = False

    def callback(_decision):
        nonlocal called
        called = True
        return "candidate-access"

    decision, result = execute_after_admission(
        _task(BIND_CORE, BIND_PRIVATE), policy=make_w5_policy(), publication_pin=_pin(),
        observed_backend="sqlite", execute=callback,
    )

    assert decision.state is AdmissionState.REFUSED
    assert result is None
    assert called is False
    assert decision.omitted_binding_ids == (BIND_PRIVATE,)


def test_forged_admitted_decision_cannot_override_a_denial() -> None:
    decision = admit_w5_task(
        _task(BIND_PRIVATE), policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite"
    )
    forged = W5AdmissionDecision(
        **{
            **decision.__dict__,
            "state": AdmissionState.ADMITTED,
            "refusal_code": None,
        }
    )
    with pytest.raises(AdmissionVerificationError, match="denial_must_refuse_whole_scope"):
        forged.validate()


def test_undeclared_selection_is_distinct_from_privacy_denial() -> None:
    decision = admit_w5_task(
        _task("not-declared"), policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite"
    )

    assert decision.state is AdmissionState.UNAVAILABLE
    assert decision.refusal_code is None
    assert decision.reason_category == "undeclared"
    assert decision.bindings[0].disposition is BindingDisposition.UNDECLARED


def test_declared_public_absent_is_not_inferred_private() -> None:
    base = make_w5_policy()
    bindings = dict(base.bindings)
    bindings[BIND_PRIVATE] = replace(bindings[BIND_PRIVATE],
        original_binding_privacy="public-dev", resolved_binding_privacy="public-dev")
    policy = replace(base, bindings=bindings).validate()
    decision = admit_w5_task(
        _task(BIND_PRIVATE, body=False), policy=policy,
        publication_pin=_pin_for_policy(policy), observed_backend="sqlite"
    )

    assert decision.state is AdmissionState.UNAVAILABLE
    assert decision.reason_category == "declared_public_absent"
    assert decision.bindings[0].disposition is BindingDisposition.DECLARED_PUBLIC_ABSENT


def test_published_undeclared_binding_is_not_an_authorization_denial() -> None:
    base = make_w5_policy()
    policy = replace(base, bindings={k:v for k,v in base.bindings.items() if k != BIND_CORE},
                     selected_binding_ids=base.selected_binding_ids - {BIND_CORE}).validate()
    decision = admit_w5_task(
        _task(BIND_CORE, body=False), policy=policy,
        publication_pin=_pin_for_policy(policy), observed_backend="sqlite"
    )
    assert decision.state is AdmissionState.UNAVAILABLE
    assert decision.refusal_code is None
    assert decision.bindings[0].disposition is BindingDisposition.UNDECLARED


@pytest.mark.parametrize("kind", ["copy", "digest", "admitted", "denied", "mutate"])
def test_copied_pin_fields_cannot_authorize_candidate_access(kind: str) -> None:
    original = _pin()
    policy = _policy_with_core_binding(alias="forged") if kind in {"digest", "mutate"} else make_w5_policy()
    if kind == "copy":
        pin = copy(original)
    elif kind == "digest":
        pin = replace(original, policy_digest=policy.policy_digest())
    elif kind == "admitted":
        pin = replace(original, admitted_public_bindings=frozenset())
    elif kind == "mutate":
        pin = original
        object.__setattr__(pin, "policy_digest", policy.policy_digest())
    else:
        pin = replace(original, denied_bindings={})
    called: list[object] = []
    with pytest.raises(AdmissionVerificationError, match="publication_pin_not_issued"):
        execute_after_admission(_task(BIND_CORE, body=False), policy=policy, publication_pin=pin,
            observed_backend="sqlite", execute=lambda decision: called.append(decision))
    assert called == []


@pytest.mark.parametrize("supplied", [False, True])
def test_runtime_freezes_policy_before_later_policy_and_pin_substitution(supplied: bool) -> None:
    policies = {"sqlite": make_w5_policy()}
    pins = {"sqlite": _pin()}
    changed = _policy_with_core_binding(alias="changed")
    runtime = W5AdmissionRuntime(policy_by_backend=policies, pin_by_backend=pins,
        frozen_policy_digest=changed.policy_digest() if supplied else None)
    policies["sqlite"] = changed
    pins["sqlite"] = _pin_for_policy(policies["sqlite"])
    with pytest.raises(AdmissionVerificationError, match="frozen_policy_digest_mismatch"):
        runtime.admit("native_tools_baseline", _task(BIND_CORE), observed_backend="native_filesystem")


def test_nonbody_metadata_does_not_apply_body_retention_exclusion() -> None:
    decision = admit_w5_task(
        _task(BIND_REDACTED, body=False), policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite"
    )
    assert decision.state is AdmissionState.ADMITTED


def test_body_retention_is_declared_denial_for_body_surface() -> None:
    decision = admit_w5_task(
        _task(BIND_REDACTED), policy=make_w5_policy(), publication_pin=_pin(), observed_backend="sqlite"
    )
    assert decision.state is AdmissionState.REFUSED
    assert decision.refusal_code == "retention_not_authorized"


def test_declared_email_and_feed_body_roles_refuse_but_feed_metadata_admits() -> None:
    feed_policy = _policy_with_core_binding(
        alias="feeds",
        role="feeds",
        original_evidence_retention="full-authorized",
        resolved_evidence_retention="full-authorized",
    )
    feed_body = admit_w5_task(
        _task(BIND_CORE), policy=feed_policy,
        publication_pin=_pin_for_policy(feed_policy), observed_backend="sqlite",
    )
    assert feed_body.state is AdmissionState.REFUSED
    assert feed_body.refusal_code == "feed_body_forbidden"

    email_policy = _policy_with_core_binding(alias="inbox", role="email")
    email_body = admit_w5_task(
        _task(BIND_CORE), policy=email_policy,
        publication_pin=_pin_for_policy(email_policy), observed_backend="sqlite",
    )
    assert email_body.state is AdmissionState.REFUSED
    assert email_body.refusal_code == "email_body_forbidden"

    feed_metadata_policy = _policy_with_core_binding(
        alias="feeds",
        role="feeds",
        original_evidence_retention="metadata-only",
        resolved_evidence_retention="metadata-only",
    )
    feed_metadata = admit_w5_task(
        _task(BIND_CORE, body=False), policy=feed_metadata_policy,
        publication_pin=_pin_for_policy(feed_metadata_policy), observed_backend="sqlite",
    )
    assert feed_metadata.state is AdmissionState.ADMITTED


def test_captured_reference_uses_actual_pin_backend_and_rejects_unknown_backend() -> None:
    policy = make_w5_policy()
    task = _task(BIND_CORE, body=False)
    for backend in ("sqlite", "postgresql"):
        decision = admit_w5_task(
            task,
            policy=policy,
            publication_pin=make_w5_verified_pin(backend=backend),
            observed_backend="captured_reference",
        )
        assert decision.state is AdmissionState.ADMITTED

    class UnsupportedBackendPin:
        graph_id = policy.graph_id
        backend = "memory"
        run_id = 1
        generation = 1
        policy_digest = policy.policy_digest()
        admitted_public_bindings = frozenset({BIND_CORE, BIND_COMP, BIND_REDACTED})
        denied_bindings: dict[str, str] = {}

        def revalidate_current(self):
            return self

    with pytest.raises(AdmissionVerificationError, match="publication_pin_required"):
        admit_w5_task(
            task,
            policy=policy,
            publication_pin=UnsupportedBackendPin(),
            observed_backend="captured_reference",
        )


@pytest.mark.parametrize("kind", ["policy", "publication", "digest"])
def test_stale_foreign_or_digest_drift_refuses_before_classification(kind: str) -> None:
    pin = _pin()
    frozen_policy_digest: str | None = None
    if kind == "policy":
        pin = replace(pin, policy_digest="sha256:" + "f" * 64)
    elif kind == "publication":
        pin = replace(pin, graph_id="foreign-graph")
    else:
        frozen_policy_digest = "sha256:" + "f" * 64
    with pytest.raises(AdmissionVerificationError):
        admit_w5_task(
            _task(BIND_CORE),
            policy=make_w5_policy(),
            publication_pin=pin,
            observed_backend="sqlite",
            frozen_policy_digest=frozen_policy_digest,
        )


def test_runtime_requires_both_real_backend_inputs() -> None:
    with pytest.raises(AdmissionVerificationError, match="backend_inputs_incomplete"):
        W5AdmissionRuntime(policy_by_backend={"sqlite": make_w5_policy()}, pin_by_backend={}).validate()
