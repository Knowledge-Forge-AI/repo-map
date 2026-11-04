"""Publication-specific proof that prefix normalization preserves selected files."""
from __future__ import annotations

from typing import Any

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_scope import evaluation_path_prefix
from retrieval_semantic_baseline_inputs import _verify_actual_inputs
from retrieval_semantic_baseline_work import _CostClock
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_provenance import VerifiedPublicationPin


def verify_baseline_source_scope(
    sidecar: Any, envelope: QueryEnvelope, task: EvaluationTask,
    pin: VerifiedPublicationPin, clock: _CostClock | None,
    selected_bindings: tuple[str, ...],
) -> None:
    """Do not infer scope equality from normalized strings alone.

    A lexical ``shared`` scope can include the file ``shared``; the frozen
    ``shared/`` task cannot. Only a complete, checked publication manifest can
    prove that the extra exact-name candidate does not exist. Other changes
    to a raw prefix retain the existing strict mismatch refusal.
    """
    try:
        requested = evaluation_path_prefix(task.source_path_prefix)
        observed = evaluation_path_prefix(envelope.scope.source_path_prefix)
    except (TypeError, ValueError) as exc:
        raise ExperimentRefusal("envelope_source_scope_mismatch") from exc
    if requested == observed:
        return
    if (
        requested is None or observed is None
        or not requested.descendants_only or observed.descendants_only
        or requested.canonical != observed.canonical
        or sidecar is None or clock is None
    ):
        raise ExperimentRefusal("envelope_source_scope_mismatch")
    inputs = _verify_actual_inputs(
        getattr(sidecar, "projection_inputs", None),
        getattr(sidecar, "projection_policy", None), pin, clock,
    )
    selected = set(selected_bindings)
    if any(
        entry.binding_id in selected
        and entry.source_relative_path == requested.canonical
        for entry in inputs.manifest.entries
    ):
        raise ExperimentRefusal("normalized_scope_would_widen_selection")
