"""Unit owner for truthful refresh phase classification and reporting."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, cast

import pytest

from common_lore_index.ops._portable_retention import PortableRefreshError
from common_lore_index.ops._refresh_outcome import classify_refresh_failure
from common_lore_index.ops.resource_view import ResourceObserver, begin
from common_lore_index.ops.resource_view._observer_reporting import finish_server
from common_lore_index.storage.errors import StorageCommitUnknownError
from common_lore_index.storage.publication_phase_witness import (
    PublicationPhase, PublicationPhaseWitness,
)


def _observer() -> ResourceObserver:
    return ResourceObserver(
        _monotonic_ns=itertools.count(0, 100).__next__,
        _process_time_ns=itertools.count(0, 10).__next__,
    )


def _cause_keyboard_interrupt(error: BaseException) -> BaseException:
    try:
        raise KeyboardInterrupt("injected interrupt")
    except KeyboardInterrupt as cause:
        error.__cause__ = cause
        return error


def test_witness_is_monotone_and_advance_never_raises() -> None:
    witness = PublicationPhaseWitness()
    for phase in PublicationPhase:
        witness.advance(phase)
        assert witness.phase is phase
    for phase in reversed(tuple(PublicationPhase)):
        witness.advance(phase)
        assert witness.phase is PublicationPhase.RETURNED

    witness.advance(cast(PublicationPhase, object()))
    assert witness.phase is PublicationPhase.RETURNED


@pytest.mark.parametrize(
    ("phase", "error", "expected_state", "expected_category"),
    (
        (
            PublicationPhase.NOT_ENTERED, ValueError("before"),
            "not_started", "worker_crash",
        ),
        (
            PublicationPhase.FINAL_TRANSACTION, ValueError("final"),
            "commit_unknown", "publication_unknown",
        ),
        (
            PublicationPhase.ROLLED_BACK, ValueError("rolled back"),
            "rolled_back", "worker_crash",
        ),
        (
            PublicationPhase.COMMIT_ATTEMPTED, ValueError("commit"),
            "commit_unknown", "publication_unknown",
        ),
        (
            PublicationPhase.RECONCILING, ValueError("reconcile"),
            "commit_unknown", "publication_unknown",
        ),
        (
            PublicationPhase.COMMITTED, ValueError("committed"),
            "commit_unknown", "publication_unknown",
        ),
        (
            PublicationPhase.RETURNED, ValueError("returned"),
            "commit_unknown", "publication_unknown",
        ),
        (
            PublicationPhase.NOT_ENTERED,
            PortableRefreshError("worker timeout", category="worker_timeout"),
            "not_started",
            "worker_timeout",
        ),
        (
            PublicationPhase.NOT_ENTERED,
            StorageCommitUnknownError("unknown"),
            "commit_unknown",
            "publication_unknown",
        ),
    ),
)
def test_classifier_covers_each_witness_boundary(
    phase: PublicationPhase,
    error: BaseException,
    expected_state: str,
    expected_category: str,
) -> None:
    assert classify_refresh_failure(phase, error) == (expected_state, expected_category)


def test_commit_unknown_with_direct_keyboard_interrupt_cause_is_cancelled() -> None:
    error = _cause_keyboard_interrupt(StorageCommitUnknownError("unknown"))
    assert classify_refresh_failure(PublicationPhase.RECONCILING, error) == (
        "commit_unknown",
        "cancelled",
    )


def test_raw_keyboard_interrupt_at_not_entered_is_not_started_and_cancelled() -> None:
    assert classify_refresh_failure(
        PublicationPhase.NOT_ENTERED, KeyboardInterrupt("before publication")
    ) == ("not_started", "cancelled")


def test_server_report_prioritizes_commit_unknown_over_cancelled() -> None:
    observer = _observer()
    begin(observer, "server_refresh", "postgresql")
    result: Any = SimpleNamespace(
        result="failure", publication_state="commit_unknown", error_category="cancelled"
    )

    finish_server(observer, result)

    assert observer.report().to_payload()["outcome"] == "commit_unknown"
