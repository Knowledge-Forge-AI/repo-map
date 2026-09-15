"""Pure ASYNC1 coalescing, retry, reconciliation, and progress rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import random
from typing import Literal

from repomap_kg.coordinator.limits import DEFAULT_LIMITS


GenerationTuple = tuple[str, str, str, str]


@dataclass(frozen=True)
class AutomaticIntent:
    graph_id: str
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    queued_job_id: str | None = None
    running_job_id: str | None = None
    dirty: bool = False
    follow_up_pending: bool = False

    @property
    def generations(self) -> GenerationTuple:
        return (
            self.source_generation,
            self.config_generation,
            self.extractor_generation,
            self.canonicalizer_generation,
        )


@dataclass(frozen=True)
class CoalescingDecision:
    action: Literal["unchanged", "replace_queued", "follow_up", "enqueue"]
    intent: AutomaticIntent
    replaced_job_id: str | None = None
    manual_jobs_affected: int = 0


def coalesce_automatic_hint(
    current: AutomaticIntent | None,
    *,
    generations: GenerationTuple,
    graph_id: str | None = None,
    manual_pending: bool = False,
) -> CoalescingDecision:
    """Collapse hints into one desired automatic intent without touching manual work."""
    # Manual work is represented separately and is never a replacement target.
    # Retaining this input in the decision makes that invariant explicit.
    if current is None:
        if graph_id is None:
            raise ValueError("graph id is required for new automatic intent")
        intent = AutomaticIntent(graph_id, *generations, dirty=True)
        return CoalescingDecision("enqueue", intent, manual_jobs_affected=0)
    if current.generations == generations:
        return CoalescingDecision("unchanged", current)
    updated = replace(
        current,
        source_generation=generations[0],
        config_generation=generations[1],
        extractor_generation=generations[2],
        canonicalizer_generation=generations[3],
        dirty=True,
    )
    if current.running_job_id is not None:
        if current.follow_up_pending:
            return CoalescingDecision("unchanged", updated)
        return CoalescingDecision(
            "follow_up", replace(updated, follow_up_pending=True)
        )
    if current.queued_job_id is not None:
        return CoalescingDecision(
            "replace_queued",
            replace(updated, queued_job_id=None),
            replaced_job_id=current.queued_job_id,
        )
    return CoalescingDecision("enqueue", updated)


def publication_is_current(expected: GenerationTuple, actual: GenerationTuple) -> bool:
    return expected == actual


def reconcile_publication(
    publication_state: str,
    marker: Literal["matching_committed", "absent", "conflicting", "unknown"],
    cancel_requested: bool,
) -> str:
    if marker == "matching_committed":
        return "succeeded"
    if marker == "conflicting":
        return "quarantined"
    if marker == "unknown" or publication_state in {"transaction_started", "commit_unknown"}:
        return "reconciliation_required"
    if marker == "absent" and publication_state in {"not_started", "prepared", "rolled_back"}:
        return "cancelled" if cancel_requested else "queued"
    return "reconciliation_required"


_RETRYABLE = frozenset(
    {
        "transient",
        "transient_database",
        "source_unavailable",
        "storage_unavailable",
        "worker_launch",
        "worker_crash",
        "worker_timeout",
    }
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_seconds: float
    maximum_seconds: float

    def __post_init__(self) -> None:
        if self.max_attempts <= 0 or self.base_seconds <= 0 or self.maximum_seconds <= 0:
            raise ValueError("retry policy is invalid")
        if self.base_seconds > self.maximum_seconds:
            raise ValueError("retry policy is invalid")

    def may_retry(self, attempt: int, category: str, publication_state: str) -> bool:
        return (
            0 < attempt < self.max_attempts
            and category in _RETRYABLE
            and publication_state in {"not_started", "prepared", "rolled_back"}
        )

    def delay_seconds(self, attempt: int, category: str, rng: random.Random) -> float:
        if not self.may_retry(attempt, category, "rolled_back"):
            raise ValueError("retry is not permitted")
        cap = min(self.maximum_seconds, self.base_seconds * (2 ** (attempt - 1)))
        return rng.uniform(0, cap)


@dataclass(frozen=True)
class ProgressSnapshot:
    phase: str
    completed: int
    total: int | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.completed, bool)
            or not isinstance(self.completed, int)
            or self.completed < 0
            or self.completed > DEFAULT_LIMITS.max_counter
            or self.total is not None
            and (
                isinstance(self.total, bool)
                or not isinstance(self.total, int)
                or self.total < self.completed
                or self.total > DEFAULT_LIMITS.max_counter
            )
        ):
            raise ValueError("progress is invalid")


def should_persist_progress(
    previous: ProgressSnapshot,
    current: ProgressSnapshot,
    minimum_interval: timedelta,
    minimum_counter_delta: int,
) -> bool:
    if minimum_interval.total_seconds() < 0 or minimum_counter_delta < 0:
        raise ValueError("progress policy is invalid")
    if current.phase != previous.phase or current.total != previous.total:
        return True
    if current.completed - previous.completed >= minimum_counter_delta:
        return True
    return current.recorded_at - previous.recorded_at >= minimum_interval


__all__ = [
    "AutomaticIntent",
    "CoalescingDecision",
    "ProgressSnapshot",
    "RetryPolicy",
    "coalesce_automatic_hint",
    "publication_is_current",
    "reconcile_publication",
    "should_persist_progress",
]
