"""Revalidate actual projection artifacts against an independently read pin."""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import CorrespondenceRefusal, ProjectionInputs, check_correspondence
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_baseline_work import _CostClock, _MeteredArtifactStore

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
