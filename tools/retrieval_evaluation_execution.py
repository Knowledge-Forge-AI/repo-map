"""Adapter dispatch and durable per-repetition evaluation observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
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
    QUERY_CONTRACT_VERSION, QueryEnvelope, QueryMode, QueryScope,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_publication import (
    read_postgres_accepted_publication, read_sqlite_accepted_publication,
)
from retrieval_evaluation_accounting import ByteLayerAccounting, summarize_timing_samples
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_grading import ExecutionState, GradedSlotRecord, grade_task_execution
from retrieval_evaluation_graph import execute_graph_baseline_task
from retrieval_evaluation_native import execute_native_baseline_task
from retrieval_evaluation_reference import execute_projection_reference_task
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_views import MaterializedNativeView


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

    def execute(self, arm_id: str, task: EvaluationTask) -> TaskOutcome:
        if arm_id == "native_tools_baseline":
            return execute_native_baseline_task(task, self.native_view)
        if arm_id.startswith("current_graph_baseline:"):
            home = self.sqlite_home if arm_id.endswith(":sqlite") else self.postgres_home
            if home is None:
                raise ValueError("PostgreSQL arm has no published generation")
            return execute_graph_baseline_task(task, home)
        if arm_id == "captured_projection_reference:sqlite":
            config = load_graph_registry_config_home(self.sqlite_home)
            if not isinstance(config, LocalSqliteConfig):
                raise ValueError("SQLite arm requires SQLite configuration")
            current, _ = read_sqlite_accepted_publication(config, task.graph_id)
            return execute_projection_reference_task(task, self.sqlite_projection, current_accepted=current)
        if arm_id == "captured_projection_reference:postgresql":
            if self.postgres_home is None or self.postgres_projection is None:
                raise ValueError("PostgreSQL projection arm has no published generation")
            config = load_graph_registry_config_home(self.postgres_home)
            if not isinstance(config, OpsConfig):
                raise ValueError("PostgreSQL arm requires PostgreSQL configuration")
            current, _ = read_postgres_accepted_publication(config, task.graph_id, psql_command=self.psql_command)
            return execute_projection_reference_task(task, self.postgres_projection, current_accepted=current)
        raise ValueError("unsupported evaluation arm")


def failed_outcome(task: EvaluationTask, arm_id: str, reason: str, elapsed_ns: int) -> TaskOutcome:
    mode = QueryMode(task.requested_mode)
    backend = "sqlite" if arm_id.endswith(":sqlite") else (
        "postgresql" if arm_id.endswith(":postgresql") else "native_filesystem"
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
