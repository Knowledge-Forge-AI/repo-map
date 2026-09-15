"""Immutable performance evidence values and scalar arithmetic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import math


class PerformanceEvidenceError(ValueError):
    """Raised when performance evidence cannot support a result."""



class QueryWorkload(StrEnum):
    EXACT_CANONICAL_LOOKUP = "exact_canonical_lookup"
    PATH_PREFIX_LOOKUP = "path_prefix_lookup"
    ONE_HOP_NEIGHBORHOOD = "one_hop_neighborhood"
    DOCUMENT_EVIDENCE_LOOKUP = "document_evidence_lookup"
    STORAGE_SUMMARY_SERIALIZATION = "storage_summary_serialization"



@dataclass(frozen=True)
class ClosedSpan:
    code: str
    sequence: int
    start_ns: int
    finish_ns: int
    wall_ns: int
    process_cpu_ns: int | None
    outcome: str

    def __post_init__(self) -> None:
        for value in (self.sequence, self.start_ns, self.finish_ns, self.wall_ns):
            _require_nonnegative_int(value)
        if self.sequence < 1 or self.finish_ns < self.start_ns:
            raise PerformanceEvidenceError("performance span interval is invalid")
        if self.wall_ns != self.finish_ns - self.start_ns:
            raise PerformanceEvidenceError("performance span duration is fabricated")
        if self.process_cpu_ns is not None:
            _require_nonnegative_int(self.process_cpu_ns)



@dataclass(frozen=True)
class QuerySummary:
    workload: QueryWorkload
    warmups: int
    samples_ns: tuple[int, ...]
    result_cardinality: int
    bytes_returned: int
    process_cpu_ns: int
    server_time: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.workload, QueryWorkload):
            raise PerformanceEvidenceError("query workload is not closed")
        _require_nonnegative_int(self.warmups)
        _require_nonnegative_int(self.result_cardinality)
        _require_nonnegative_int(self.bytes_returned)
        _require_nonnegative_int(self.process_cpu_ns)
        if not self.samples_ns:
            raise PerformanceEvidenceError("query samples are missing")
        for sample in self.samples_ns:
            _require_nonnegative_int(sample)
            if sample == 0:
                raise PerformanceEvidenceError("query duration is fabricated")

    def to_public_payload(self) -> dict[str, object]:
        return {
            "workload": self.workload.value,
            "warmup_iterations": self.warmups,
            "measured_iterations": len(self.samples_ns),
            "result_cardinality": self.result_cardinality,
            "p50_wall_ns": nearest_rank(self.samples_ns, 50),
            "p95_wall_ns": nearest_rank(self.samples_ns, 95),
            "maximum_wall_ns": max(self.samples_ns),
            "client_process_cpu_ns": self.process_cpu_ns,
            "server_time": "unobserved",
            "bytes_returned": self.bytes_returned,
        }



def nearest_rank(samples: Sequence[int], percentile: int) -> int:
    if not samples or isinstance(percentile, bool) or not 1 <= percentile <= 100:
        raise PerformanceEvidenceError("percentile request is invalid")
    ordered = sorted(samples)
    for value in ordered:
        _require_nonnegative_int(value)
    rank = math.ceil(percentile * len(ordered) / 100)
    return ordered[rank - 1]



def _require_nonnegative_int(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PerformanceEvidenceError("performance integer is invalid")



def _validate_interval(start: int, finish: int) -> None:
    _require_nonnegative_int(start)
    _require_nonnegative_int(finish)
    if finish < start:
        raise PerformanceEvidenceError("performance interval is inverted")

