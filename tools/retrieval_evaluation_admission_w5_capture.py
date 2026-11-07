"""Evaluator-owned native work evidence for a pre-execution W5 block."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_accounting import EvaluatorByteBreakdownV1
from retrieval_evaluation_native import DEFAULT_MAX_STDOUT_BYTES
from retrieval_semantic_experiment_contracts import ExperimentRefusal


class IssuedCapture(Protocol):
    @property
    def arm_id(self) -> str: ...

    @property
    def task_id(self) -> str: ...

    def validate(self) -> IssuedCapture: ...


@dataclass(frozen=True)
class NativePrecheckWork:
    """One evaluator-derived native zero-work witness awaiting collection."""

    arm_id: str
    task_id: str
    envelope_digest: str
    capture: IssuedCapture
    breakdown: EvaluatorByteBreakdownV1

    def validate(self) -> NativePrecheckWork:
        if self.arm_id != "native_tools_baseline" or not self.task_id:
            raise ExperimentRefusal("native_precheck_work_identity_invalid")
        self.capture.validate()
        self.breakdown.validate()
        if self.capture.arm_id != self.arm_id or self.capture.task_id != self.task_id:
            raise ExperimentRefusal("native_precheck_work_capture_mismatch")
        if (
            type(self.envelope_digest) is not str
            or not self.envelope_digest.startswith("sha256:")
        ):
            raise ExperimentRefusal("native_precheck_work_envelope_invalid")
        return self


def native_precheck_breakdown(envelope: QueryEnvelope) -> EvaluatorByteBreakdownV1:
    serialized = len(json.dumps(
        envelope.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8"))
    return EvaluatorByteBreakdownV1(
        raw_process_stdout_bytes=0,
        direct_selected_text_bytes=0,
        native_process_stdout_cap_bytes=DEFAULT_MAX_STDOUT_BYTES,
        decoded_candidate_count=0,
        returned_hit_count=0,
        serialized_envelope_bytes=serialized,
        observed_output_payload_bytes=0,
    ).validate()


def retain_native_work(
    runner: object,
    collector: object | None,
    arm_id: str,
    task: Any,
    envelope: QueryEnvelope,
    identity: Mapping[str, object],
) -> None:
    """Consume one runner witness and append it only when a collector exists."""
    if arm_id != "native_tools_baseline":
        return
    consume = getattr(runner, "take_native_precheck_work", None)
    if not callable(consume):
        return
    breakdown = consume(arm_id, task, envelope)
    if breakdown is None or collector is None:
        return
    add = getattr(collector, "add_byte_work", None)
    if not callable(add):
        raise ExperimentRefusal("native_precheck_collector_invalid")
    add(identity, breakdown)


__all__ = ["NativePrecheckWork", "native_precheck_breakdown", "retain_native_work"]
