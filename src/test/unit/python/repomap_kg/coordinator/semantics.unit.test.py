from datetime import datetime, timedelta, timezone
import random
from typing import cast

import pytest

from repomap_kg.coordinator.semantics import (
    AutomaticIntent,
    ProgressSnapshot,
    RetryPolicy,
    coalesce_automatic_hint,
    publication_is_current,
    reconcile_publication,
    should_persist_progress,
)


GEN_A = ("sg1:aaa", "cg1:aaa", "extractor-a", "canonical-a")
GEN_B = ("sg1:bbb", "cg1:bbb", "extractor-b", "canonical-b")


def test_duplicate_hints_do_not_grow_automatic_intent():
    current = AutomaticIntent("synthetic-a", *GEN_A, queued_job_id="job-a")
    decision = coalesce_automatic_hint(current, generations=GEN_A)
    assert decision.action == "unchanged"
    assert decision.intent == current


def test_queued_automatic_work_is_replaced_once_for_new_generations():
    current = AutomaticIntent("synthetic-a", *GEN_A, queued_job_id="job-a")
    decision = coalesce_automatic_hint(current, generations=GEN_B)
    assert decision.action == "replace_queued"
    assert decision.replaced_job_id == "job-a"
    assert decision.intent.dirty is True
    assert decision.intent.queued_job_id is None


def test_running_automatic_work_records_one_follow_up_without_superseding_manual():
    current = AutomaticIntent(
        "synthetic-a", *GEN_A, running_job_id="job-running", follow_up_pending=False
    )
    first = coalesce_automatic_hint(current, generations=GEN_B, manual_pending=True)
    second = coalesce_automatic_hint(first.intent, generations=GEN_B, manual_pending=True)
    assert first.action == "follow_up"
    assert first.intent.follow_up_pending is True
    assert second.action == "unchanged"
    assert first.manual_jobs_affected == 0


@pytest.mark.parametrize("index", range(4))
def test_every_generation_mismatch_blocks_publication(index):
    actual = list(GEN_A)
    actual[index] = GEN_B[index]
    assert publication_is_current(GEN_A, cast(tuple[str, str, str, str], tuple(actual))) is False


def test_matching_generations_allow_publication():
    assert publication_is_current(GEN_A, GEN_A) is True


@pytest.mark.parametrize(
    ("publication,marker,cancel_requested,expected"),
    [
        ("commit_unknown", "matching_committed", False, "succeeded"),
        ("commit_unknown", "conflicting", False, "quarantined"),
        ("commit_unknown", "unknown", False, "reconciliation_required"),
        ("rolled_back", "absent", False, "queued"),
        ("rolled_back", "absent", True, "cancelled"),
        ("committed", "matching_committed", True, "succeeded"),
    ],
)
def test_reconciliation_never_guesses_from_process_exit(
    publication, marker, cancel_requested, expected
):
    assert reconcile_publication(publication, marker, cancel_requested) == expected


def test_retry_policy_uses_bounded_exponential_full_jitter():
    policy = RetryPolicy(max_attempts=4, base_seconds=2, maximum_seconds=10)
    rng = random.Random(7)
    delays = [policy.delay_seconds(attempt, "transient", rng) for attempt in (1, 2, 3)]
    assert all(0 <= delay <= cap for delay, cap in zip(delays, (2, 4, 8)))
    assert policy.may_retry(4, "transient", "rolled_back") is False


@pytest.mark.parametrize(
    "category",
    [
        "authorization", "privacy", "configuration", "protocol",
        "generation_changed", "cancelled", "superseded", "publication_unknown",
        "permanent", "internal", "unknown-category",
    ],
)
def test_retry_policy_rejects_nonretryable_categories(category):
    policy = RetryPolicy(max_attempts=4, base_seconds=2, maximum_seconds=10)
    assert policy.may_retry(1, category, "rolled_back") is False


def test_retry_policy_rejects_unknown_publication():
    policy = RetryPolicy(max_attempts=4, base_seconds=2, maximum_seconds=10)
    assert policy.may_retry(1, "transient", "commit_unknown") is False


def test_progress_writes_only_for_meaningful_delta_or_interval():
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    previous = ProgressSnapshot("discovery", 10, None, now)
    unchanged = ProgressSnapshot("discovery", 10, None, now + timedelta(seconds=1))
    advanced = ProgressSnapshot("discovery", 11, None, now + timedelta(seconds=1))
    elapsed = ProgressSnapshot("discovery", 10, None, now + timedelta(seconds=6))
    assert should_persist_progress(previous, unchanged, timedelta(seconds=5), 1) is False
    assert should_persist_progress(previous, advanced, timedelta(seconds=5), 1) is True
    assert should_persist_progress(previous, elapsed, timedelta(seconds=5), 1) is True


def test_progress_rejects_invented_totals_and_unbounded_counters():
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="progress"):
        ProgressSnapshot("discovery", 2, 1, now)
    with pytest.raises(ValueError, match="progress"):
        ProgressSnapshot("discovery", 2**100, None, now)
