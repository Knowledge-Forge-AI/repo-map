"""Public-safe closed characterization of SCALE28-FIX11 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


CORRECTED_PATCH_SHA256 = (
    "c46003e5af8b72e2669b44764fc5daed"
    "ba051d71cf6ee5091fbe485e67767f74"
)
RECOVERED_RECEIPT_SHA256 = (
    "32d6ef1c1fc1dfbc953dc28383e3c864"
    "be144c75999a1709f9c3391197d0e94c"
)
ACCEPTED_TRACE_PACKET_SHA256 = (
    "3b3db0b5c90172110e51ef261a978699"
    "d7f846c492c1a23977266701bfe0b495"
)
COMPONENT_PROBE_PACKET_SHA256 = (
    "a6089ef41e410236671af36b42e46f728"
    "f660d83c0140fa9d2a309ec73347425"
)


class PreparationFork(StrEnum):
    A = "implementation_or_harness_defect"
    B = "selected_implementation_policy_insufficient"
    C = "architecture_insufficient"


class Fix11Outcome(StrEnum):
    A = "executable_candidate_accepted"
    B = "evidence_or_implementation_blocker"
    C = "policy_or_architecture_decision_required"


@dataclass(frozen=True, slots=True)
class ProvenanceSummary:
    result: str
    changed_path_count: int
    matching_commit_count: int
    matching_full_tree_count: int
    canonical_base: str | None
    corrected_result_tree: str | None


@dataclass(frozen=True, slots=True)
class AcceptedTraceSummary:
    execution_count: int
    attempt_record_count: int
    success_count: int
    preparation_timeout_count: int
    controlled_failure_count: int
    candidate_execution_count: int
    cleanup_limitation_count: int
    attempt_overlap_count: int
    condition_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class StageAggregate:
    minimum: float
    median: float
    p95: float
    maximum: float


PROVENANCE_SUMMARY = ProvenanceSummary(
    result="nonunique_base",
    changed_path_count=23,
    matching_commit_count=5,
    matching_full_tree_count=5,
    canonical_base=None,
    corrected_result_tree=None,
)

ACCEPTED_TRACE_SUMMARY = AcceptedTraceSummary(
    execution_count=40,
    attempt_record_count=50,
    success_count=11,
    preparation_timeout_count=29,
    controlled_failure_count=10,
    candidate_execution_count=0,
    cleanup_limitation_count=0,
    attempt_overlap_count=0,
    condition_counts=MappingProxyType(
        {
            "quiet": 5,
            "bounded_cpu_contention": 5,
            "bounded_filesystem_contention": 5,
            "bounded_connection_churn": 5,
            "complete_gate_prelude": 10,
            "immediate_second_attempt_reacquisition": 10,
        }
    ),
)

COMPONENT_AGGREGATES: Mapping[str, StageAggregate] = MappingProxyType(
    {
        "allocated_tree_ms": StageAggregate(
            minimum=3.887,
            median=5.842,
            p95=1_721.692,
            maximum=1_833.992,
        ),
        "backing_free_ms": StageAggregate(
            minimum=0.025,
            median=0.143,
            p95=12.658,
            maximum=38.111,
        ),
        "client_rss_ms": StageAggregate(
            minimum=3.289,
            median=4.770,
            p95=52.076,
            maximum=78.971,
        ),
        "container_rss_ms": StageAggregate(
            minimum=1_041.965,
            median=1_984.661,
            p95=2_016.661,
            maximum=2_035.099,
        ),
        "concurrent_resource_group_ms": StageAggregate(
            minimum=1_042.770,
            median=1_988.482,
            p95=2_019.727,
            maximum=2_147.613,
        ),
        "connection_ms": StageAggregate(
            minimum=4.159,
            median=8.385,
            p95=68.780,
            maximum=113.644,
        ),
        "temporary_bytes_ms": StageAggregate(
            minimum=0.771,
            median=1.357,
            p95=36.554,
            maximum=42.125,
        ),
        "wal_bytes_ms": StageAggregate(
            minimum=0.204,
            median=0.362,
            p95=37.682,
            maximum=43.612,
        ),
    }
)

UNOBSERVED_CLOSED_STAGES = (
    "worker_import_duration",
    "filesystem_observation_duration",
    "baseline_assembly_duration",
    "canonical_encoding_digest_duration",
    "frame_transfer_duration",
    "parent_validation_duration",
    "cleanup_duration",
)

TEST_COV5K_AUTHORIZED = False


def decision() -> tuple[PreparationFork, Fix11Outcome]:
    """Return the only fork/outcome supported by the closed aggregates."""

    dominant = COMPONENT_AGGREGATES["concurrent_resource_group_ms"]
    if dominant.maximum > 5_000:
        return PreparationFork.C, Fix11Outcome.C
    if dominant.median > 1_800 or dominant.maximum > 1_800:
        return PreparationFork.B, Fix11Outcome.C
    return PreparationFork.A, Fix11Outcome.B
