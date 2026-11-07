"""Timing sample statistics, byte-layer accounting, and external agent cost helpers (S3)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimingSummary:
    """Raw timing samples and median without claiming p95 on small sample counts."""

    sample_count: int
    raw_samples_ns: tuple[int, ...]
    min_ns: int
    median_ns: int
    max_ns: int
    p95_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "raw_samples_ns": list(self.raw_samples_ns),
            "min_ns": self.min_ns,
            "median_ns": self.median_ns,
            "max_ns": self.max_ns,
            "p95_ns": self.p95_ns,
        }


def summarize_timing_samples(samples_ns: Sequence[int]) -> TimingSummary:
    """Summarize raw nanosecond timing samples; p95 is None when sample_count < 20."""
    if not samples_ns:
        raise ValueError("samples_ns must be non-empty")
    cleaned: list[int] = []
    for s in samples_ns:
        if isinstance(s, bool) or not isinstance(s, int) or s < 0:
            raise ValueError("timing samples must be non-negative integers")
        cleaned.append(s)
    cleaned_tuple = tuple(cleaned)
    ordered = sorted(cleaned_tuple)
    n = len(ordered)
    median_val = int(statistics.median(ordered))
    p95_val: int | None = None
    if n >= 20:
        idx = min(n - 1, int(round(0.95 * (n - 1))))
        p95_val = ordered[idx]
    return TimingSummary(
        sample_count=n,
        raw_samples_ns=cleaned_tuple,
        min_ns=ordered[0],
        median_ns=median_val,
        max_ns=ordered[-1],
        p95_ns=p95_val,
    )


@dataclass(frozen=True)
class ByteLayerAccounting:
    """Layer-specific byte accounting; unobserved layers remain None, never zero."""

    observed_output_payload_bytes: int | None = None
    artifact_store_bytes_read: int | None = None
    internal_source_io_bytes: int | None = None
    model_tokens_spent: int | None = None
    agent_completion_cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_output_payload_bytes": self.observed_output_payload_bytes,
            "artifact_store_bytes_read": self.artifact_store_bytes_read,
            "internal_source_io_bytes": self.internal_source_io_bytes,
            "model_tokens_spent": self.model_tokens_spent,
            "agent_completion_cost_usd": self.agent_completion_cost_usd,
        }


EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1 = "cloe-w5-byte-accounting-v1"


@dataclass(frozen=True)
class EvaluatorByteBreakdownV1:
    """Versioned W5 byte/work breakdown separating raw process stdout, candidates, hits, envelope, and correspondence."""

    schema_version: str = EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1
    raw_process_stdout_bytes: int | None = None
    direct_selected_text_bytes: int | None = None
    native_process_stdout_cap_bytes: int | None = None
    decoded_candidate_count: int = 0
    returned_hit_count: int = 0
    serialized_envelope_bytes: int = 0
    observed_output_payload_bytes: int | None = None
    correspondence_verification_bytes_read: int = 0
    correspondence_verification_ns: int = 0

    def validate(self) -> EvaluatorByteBreakdownV1:
        if self.schema_version != EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1:
            raise ValueError("invalid_byte_breakdown_schema")
        for val in (
            self.raw_process_stdout_bytes,
            self.direct_selected_text_bytes,
            self.native_process_stdout_cap_bytes,
            self.observed_output_payload_bytes,
        ):
            if val is not None and (isinstance(val, bool) or not isinstance(val, int) or val < 0):
                raise ValueError("invalid_byte_breakdown_value")
        for req_int in (
            self.decoded_candidate_count,
            self.returned_hit_count,
            self.serialized_envelope_bytes,
            self.correspondence_verification_bytes_read,
            self.correspondence_verification_ns,
        ):
            if isinstance(req_int, bool) or not isinstance(req_int, int) or req_int < 0:
                raise ValueError("invalid_byte_breakdown_value")
        if self.returned_hit_count > self.decoded_candidate_count:
            raise ValueError("returned_hits_exceed_decoded_candidates")
        return self

    def with_correspondence(self, *, bytes_read: int, elapsed_ns: int) -> EvaluatorByteBreakdownV1:
        if type(bytes_read) is not int or type(elapsed_ns) is not int or bytes_read < 0 or elapsed_ns < 0:
            raise ValueError("invalid_correspondence_measurement")
        return EvaluatorByteBreakdownV1(
            schema_version=self.schema_version,
            raw_process_stdout_bytes=self.raw_process_stdout_bytes,
            direct_selected_text_bytes=self.direct_selected_text_bytes,
            native_process_stdout_cap_bytes=self.native_process_stdout_cap_bytes,
            decoded_candidate_count=self.decoded_candidate_count,
            returned_hit_count=self.returned_hit_count,
            serialized_envelope_bytes=self.serialized_envelope_bytes,
            observed_output_payload_bytes=self.observed_output_payload_bytes,
            correspondence_verification_bytes_read=self.correspondence_verification_bytes_read + bytes_read,
            correspondence_verification_ns=self.correspondence_verification_ns + elapsed_ns,
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "raw_process_stdout_bytes": self.raw_process_stdout_bytes,
            "direct_selected_text_bytes": self.direct_selected_text_bytes,
            "native_process_stdout_cap_bytes": self.native_process_stdout_cap_bytes,
            "decoded_candidate_count": self.decoded_candidate_count,
            "returned_hit_count": self.returned_hit_count,
            "serialized_envelope_bytes": self.serialized_envelope_bytes,
            "observed_output_payload_bytes": self.observed_output_payload_bytes,
            "correspondence_verification_bytes_read": self.correspondence_verification_bytes_read,
            "correspondence_verification_ns": self.correspondence_verification_ns,
        }


@dataclass(frozen=True)
class ExternalAgentCostSummary:
    """Accounting summary for externally supplied agent/model telemetry records."""

    total_attempts: int
    successful_task_count: int
    failed_attempt_count: int
    total_tokens_spent: int
    failed_attempt_tokens_spent: int
    total_cost_usd: float
    failed_attempt_cost_usd: float
    zero_success: bool
    tokens_per_successful_task: float | None
    cost_per_successful_task_usd: float | None
    success_denominator_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_attempts": self.total_attempts,
            "successful_task_count": self.successful_task_count,
            "failed_attempt_count": self.failed_attempt_count,
            "total_tokens_spent": self.total_tokens_spent,
            "failed_attempt_tokens_spent": self.failed_attempt_tokens_spent,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "failed_attempt_cost_usd": round(self.failed_attempt_cost_usd, 6),
            "zero_success": self.zero_success,
            "success_denominator_kind": self.success_denominator_kind,
            "tokens_per_successful_task": (
                round(self.tokens_per_successful_task, 2)
                if self.tokens_per_successful_task is not None
                else None
            ),
            "cost_per_successful_task_usd": (
                round(self.cost_per_successful_task_usd, 6)
                if self.cost_per_successful_task_usd is not None
                else None
            ),
        }


def compute_external_agent_cost(
    records: Sequence[Mapping[str, Any]],
) -> ExternalAgentCostSummary:
    """Compute agent cost over externally supplied telemetry, including failed spend."""
    if not records:
        raise ValueError("telemetry records must be non-empty")
    identified = [isinstance(record.get("task_id"), str) and bool(record["task_id"].strip()) for record in records]
    if any(identified) and not all(identified):
        raise ValueError("task_id coverage must be uniform; anonymous attempts cannot be pooled with distinct tasks")
    if not any(identified) and any("task_id" in record for record in records):
        raise ValueError("task_id must be a non-empty string when supplied")
    total_tokens = 0
    failed_tokens = 0
    total_cost = 0.0
    failed_cost = 0.0
    anon_success_count = 0
    succeeded_task_ids: set[str] = set()
    failed_count = 0

    for idx, rec in enumerate(records):
        tokens = rec.get("tokens_spent")
        cost = rec.get("cost_usd")
        succeeded = rec.get("succeeded")
        if (
            tokens is None
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens < 0
        ):
            raise ValueError(f"record[{idx}] has unknown spend for tokens_spent")
        if (
            cost is None
            or isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or math.isnan(float(cost))
            or math.isinf(float(cost))
            or float(cost) < 0.0
        ):
            raise ValueError(f"record[{idx}] has unknown spend for cost_usd")
        if not isinstance(succeeded, bool):
            raise ValueError(f"record[{idx}] succeeded must be a boolean")

        total_tokens += tokens
        total_cost += float(cost)
        if succeeded:
            task_id = rec.get("task_id")
            if isinstance(task_id, str) and task_id.strip():
                succeeded_task_ids.add(task_id.strip())
            else:
                anon_success_count += 1
        else:
            failed_count += 1
            failed_tokens += tokens
            failed_cost += float(cost)

    success_count = len(succeeded_task_ids) + anon_success_count
    zero_success = success_count == 0
    return ExternalAgentCostSummary(
        total_attempts=len(records),
        successful_task_count=success_count,
        failed_attempt_count=failed_count,
        total_tokens_spent=total_tokens,
        failed_attempt_tokens_spent=failed_tokens,
        total_cost_usd=total_cost,
        failed_attempt_cost_usd=failed_cost,
        zero_success=zero_success,
        tokens_per_successful_task=(
            None if zero_success else total_tokens / success_count
        ),
        cost_per_successful_task_usd=(
            None if zero_success else total_cost / success_count
        ),
        success_denominator_kind="distinct_task_ids" if all(identified) else "successful_attempts_without_task_identity",
    )


__all__ = [
    "ByteLayerAccounting",
    "EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1",
    "EvaluatorByteBreakdownV1",
    "ExternalAgentCostSummary",
    "TimingSummary",
    "compute_external_agent_cost",
    "summarize_timing_samples",
]
