"""The six learned arm operations and their public cells (study sections 9-11 and 19.4).

Per admitted task and repetition: exact reads and observed default-planner ANN
over the sealed study batches, the issued v1/v2 arm adapters, the maintained
RRF (current native FTS plus the exact vector arm, fallback disabled) and the
maintained file grading. Original v1/public-text decisions are retained for
every non-admitted task, so generation 2 stays document-only. Nothing manufactures
a completed ANN or a zero metric: a completed learned cell needs verified file
metrics, and every other outcome keeps its actual closed reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any

from common_lore_index.storage.semantic_candidate_sql import accepted_candidate_publication_sql
from common_lore_index.storage.semantic_candidates import CandidatePublication, EmbeddingProfile
from common_lore_index.storage.sql_core import sql_literal
from repomap_test_support.w5_experiment_postgres import PostgresHandle
from repomap_test_support.w5_experiment_support import merge_candidate_rows, selected_public_binding_ids
from repomap_test_support.w5_public_text_postgres import StudyRead, exact_read, observe_ann, run_study_sql
from retrieval_evaluation_execution import TaskOutcome
from retrieval_evaluation_schema import EvaluationTask
from retrieval_public_text_census import PublicTextCensus, retained_task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_public_text_fusion import (
    LEXICAL_ARM, fuse_study_arms, grade_fusion, project_public_text_candidates, public_text_fusion_to_dict,
    public_text_vector_arm, v1_vector_arm,
)
from retrieval_public_text_report_cells import cell
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import StudyGenerationSeal
from retrieval_public_text_study_catalog import StudyCatalog
from retrieval_public_text_study_queries import StudyQuery
from retrieval_public_text_study_schema import StudyEmbeddingProfile, qualified
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_fusion import AdmittedArmObservation
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_generator_kernel_contracts import MODEL_REVISION
from retrieval_semantic_provenance import VerifiedPublicationPin

KINDS = ("exact_vector", "hnsw_vector", "hybrid_rrf")
MODEL = "BAAI/bge-small-en-v1.5"
GENERATOR = "cloe-bge-onnx-cpu"


def profiles(artifact_profile_identity: str) -> dict[str, EmbeddingProfile | StudyEmbeddingProfile]:
    """The exact production v1 profile fields and the study v2 profile with the same model/generator."""
    version = "v1:" + artifact_profile_identity[7:]
    return {ARM_V1: EmbeddingProfile(MODEL, MODEL_REVISION, GENERATOR, version, 384).validate(),
            ARM_PTX: StudyEmbeddingProfile(MODEL, MODEL_REVISION, GENERATOR, version).validate()}


@dataclass(frozen=True, repr=False)
class LearnedGeneration:
    """Everything one generation's learned reads bind to; private vectors and text stay in memory."""

    postgres: PostgresHandle
    catalog: StudyCatalog
    seal: StudyGenerationSeal
    pin: VerifiedPublicationPin
    publication: CandidatePublication
    v1: PublicGenerationInput
    preparation: PublicTextPreparation
    census: PublicTextCensus
    scope: PrivateMarkerScope
    imported: frozenset[str]
    profiles: Mapping[str, Any] = field(repr=False)

    def __repr__(self) -> str:
        return f"LearnedGeneration(generation={self.seal.generation}, imported={sorted(self.imported)})"


