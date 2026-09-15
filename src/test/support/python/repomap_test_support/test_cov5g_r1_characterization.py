"""Public-safe TEST-COV5G-R1 protocol and aggregate support."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


FIX1_COMMIT = "46f826a321ea158e2edb1ed13f1d6ee5e560567c"
FROZEN_SOURCE_MANIFEST_DIGEST = (
    "dfb5c825b17527475ecf8a895e4a7e687ba613e4fc0ddeda83fbf70b5c5bd72d"
)
FROZEN_POLICY_DIGEST = (
    "1d1e3a73f8fd908b8c991cb4f49f67ccd0b915f1c056d6502f16eed1aa059a16"
)


@dataclass(frozen=True, slots=True)
class SourceDigest:
    """One path-bound accepted production source identity."""

    relative_path: str
    sha256: str


FROZEN_SOURCE_DIGESTS = (
    SourceDigest(
        "tools/scale14_backend_monitor.py",
        "ef99e804d92aa4304089ca84e8d2222b9ea0a201a9d29f0564129d718b991d97",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session.py",
        "35799e4f3f1abb444c769f0b15bc48ed66e782ec7e336c0e6de984e8a31e5920",
    ),
    SourceDigest(
        "tools/scale28_hybrid_startup.py",
        "f7aec398200b0f5c8420d9223fbd0e702879fb0e4dc2efd703b7d45a6580d90d",
    ),
    SourceDigest(
        "tools/scale28_observer_deadlines.py",
        "4a600a1d6d20b49c7166694b450a0a0b717201a9928ebe9438517f695e94b1ad",
    ),
    SourceDigest(
        "tools/scale28_preparation_authority.py",
        "6cac5359950a906d8cea1f3e73d42363e72314d2272f9b5ba97ab3b7596c4389",
    ),
)


def verify_source_freeze(repository_root: Path) -> tuple[SourceDigest, ...]:
    """Return the accepted source identities or reject production drift."""

    observed = tuple(
        SourceDigest(
            expected.relative_path,
            hashlib.sha256(
                (repository_root / expected.relative_path).read_bytes()
            ).hexdigest(),
        )
        for expected in FROZEN_SOURCE_DIGESTS
    )
    if observed != FROZEN_SOURCE_DIGESTS:
        raise ValueError("TEST-COV5G-R1 production source changed")
    return observed


class Condition(str, Enum):
    """One frozen configured measurement condition."""

    QUIET = "A_quiet_tcp"
    CPU = "B_cpu_contention"
    FILESYSTEM_CONTAINER = "C_filesystem_container"
    CONNECTION_CHURN = "D_connection_churn"
    CONFIGURED_SESSION = "E_configured_session"


class RequestOutcome(str, Enum):
    """Terminal request observation vocabulary."""

    SUCCESS = "request_success"
    TIMEOUT = "request_timeout"
    TRANSPORT_FAILURE = "request_transport_failure"
    CENSORED = "censored_request"


@dataclass(frozen=True, slots=True)
class MeasurementProtocol:
    """The inherited protocol frozen before either cohort."""

    cohorts: int = 2
    operations_per_condition: int = 50
    operation_sql: str = "SELECT pg_sleep(5)"
    product_trigger_ms: int = 450
    observation_ceiling_ms: int = 2_000
    percentile_rule: str = "nearest_rank"
    remove_outliers: bool = False
    remove_valid_samples: bool = False
    thresholds_ms: tuple[int, ...] = (
        40,
        80,
        120,
        160,
        200,
        250,
        500,
        1_000,
        2_000,
    )

    def __post_init__(self) -> None:
        if self.cohorts != 2 or self.operations_per_condition != 50:
            raise ValueError("TEST-COV5G-R1 counts changed")
        if self.operation_sql != "SELECT pg_sleep(5)":
            raise ValueError("TEST-COV5G-R1 operation changed")
        if (self.product_trigger_ms, self.observation_ceiling_ms) != (450, 2_000):
            raise ValueError("TEST-COV5G-R1 timing changed")
        if self.percentile_rule != "nearest_rank":
            raise ValueError("TEST-COV5G-R1 percentile rule changed")
        if self.remove_outliers or self.remove_valid_samples:
            raise ValueError("TEST-COV5G-R1 removal rule changed")

    @property
    def total_operations(self) -> int:
        """Return the exact inherited campaign size."""

        return (
            self.cohorts
            * len(Condition)
            * self.operations_per_condition
        )

    @property
    def digest(self) -> str:
        """Return a stable public protocol identity."""

        payload = {
            "cohorts": self.cohorts,
            "conditions": [condition.value for condition in Condition],
            "observation_ceiling_ms": self.observation_ceiling_ms,
            "operation_sql": self.operation_sql,
            "operations_per_condition": self.operations_per_condition,
            "percentile_rule": self.percentile_rule,
            "product_trigger_ms": self.product_trigger_ms,
            "remove_outliers": self.remove_outliers,
            "remove_valid_samples": self.remove_valid_samples,
            "thresholds_ms": self.thresholds_ms,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


PROTOCOL = MeasurementProtocol()


@dataclass(frozen=True, slots=True)
class RequestObservation:
    """One public-safe measured request and settlement projection."""

    cohort: str
    condition: Condition
    case_number: int
    request_elapsed_ms: float
    request_outcome: RequestOutcome
    operation_elapsed_ms: float
    operation_outcome: str
    request_settled: bool
    operation_settled: bool
    close_eligible: bool
    close_count: int
    backend_disappeared: bool
    cleanup_succeeded: bool
    projection_order: str

    def __post_init__(self) -> None:
        if self.cohort not in {"A", "B"}:
            raise ValueError("cohort is invalid")
        if not 1 <= self.case_number <= PROTOCOL.operations_per_condition:
            raise ValueError("case number is invalid")
        for value in (self.request_elapsed_ms, self.operation_elapsed_ms):
            if not math.isfinite(value) or value < 0:
                raise ValueError("duration is invalid")


@dataclass(frozen=True, slots=True)
class Aggregate:
    """One conservative nearest-rank aggregate."""

    sample_count: int
    successes: int
    timeouts: int
    transport_failures: int
    censored: int
    successful_request_ms: tuple[float, ...]
    operation_ms: tuple[float, ...]
    threshold_exceedances: tuple[tuple[int, int], ...]
    cleanup_failures: int

    def percentile(self, percentile: float, *, operation: bool = False) -> float:
        """Return a frozen nearest-rank percentile."""

        values = self.operation_ms if operation else self.successful_request_ms
        return nearest_rank(values, percentile)

    def rule_of_three(self, threshold_ms: int) -> float | None:
        """Return 3/n only when no observed request exceeds the threshold."""

        exceedances = dict(self.threshold_exceedances)
        if exceedances[threshold_ms] != 0:
            return None
        return 3 / self.sample_count


def nearest_rank(values: Iterable[float], percentile: float) -> float:
    """Compute a nearest-rank percentile without interpolation."""

    selected = tuple(sorted(values))
    if not selected:
        raise ValueError("percentile sample is empty")
    if not 0 < percentile <= 100:
        raise ValueError("percentile is invalid")
    rank = math.ceil(percentile / 100 * len(selected))
    return selected[rank - 1]


def aggregate(observations: Iterable[RequestObservation]) -> Aggregate:
    """Aggregate observations without removing any valid sample."""

    selected = tuple(observations)
    if not selected:
        raise ValueError("observation sample is empty")
    successful = tuple(
        item.request_elapsed_ms
        for item in selected
        if item.request_outcome is RequestOutcome.SUCCESS
    )
    operation = tuple(item.operation_elapsed_ms for item in selected)
    exceedances = tuple(
        (
            threshold,
            sum(
                item.request_outcome is not RequestOutcome.SUCCESS
                or item.request_elapsed_ms > threshold
                for item in selected
            ),
        )
        for threshold in PROTOCOL.thresholds_ms
    )
    return Aggregate(
        sample_count=len(selected),
        successes=len(successful),
        timeouts=sum(
            item.request_outcome is RequestOutcome.TIMEOUT for item in selected
        ),
        transport_failures=sum(
            item.request_outcome is RequestOutcome.TRANSPORT_FAILURE
            for item in selected
        ),
        censored=sum(
            item.request_outcome is RequestOutcome.CENSORED for item in selected
        ),
        successful_request_ms=tuple(sorted(successful)),
        operation_ms=tuple(sorted(operation)),
        threshold_exceedances=exceedances,
        cleanup_failures=sum(not item.cleanup_succeeded for item in selected),
    )
