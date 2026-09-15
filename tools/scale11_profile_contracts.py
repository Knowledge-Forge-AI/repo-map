"""Public-safe result and scaling contracts for SCALE11 profiling."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import ClassVar, Mapping


FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)
PROFILES = (
    "file_raw_heavy",
    "canonical_node_evidence_heavy",
    "canonical_edge_evidence_heavy",
    "duplicate_proposal_heavy",
    "payload_heavy",
    "mixed",
)
CLASSIFICATIONS = frozenset(
    {
        "stable_linear_characterization",
        "fixed_overhead_dominated",
        "data_shape_sensitive",
        "spill_sensitive",
        "superlinear_suspect",
        "measurement_unstable",
        "insufficient_evidence",
    }
)
_AVAILABILITY = frozenset({"available", "unavailable"})
_MAX_PAYLOAD_BYTES = 1_048_576
_FORBIDDEN_TOKENS = (
    "/Users/",
    "postgresql://",
    "repository_name",
    "graph_name",
    "source_id",
    "canonical_key",
    "stage_id",
    "receipt_id",
)


class Scale11ContractError(ValueError):
    """Raised when SCALE11 evidence violates its closed public contract."""


@dataclass(frozen=True)
class MetricValue:
    """One explicitly available or unavailable metric."""

    value: int | float | None
    availability: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.availability not in _AVAILABILITY:
            raise Scale11ContractError("metric availability is invalid")
        if self.availability == "available":
            if self.reason is not None or not _is_number(self.value):
                raise Scale11ContractError("available metric value is invalid")
        elif self.value is not None or not _is_category(self.reason):
            raise Scale11ContractError("unavailable metric reason is invalid")

    @classmethod
    def available(cls, value: int | float) -> MetricValue:
        return cls(value=value, availability="available")

    @classmethod
    def unavailable(cls, reason: str) -> MetricValue:
        return cls(value=None, availability="unavailable", reason=reason)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "availability": self.availability,
            "value": self.value,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class FamilyProfile:
    """Measured work and accepted event attribution for one retained family."""

    family: str
    row_count: int
    normalized_bytes: int
    spool_bytes: int
    encoded_bytes: MetricValue
    preparation_seconds: MetricValue
    checksum_seconds: MetricValue
    copy_seconds: MetricValue
    statistics_seconds: MetricValue
    completeness_validation_seconds: MetricValue
    semantic_guard_seconds: MetricValue
    merge_seconds: MetricValue
    cleanup_seconds: MetricValue

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise Scale11ContractError("profile family is invalid")
        for value in (self.row_count, self.normalized_bytes, self.spool_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise Scale11ContractError("profile family count is invalid")

    def to_payload(self) -> dict[str, object]:
        elapsed = sum(
            _available_float(metric)
            for metric in (
                self.preparation_seconds,
                self.checksum_seconds,
                self.copy_seconds,
                self.statistics_seconds,
                self.completeness_validation_seconds,
                self.semantic_guard_seconds,
                self.merge_seconds,
                self.cleanup_seconds,
            )
            if metric.availability == "available"
        )
        throughput = self.row_count / elapsed if elapsed > 0 else None
        elapsed_per_thousand = elapsed * 1_000 / self.row_count if self.row_count else None
        return {
            "family": self.family,
            "row_count": self.row_count,
            "normalized_bytes": self.normalized_bytes,
            "spool_bytes": self.spool_bytes,
            "encoded_bytes": self.encoded_bytes.to_payload(),
            "bytes_per_row": self.normalized_bytes / self.row_count if self.row_count else None,
            "rows_per_second": throughput,
            "elapsed_seconds_per_thousand_rows": elapsed_per_thousand,
            "prepare_elapsed": self.preparation_seconds.to_payload(),
            "checksum_elapsed": self.checksum_seconds.to_payload(),
            "copy_elapsed": self.copy_seconds.to_payload(),
            "statistics_elapsed": self.statistics_seconds.to_payload(),
            "completeness_validation_elapsed": self.completeness_validation_seconds.to_payload(),
            "semantic_guard_elapsed": self.semantic_guard_seconds.to_payload(),
            "merge_elapsed": self.merge_seconds.to_payload(),
            "cleanup_elapsed": self.cleanup_seconds.to_payload(),
        }


@dataclass(frozen=True)
class ProfileResult:
    """One bounded receipt-bearing profiling repetition."""

    schema_version: ClassVar[int] = 1
    profile: str
    size_band: int
    repetition: int
    work_items: int
    observation_count: int
    elapsed_seconds: float
    families: tuple[FamilyProfile, ...]
    aggregate_metrics: Mapping[str, MetricValue]
    receipt_complete: bool
    generation: int
    structural_digest: str
    cleanup_complete: bool
    threshold_evaluation: Mapping[str, object]
    boundary_occurrences: Mapping[str, tuple[MetricValue, ...]]
    repeat_equal: bool | None = None

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise Scale11ContractError("result profile is invalid")
        for value in (self.size_band, self.repetition, self.work_items, self.observation_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise Scale11ContractError("result counter is invalid")
        if not _is_number(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise Scale11ContractError("result elapsed time is invalid")
        if tuple(family.family for family in self.families) != FAMILIES:
            raise Scale11ContractError("result family manifest is invalid")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise Scale11ContractError("result generation is invalid")
        if len(self.structural_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.structural_digest
        ):
            raise Scale11ContractError("result structural digest is invalid")
        if not all(_is_category(category) and isinstance(metric, MetricValue) for category, metric in self.aggregate_metrics.items()):
            raise Scale11ContractError("result aggregate metric is invalid")

    def to_payload(self) -> dict[str, object]:
        family_payloads = [family.to_payload() for family in self.families]
        encoded_values = [
            _available_number(family.encoded_bytes)
            for family in self.families
            if family.encoded_bytes.availability == "available"
        ]
        total_encoded = (
            sum(encoded_values)
            if len(encoded_values) == len(self.families)
            else None
        )
        client_peak = _metric_payload_value(
            self.aggregate_metrics.get("client_memory_bytes")
        )
        postgres_metric = self.aggregate_metrics.get(
            "postgres_group_peak_rss_bytes",
            self.aggregate_metrics.get("postgresql_memory_bytes"),
        )
        payload = {
            "schema_version": self.schema_version,
            "workload_profile": self.profile,
            "size_band": self.size_band,
            "execution_mode": "direct",
            "repetition": self.repetition,
            "result_category": "complete",
            "publication_result": (
                "complete_receipt" if self.receipt_complete else "missing_receipt"
            ),
            "family_count": len(self.families),
            "total_rows": sum(family.row_count for family in self.families),
            "total_normalized_bytes": sum(
                family.normalized_bytes for family in self.families
            ),
            "total_spool_bytes": sum(
                family.spool_bytes for family in self.families
            ),
            "total_encoded_bytes": total_encoded,
            "total_elapsed_seconds": self.elapsed_seconds,
            "client_peak_rss_bytes": client_peak,
            "postgres_peak_rss_available": (
                postgres_metric is not None
                and postgres_metric.availability == "available"
            ),
            "postgres_peak_rss_bytes_when_available": _metric_payload_value(
                postgres_metric
            ),
            "temporary_bytes_delta": _metric_payload_value(
                self.aggregate_metrics.get("temporary_byte_upper_bound_bytes")
            ),
            "wal_bytes_delta": _metric_payload_value(
                self.aggregate_metrics.get("wal_upper_bound_bytes")
            ),
            "statement_count": _metric_payload_value(
                self.aggregate_metrics.get("statement_count")
            ),
            "receipt_complete": self.receipt_complete,
            "repeat_equal": self.repeat_equal,
            "cleanup_complete": self.cleanup_complete,
            "threshold_crossings": dict(self.threshold_evaluation),
            "boundary_metrics": {
                category: self.aggregate_metrics[category].to_payload()
                for category in sorted(self.aggregate_metrics)
            },
            "boundary_occurrences": {
                category: [metric.to_payload() for metric in metrics]
                for category, metrics in sorted(
                    self.boundary_occurrences.items()
                )
            },
            "families": family_payloads,
        }
        _validate_payload(payload)
        return payload


@dataclass(frozen=True)
class ProfileAggregate:
    """Multi-band characterization retaining every source repetition."""

    schema_version: ClassVar[int] = 1
    profile: str
    size_bands: tuple[int, ...]
    repetition_count: int
    elapsed_medians: tuple[float, ...]
    elapsed_coefficients_of_variation: tuple[float, ...]
    elapsed_ratios: tuple[float, ...]
    classification: str
    repetitions: tuple[ProfileResult, ...]
    family_row_medians: Mapping[str, tuple[float, ...]]

    def __post_init__(self) -> None:
        if self.classification not in CLASSIFICATIONS:
            raise Scale11ContractError("scaling classification is invalid")

    def to_payload(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "size_bands": list(self.size_bands),
            "repetition_count": self.repetition_count,
            "elapsed_medians": list(self.elapsed_medians),
            "elapsed_coefficients_of_variation": list(self.elapsed_coefficients_of_variation),
            "elapsed_ratios": list(self.elapsed_ratios),
            "classification": self.classification,
            "family_row_medians": {
                family: list(self.family_row_medians[family]) for family in FAMILIES
            },
            "repetitions": [result.to_payload() for result in self.repetitions],
        }
        _validate_payload(payload)
        return payload


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _is_category(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 64
        and all(
            character.islower()
            or character.isdigit()
            or character == "_"
            for character in value
        )
    )


def _validate_payload(payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise Scale11ContractError("SCALE11 payload limit exceeded")
    text = encoded.decode("utf-8")
    if any(token in text for token in _FORBIDDEN_TOKENS):
        raise Scale11ContractError("SCALE11 payload contains a forbidden field")


def _metric_payload_value(metric: MetricValue | None) -> int | float | None:
    if metric is None or metric.availability != "available":
        return None
    return metric.value


def _available_float(metric: MetricValue) -> float:
    return float(_available_number(metric))


def _available_number(metric: MetricValue) -> int | float:
    if metric.availability != "available" or metric.value is None:
        raise Scale11ContractError("available metric value is missing")
    return metric.value