def _digest(value: object) -> dict[str, Any]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("ascii")
    return {"sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "length": len(raw)}


def _query_vector(seal: StudyGenerationSeal, arm: str, task_id: str) -> tuple[float, ...] | None:
    prefix = "v1.query:" if arm == ARM_V1 else "ptx.q."
    matches = [r.vector for r in seal.arms[arm].records
               if r.mode is SemanticMode.QUERY and r.record_id == prefix + task_id]
    return matches[0] if len(matches) == 1 else None


def _decision(census: PublicTextCensus, task_id: str, arm: str) -> tuple[str, str | None]:
    row = next(item for item in census.tasks if item.task_id == task_id)
    return ((row.v1_learned_state, row.v1_learned_reason) if arm == ARM_V1
            else (row.public_text_state, row.public_text_reason))


@dataclass(frozen=True)
class _Outcome:
    state: str
    reason: tuple[str, str] | None
    rows: tuple[dict[str, Any], ...] = ()
    plan: dict[str, Any] | None = None


def _reads(context: LearnedGeneration, task: EvaluationTask, arm: str, vector: tuple[float, ...], kind: str,
           repetition: int) -> _Outcome:
    """Per selected binding, exact or observed ANN; merged only when every binding completed."""
    rows_by_binding: dict[str, tuple[dict[str, Any], ...]] = {}
    plans: list[StudyRead] = []
    for binding in selected_public_binding_ids(task):
        query = StudyQuery(context.catalog, context.catalog.names.batch_id(context.seal.generation, arm), arm,
                           context.profiles[arm], context.publication, binding, vector)
        read = (exact_read(context.postgres, query, context.pin) if kind == "exact_vector"
                else observe_ann(context.postgres, query, context.pin, task_id=task.task_id, repetition=repetition))
        if read.plan_sha256 is not None:
            plans.append(read)
        if read.state != "completed":
            plan = None if not plans else _plan(plans)
            return _Outcome(read.state, ("sql", read.reason or read.state), plan=plan)
        rows_by_binding[binding] = read.rows
    rows = merge_candidate_rows(rows_by_binding, limit=20)
    return _Outcome("completed", None, rows, _plan(plans) if kind == "hnsw_vector" else None)


def _plan(reads: Sequence[StudyRead]) -> dict[str, Any]:
    joined = "".join(str(item.plan_sha256) for item in reads).encode("ascii")
    return {"sha256": "sha256:" + hashlib.sha256(joined).hexdigest(),
            "length": sum(int(item.plan_length or 0) for item in reads),
            "index_selected": all(item.index_selected is True for item in reads)}


def _arm(context: LearnedGeneration, kind: str, arm: str, rows: Sequence[Mapping[str, Any]],
         task: EvaluationTask) -> AdmittedArmObservation:
    if arm == ARM_V1:
        return v1_vector_arm(kind, rows, task=task, pin=context.pin, inputs=context.v1)
    projection = project_public_text_candidates(rows, preparation=context.preparation, seal=context.seal.arms[arm],
                                                pin=context.pin, task=task, scope=context.scope)
    return public_text_vector_arm(kind, projection, seal=context.seal.arms[arm], pin=context.pin, task=task)


def lexical_observation(task: EvaluationTask, outcome: TaskOutcome, pin: VerifiedPublicationPin) -> AdmittedArmObservation:
    """The actual current native FTS repetition, exactly as the original hybrid consumed it."""
    state, envelope, _elapsed, _bytes = outcome
    return AdmittedArmObservation(arm_id=LEXICAL_ARM, mode=task.requested_mode, verified_pin=pin,
                                  execution_state=state, envelope=envelope,
                                  selected_binding_ids=selected_public_binding_ids(task))


def _graded(context: LearnedGeneration, arms: Sequence[AdmittedArmObservation], task: EvaluationTask,
            arm: str) -> tuple[_Outcome, dict[str, Any] | None]:
    fused = fuse_study_arms(arms, pin=context.pin, private_markers=context.scope.markers)
    metrics = grade_fusion(fused, task, context.pin, private_markers=context.scope.markers)
    representations = {item.arm_id: ("not_applicable" if item.arm_id == LEXICAL_ARM else arm) for item in arms}
    if metrics is None:
        # The maintained fusion state is kept (e.g. an FTS arm that refused the original mode); never success.
        state = getattr(fused.execution_state, "value", "failed")
        state = state if state in ("refused", "unavailable") else "failed"
        return _Outcome(state, ("fusion", f"fusion_{state}")), None
    return _Outcome("completed", None, rows=(public_text_fusion_to_dict(fused, representations=representations),)), metrics


def _cell(task: EvaluationTask, kind: str, arm: str, repetition: int, outcome: _Outcome,
          metrics: Mapping[str, float] | None, context: LearnedGeneration | None) -> dict[str, Any]:
    """A completed learned cell exists only with verified file metrics; anything else keeps its reason."""
    completed = outcome.state == "completed"
    if completed and (metrics is None or context is None):
        raise RuntimeError("completed learned cell without verified file metrics")
    seal = context.seal.arms[arm] if completed and context is not None else None
    partial = seal is not None and seal.capability == "token_partial"
    return cell(
        generation=task.generation, task_id=task.task_id, task_sha256=retained_task_sha256(task),
        arm=f"{kind}:{arm}", repetition=repetition, state=outcome.state, reason=outcome.reason,
        capability=None if seal is None else ("partial" if partial else "complete"), incomplete=partial,
        truncated=partial, publication_coverage="unknown" if seal is None else seal.publication_coverage,
        metrics=metrics if completed else None, result=_digest(outcome.rows) if completed else None,
        plan=outcome.plan if kind == "hnsw_vector" else None)


def _decision_cells(task: EvaluationTask, arm: str, repetition: int, state: str, reason: str | None,
                    source: str) -> list[dict[str, Any]]:
    cell_state = "refused" if state == "refused" else "unavailable"
    outcome = _Outcome(cell_state, (source, reason or state))
    return [_cell(task, kind, arm, repetition, outcome, None, None) for kind in KINDS]


def learned_cells(context: LearnedGeneration, task: EvaluationTask, repetition: int,
                  lexical: TaskOutcome) -> tuple[dict[str, Any], ...]:
    """Six cells (three kinds x two representations) for one task repetition, in arm order."""
    cells: list[dict[str, Any]] = []
    for arm in (ARM_V1, ARM_PTX):
        state, reason = _decision(context.census, task.task_id, arm)
        if state != "admitted":
            source = "v1_decision" if arm == ARM_V1 else "public_text_decision"
            cells.extend(_decision_cells(task, arm, repetition, state, reason, source))
            continue
        vector = _query_vector(context.seal, arm, task.task_id)
        if context.seal.arms[arm].capability == "refused":
            blocked: _Outcome | None = _Outcome("refused", ("study", "v1_own_record_truncated"))
        elif arm not in context.imported or vector is None:
            blocked = _Outcome("failed", ("study", "study_import_refused"))
        else:
            blocked = None
        if blocked is not None:
            cells.extend(_cell(task, kind, arm, repetition, blocked, None, context) for kind in KINDS)
            continue
        assert vector is not None
        exact_arm: AdmittedArmObservation | None = None
        exact_outcome: _Outcome | None = None
        for kind in ("exact_vector", "hnsw_vector"):
            outcome, metrics = _reads(context, task, arm, vector, kind, repetition), None
            if outcome.state == "completed":
                try:
                    observation = _arm(context, kind, arm, outcome.rows, task)
                    graded, metrics = _graded(context, (observation,), task, arm)
                    outcome = replace(graded, plan=outcome.plan)
                    if kind == "exact_vector":
                        exact_arm = observation
                except (ExperimentRefusal, ValueError) as error:
                    outcome = _Outcome("failed", ("fusion", getattr(error, "code", "fusion_refused")), plan=outcome.plan)
            if kind == "exact_vector":
                exact_outcome = outcome
            cells.append(_cell(task, kind, arm, repetition, outcome, metrics, context))
        assert exact_outcome is not None
        if exact_arm is None:
            hybrid = _Outcome("failed" if exact_outcome.state == "completed" else exact_outcome.state,
                              exact_outcome.reason or ("fusion", "exact_vector_not_completed"))
            cells.append(_cell(task, "hybrid_rrf", arm, repetition, hybrid, None, context))
            continue
        try:
            hybrid, metrics = _graded(context, (lexical_observation(task, lexical, context.pin), exact_arm), task, arm)
        except (ExperimentRefusal, ValueError) as error:
            hybrid, metrics = _Outcome("failed", ("fusion", getattr(error, "code", "fusion_refused"))), None
        cells.append(_cell(task, "hybrid_rrf", arm, repetition, hybrid, metrics, context))
    order = {f"{kind}:{arm}": index for index, (arm, kind) in enumerate(
        (a, k) for a in (ARM_V1, ARM_PTX) for k in KINDS)}
    return tuple(sorted(cells, key=lambda item: order[item["arm"]]))


def old_batch_status(postgres: PostgresHandle, catalog: StudyCatalog, publication: CandidatePublication,
                     batch_id: str) -> tuple[str, str]:
    """No-vector readback of an old batch row against the accepted-publication CTE; returns status and raw sha256."""
    names = catalog.names
    sql = (f'SET ROLE "{names.owner}";\nWITH {accepted_candidate_publication_sql(publication)}\n'
           "SELECT json_build_object('batch_present', EXISTS (SELECT 1 FROM "
           f"{qualified(names.batch_table)} b WHERE b.batch_id = {sql_literal(batch_id)}"
           f" AND b.study_identity = {sql_literal(names.study_identity)}),"
           " 'current', EXISTS (SELECT 1 FROM accepted))::text;\n")
    raw = run_study_sql(postgres, sql)
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"batch_present", "current"} or not all(
            type(item) is bool for item in value.values()):
        raise ValueError("old batch status readback is malformed")
    if value["current"]:
        raise ValueError("old publication is still current")
    status = "imported_non_current" if value["batch_present"] else "not_imported_non_current"
    return status, "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["KINDS", "LearnedGeneration", "learned_cells", "lexical_observation", "old_batch_status", "profiles"]
