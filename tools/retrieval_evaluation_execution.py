"""Adapter dispatch and durable per-repetition evaluation observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.query_contracts import (
    CapabilityState, DEFAULT_ORDERING_POLICY_VERSION, MatchSurface,
    OmissionRecord, QUERY_CONTRACT_VERSION, QueryEnvelope, QueryMode, QueryScope,
    refused_envelope,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_publication import (
    read_postgres_accepted_publication, read_sqlite_accepted_publication,
)
from retrieval_evaluation_accounting import (
    ByteLayerAccounting, EvaluatorByteBreakdownV1, summarize_timing_samples,
)
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_grading import ExecutionState, GradedSlotRecord, grade_task_execution
from retrieval_evaluation_graph import execute_graph_baseline_task
from retrieval_evaluation_native import (
    DEFAULT_MAX_STDOUT_BYTES, execute_native_baseline_task,
    execute_native_baseline_task_with_breakdown,
)
from retrieval_evaluation_reference import execute_projection_reference_task
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_views import MaterializedNativeView
from retrieval_evaluation_observation_contracts import ObservationPublicationPin
from retrieval_evaluation_admission_w5 import (
    AdmissionState, AdmissionVerificationError, W5AdmissionDecision, W5AdmissionRuntime,
)


TaskOutcome = tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]


@dataclass(frozen=True)
class ArmContext:
    """Generation-specific execution dependencies; no evaluation gold is consulted."""

    native_view: MaterializedNativeView
    sqlite_home: Path
    sqlite_projection: CapturedTextProjection
    postgres_home: Path | None
    postgres_projection: CapturedTextProjection | None
    psql_command: str
    postgres_lexical_home: Path | None = None
    postgres_lexical_input_bytes: int | None = None
    w5_admission: W5AdmissionRuntime | None = None

    @staticmethod
    def _observed_backend(arm_id: str) -> str:
        if arm_id == "native_tools_baseline":
            return "native_filesystem"
        if arm_id.startswith("captured_projection_reference:"):
            return "captured_reference"
        if arm_id.endswith(":sqlite"):
            return "sqlite"
        if arm_id.endswith(":postgresql"):
            return "postgresql"
        raise ValueError("unsupported evaluation arm")

    def _admission_outcome(
        self, arm_id: str, task: EvaluationTask,
    ) -> tuple[TaskOutcome | None, W5AdmissionDecision | None, int]:
        """Recompute W5 admission before any backend-specific read is reached."""
        if self.w5_admission is None:
            return None, None, 0
        started = time.perf_counter_ns()
        try:
            decision = self.w5_admission.admit(
                arm_id, task, observed_backend=self._observed_backend(arm_id),
            )
        except AdmissionVerificationError as error:
            elapsed = max(0, time.perf_counter_ns() - started)
            failed = failed_outcome(
                task, arm_id, error.code, elapsed,
                backend=self._observed_backend(arm_id),
            )
            provenance = dict(failed[1].provenance)
            provenance.update({
                "evaluator_precheck": True,
                "admission_schema": "cloe-w5-admission-v1",
                "admission_state": "failed",
                "policy_enforcement_layer": "evaluator_precheck",
                "backend_policy_enforcement_observed": False,
                "admission_elapsed_ns": elapsed,
                "admission_elapsed_overlapping": True,
            })
            return (
                (failed[0], replace(failed[1], provenance=provenance).validate(), failed[2], failed[3]),
                None,
                elapsed,
            )
        admission_elapsed = max(0, time.perf_counter_ns() - started)
        if decision.execution_allowed:
            return None, decision, admission_elapsed
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
                reason_code=item.reason_code or decision.reason_category or "w5_admission_refused",
                detail=f"evaluator precheck: {item.disposition.value}",
            ).validate()
            for item in decision.bindings
            if item.binding_id in decision.omitted_binding_ids
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
            "admission_elapsed_ns": admission_elapsed,
            "admission_elapsed_overlapping": True,
        }
        if decision.state is AdmissionState.REFUSED:
            envelope = refused_envelope(
                requested_mode=QueryMode(task.requested_mode), scope=scope,
                refusal_code=decision.refusal_code or "w5_admission_refused",
                omissions=omissions, provenance=provenance,
            )
            state = ExecutionState.REFUSED
        else:
            envelope = QueryEnvelope(
                contract_version=QUERY_CONTRACT_VERSION,
                requested_mode=QueryMode(task.requested_mode),
                effective_mode=QueryMode(task.requested_mode),
                match_surface=MatchSurface.NONE, scope=scope,
                ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
                capability_state=CapabilityState.UNAVAILABLE,
                omissions=omissions,
                unavailable_reason=decision.reason_category or "w5_admission_unavailable",
                provenance=provenance,
            ).validate()
            state = ExecutionState.UNAVAILABLE
        return (
            (state, envelope, admission_elapsed, ByteLayerAccounting(observed_output_payload_bytes=0)),
            decision,
            admission_elapsed,
        )

    @staticmethod
    def _add_admission_elapsed(outcome: TaskOutcome, admission_elapsed: int) -> TaskOutcome:
        state, envelope, elapsed, accounting = outcome
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

    def execute(
        self, arm_id: str, task: EvaluationTask, *,
        expected_pin: ObservationPublicationPin | None = None,
    ) -> TaskOutcome:
        precheck, decision, admission_elapsed = self._admission_outcome(arm_id, task)
        if precheck is not None:
            return precheck
        if arm_id == "native_tools_baseline":
            outcome = execute_native_baseline_task(task, self.native_view)
        elif arm_id.startswith("current_graph_baseline:"):
            home = self.sqlite_home if arm_id.endswith(":sqlite") else self.postgres_home
            if home is None:
                raise ValueError("PostgreSQL arm has no published generation")
            outcome = execute_graph_baseline_task(
                task, home, psql_command=self.psql_command, expected_pin=expected_pin,
            )
        elif arm_id == "captured_projection_reference:sqlite":
            config = load_graph_registry_config_home(self.sqlite_home)
            if not isinstance(config, LocalSqliteConfig):
                raise ValueError("SQLite arm requires SQLite configuration")
            current, _ = read_sqlite_accepted_publication(config, task.graph_id)
            outcome = execute_projection_reference_task(
                task, self.sqlite_projection, current_accepted=current,
            )
        elif arm_id == "captured_projection_reference:postgresql":
            if self.postgres_home is None or self.postgres_projection is None:
                raise ValueError("PostgreSQL projection arm has no published generation")
            config = load_graph_registry_config_home(self.postgres_home)
            if not isinstance(config, OpsConfig):
                raise ValueError("PostgreSQL arm requires PostgreSQL configuration")
            current, _ = read_postgres_accepted_publication(config, task.graph_id, psql_command=self.psql_command)
            outcome = execute_projection_reference_task(
                task, self.postgres_projection, current_accepted=current,
            )
        elif arm_id == "postgres_native_fts:postgresql":
            lex_home = self.postgres_lexical_home or self.postgres_home
            if lex_home is None:
                raise ValueError("PostgreSQL lexical arm has no published generation")
            outcome = execute_postgres_native_fts_task(task, lex_home)
        else:
            raise ValueError("unsupported evaluation arm")
        return (
            self._add_admission_elapsed(outcome, admission_elapsed)
            if decision is not None else outcome
        )

    def execute_with_breakdown(
        self,
        arm_id: str,
        task: EvaluationTask,
        *,
        expected_pin: ObservationPublicationPin | None = None,
    ) -> tuple[TaskOutcome, EvaluatorByteBreakdownV1 | None]:
        """Expose native byte/work evidence while preserving the legacy adapter."""
        if arm_id != "native_tools_baseline":
            return self.execute(arm_id, task, expected_pin=expected_pin), None
        precheck, decision, admission_elapsed = self._admission_outcome(arm_id, task)
        if precheck is not None:
            envelope = precheck[1]
            serialized = len(json.dumps(
                envelope.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            ).encode("utf-8"))
            return precheck, EvaluatorByteBreakdownV1(
                raw_process_stdout_bytes=0,
                direct_selected_text_bytes=0,
                native_process_stdout_cap_bytes=DEFAULT_MAX_STDOUT_BYTES,
                decoded_candidate_count=0,
                returned_hit_count=0,
                serialized_envelope_bytes=serialized,
                observed_output_payload_bytes=0,
            )
        state, envelope, elapsed, layers, breakdown = execute_native_baseline_task_with_breakdown(
            task, self.native_view,
        )
        outcome = (state, envelope, elapsed, layers)
        return (
            self._add_admission_elapsed(outcome, admission_elapsed)
            if decision is not None else outcome,
            breakdown,
        )


def failed_outcome(
    task: EvaluationTask,
    arm_id: str,
    reason: str,
    elapsed_ns: int,
    *,
    backend: str | None = None,
) -> TaskOutcome:
    mode = QueryMode(task.requested_mode)
    backend = backend or (
        "sqlite" if arm_id.endswith(":sqlite") else (
            "postgresql" if arm_id.endswith(":postgresql") else "native_filesystem"
        )
    )
    envelope = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=mode, effective_mode=mode,
        match_surface=MatchSurface.NONE, scope=QueryScope(graph_id=task.graph_id, backend=backend),
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.FAILED,
        provenance={"adapter_id": arm_id, "failure_type": reason},
    ).validate()
    return ExecutionState.FAILED, envelope, elapsed_ns, ByteLayerAccounting()


def maximum_observed_bytes(samples: list[ByteLayerAccounting]) -> ByteLayerAccounting:
    """Per-query maximum across repetitions; any unknown sample leaves that layer unknown."""
    maxima = {}
    for field in fields(ByteLayerAccounting):
        values = [getattr(sample, field.name) for sample in samples]
        maxima[field.name] = max(values) if all(value is not None for value in values) else None
    return ByteLayerAccounting(**maxima)


def measure_task_repetitions(
    task: EvaluationTask,
    arm_id: str,
    repetitions: int,
    execute: Callable[[], TaskOutcome],
    journal: AttemptJournal,
) -> tuple[GradedSlotRecord, list[dict[str, Any]], bool]:
    """Retain every repetition before deciding whether its outcome is reproducible."""
    observations: list[dict[str, Any]] = []
    outcomes: list[TaskOutcome] = []
    signatures: set[str] = set()
    for repetition in range(1, repetitions + 1):
        identity = {"task_id": task.task_id, "arm_id": arm_id, "repetition": repetition}
        journal.append({"event": "query_started", **identity})
        started = time.perf_counter_ns()
        try:
            outcome = execute()
        except Exception as error:
            outcome = failed_outcome(task, arm_id, type(error).__name__, time.perf_counter_ns() - started)
        state, envelope, elapsed, byte_layers = outcome
        public_envelope = envelope.to_dict()
        assert_canary_free(public_envelope)
        semantic_bytes = json.dumps(
            {"execution_state": state.value, "envelope": public_envelope},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        signature = "sha256:" + hashlib.sha256(semantic_bytes).hexdigest()
        signatures.add(signature)
        observation = {
            **identity, "execution_state": state.value, "elapsed_ns": max(0, elapsed),
            "byte_accounting": byte_layers.to_dict(), "outcome_sha256": signature,
        }
        journal.append({"event": "query_observed", **observation, "envelope": public_envelope})
        observations.append(observation)
        outcomes.append(outcome)

    divergent = len(signatures) != 1
    state, envelope, _, _ = outcomes[0]
    if divergent:
        state, envelope, _, _ = failed_outcome(task, arm_id, "nondeterministic_repetitions", 0)
    slot = grade_task_execution(
        task, execution_state=state, envelope=envelope,
        timing=summarize_timing_samples([item["elapsed_ns"] for item in observations]),
        byte_accounting=maximum_observed_bytes([item[3] for item in outcomes]),
    )
    assert_canary_free(slot.to_dict())
    journal.append({"event": "task_graded", "arm_id": arm_id, "divergent": divergent, "slot": slot.to_dict()})
    return slot, observations, divergent
