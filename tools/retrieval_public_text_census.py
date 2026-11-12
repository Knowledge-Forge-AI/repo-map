"""Frozen task-side/runtime applicability and a bounded public-text preparation ledger.

The census is data-only and calibration-only. Every task must match its
retained digest. Question and gold values are never read for selection: task
state comes only from the unchanged v1 decisions and the supplemental
public-text policy, and documents come only from the accepted preparation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast, Any

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_evaluation_admission_w5 import AdmissionVerificationError
from retrieval_evaluation_schema import EvaluationTask
from retrieval_public_text_admission import admit_public_text_query
from retrieval_public_text_contracts import (
    ADMISSION_POLICY_VERSION, CENSUS_SCOPE_REFUSED, DOCUMENT_CAP_EXCEEDED, TASK_DIGEST_MISMATCH,
    PublicTextRefusal, counter_mapping,
)
from retrieval_public_text_descriptors import MAX_DOCUMENTS, PublicTextPreparation, revalidate_publication_pin
from retrieval_semantic_generator_inputs import MAX_CALIBRATION_TASKS, _digest, _query_decision
from retrieval_semantic_provenance import RepresentationValidationError, VerifiedPublicationPin

CENSUS_SCHEMA = "cloe-public-text-census-v1"
CENSUS_STATUSES = frozenset({"ready", "document_only", "no_documents", "preparation_absent"})


def task_sha256(task: EvaluationTask) -> str:
    """The same digest the learned v1 query decision records for this task."""
    return _digest(task.to_dict())


def retained_task_sha256(task: EvaluationTask) -> str:
    """The unchanged retained manifest scheme: sorted compact ASCII-escaped JSON."""
    return str(digest_json(task.to_dict()))


@dataclass(frozen=True)
class TaskCensusRecord:
    """Closed per-task ledger row; it carries no question, gold or plan value."""

    task_id: str
    task_sha256: str
    retained_task_sha256: str
    generation: int
    requested_mode: str
    comparability_stratum: str
    intended_match_surface: str
    grading_rule: str
    v1_evaluator: Mapping[str, Any]
    v1_learned_state: str
    v1_learned_reason: str | None
    public_text_state: str
    public_text_reason: str | None
    public_text_layer: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "task_sha256": self.task_sha256, "generation": self.generation,
            "retained_task_sha256": self.retained_task_sha256,
            "requested_mode": self.requested_mode, "comparability_stratum": self.comparability_stratum,
            "intended_match_surface": self.intended_match_surface, "grading_rule": self.grading_rule,
            "v1_evaluator_state": self.v1_evaluator["state"],
            "v1_evaluator_reason": self.v1_evaluator["refusal_code"] or self.v1_evaluator["reason_category"],
            "v1_learned_state": self.v1_learned_state, "v1_learned_reason": self.v1_learned_reason,
            "public_text_state": self.public_text_state, "public_text_reason": self.public_text_reason,
            "public_text_layer": self.public_text_layer,
        }


@dataclass(frozen=True)
class PublicTextCensus:
    graph_id: str
    backend: str
    generation: int
    publication_identity: str
    tasks: tuple[TaskCensusRecord, ...]
    status: str
    document_count: int
    v1_verified_pair_count: int
    exclusion_counts: Mapping[str, int]
    privacy_scope_id: str | None
    preparation_measurements: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        states = [task.public_text_state for task in self.tasks]
        result = {
            "schema": CENSUS_SCHEMA, "admission_policy_version": ADMISSION_POLICY_VERSION,
            "graph_id": self.graph_id, "backend": self.backend, "generation": self.generation,
            "publication_identity": self.publication_identity, "status": self.status,
            "task_count": len(self.tasks), "public_text_state_counts": counter_mapping(states),
            "public_text_reason_counts": counter_mapping([t.public_text_reason for t in self.tasks if t.public_text_reason]),
            "v1_learned_state_counts": counter_mapping([task.v1_learned_state for task in self.tasks]),
            "ranked_public_text_queries": states.count("admitted"),
            "tasks": [task.to_dict() for task in self.tasks],
            "document_count": self.document_count, "v1_verified_pair_count": self.v1_verified_pair_count,
            "exclusion_counts": dict(self.exclusion_counts), "privacy_scope_id": self.privacy_scope_id,
            "preparation_measurements": None if self.preparation_measurements is None else dict(self.preparation_measurements),
        }
        result["census_identity"] = str(digest_json(result))
        return result


def build_public_text_census(
    tasks: Sequence[EvaluationTask],
    *,
    retained_task_digests: Mapping[str, str],
    policy: BodyProjectionPolicy,
    publication_pin: VerifiedPublicationPin,
    observed_backend: str,
    frozen_policy_digest: str | None = None,
    preparation: PublicTextPreparation | None = None,
) -> PublicTextCensus:
    """Repeat the declared task checks against the current accepted publication and summarize readiness.

    The pin is revalidated at entry and again before return; either failure is
    ``PUBLICATION_REVALIDATION_FAILED`` for the whole census.
    """
    try:
        return _build_public_text_census(
            tasks, retained_task_digests=retained_task_digests, policy=policy,
            publication_pin=publication_pin, observed_backend=observed_backend,
            frozen_policy_digest=frozen_policy_digest, preparation=preparation,
        )
    except PublicTextRefusal:
        raise
    except (AdmissionVerificationError, RepresentationValidationError, TypeError, ValueError) as error:
        raise PublicTextRefusal(CENSUS_SCOPE_REFUSED) from error


def _build_public_text_census(
    tasks: Sequence[EvaluationTask], *, retained_task_digests: Mapping[str, str], policy: BodyProjectionPolicy,
    publication_pin: VerifiedPublicationPin, observed_backend: str, frozen_policy_digest: str | None,
    preparation: PublicTextPreparation | None,
) -> PublicTextCensus:
    pin = publication_pin
    if type(pin) is not VerifiedPublicationPin or not isinstance(retained_task_digests, Mapping):
        raise PublicTextRefusal(CENSUS_SCOPE_REFUSED)
    revalidate_publication_pin(pin)
    census = _census_records(
        tasks, retained_task_digests=retained_task_digests, policy=policy, pin=pin,
        observed_backend=observed_backend, frozen_policy_digest=frozen_policy_digest, preparation=preparation,
    )
    revalidate_publication_pin(pin)
    return census


def _census_records(
    tasks: Sequence[EvaluationTask], *, retained_task_digests: Mapping[str, str], policy: BodyProjectionPolicy,
    pin: VerifiedPublicationPin, observed_backend: str, frozen_policy_digest: str | None,
    preparation: PublicTextPreparation | None,
) -> PublicTextCensus:
    if (
        not isinstance(tasks, Sequence) or isinstance(cast(object, tasks), (str, bytes)) or not tasks
        or len(tasks) > MAX_CALIBRATION_TASKS or not all(type(t) is EvaluationTask for t in tasks)
        or len({t.task_id for t in tasks}) != len(tasks)
    ):
        raise PublicTextRefusal(CENSUS_SCOPE_REFUSED)
    if set(retained_task_digests) != {task.task_id for task in tasks}:
        raise PublicTextRefusal(TASK_DIGEST_MISMATCH)
    records: list[TaskCensusRecord] = []
    for task in tasks:
        if type(task) is not EvaluationTask or task.split != "calibration" or task.generation != pin.generation:
            raise PublicTextRefusal(CENSUS_SCOPE_REFUSED)
        digest = task_sha256(task)
        retained_digest = retained_task_sha256(task)
        if retained_task_digests[task.task_id] != retained_digest:
            raise PublicTextRefusal(TASK_DIGEST_MISMATCH)
        decision = admit_public_text_query(
            task, policy=policy, publication_pin=pin, observed_backend=observed_backend,
            frozen_policy_digest=frozen_policy_digest,
        )
        learned = _query_decision(task, pin)
        if learned.task_sha256 != digest:
            raise PublicTextRefusal(TASK_DIGEST_MISMATCH)
        records.append(TaskCensusRecord(
            task.task_id, digest, retained_digest, task.generation, task.requested_mode, task.comparability_stratum,
            task.intended_match_surface, task.grading_rule, decision.v1_decision.to_dict(), learned.state,
            learned.reason, decision.state, decision.refusal_code or decision.reason_category,
            decision.policy_enforcement_layer,
        ))
    publication_identity = str(digest_json(pin.to_dict()))
    if preparation is None:
        return PublicTextCensus(
            pin.graph_id, pin.backend, pin.generation, publication_identity, tuple(records),
            "preparation_absent", 0, 0, {}, None, None,
        )
    if (
        type(preparation) is not PublicTextPreparation or preparation.publication_identity != publication_identity
        or (preparation.graph_id, preparation.backend, preparation.generation) != (pin.graph_id, pin.backend, pin.generation)
    ):
        raise PublicTextRefusal(CENSUS_SCOPE_REFUSED)
    count = len(preparation.documents)
    if count > MAX_DOCUMENTS:
        raise PublicTextRefusal(DOCUMENT_CAP_EXCEEDED)
    queries = sum(1 for record in records if record.public_text_state == "admitted")
    status = "no_documents" if count == 0 else ("ready" if queries else "document_only")
    return PublicTextCensus(
        pin.graph_id, pin.backend, pin.generation, publication_identity, tuple(records), status, count,
        preparation.v1_verified_pair_count, counter_mapping([item.reason for item in preparation.exclusions]),
        preparation.privacy_scope_id, preparation.measurements,
    )
