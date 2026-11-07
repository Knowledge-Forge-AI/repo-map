"""Durable CAS refusal cannot authorize terminal release, retirement, or retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

from common_lore_index.coordinator._control_types import JobClaim
from common_lore_index.coordinator.core import SyntheticCoordinator
from repomap_test_support.coordinator_core_fakes import FakeStore, terminal
from repomap_test_support.run25_portable_workflows import build_clean_explicit_pythonpath
from runner_coverage_execution import prepare_child_coverage_environment


class RefusalStore(FakeStore):
    def __init__(self, refused: str) -> None:
        super().__init__()
        self.refused = refused
        self.transitions: list[tuple[str, str]] = []
        self.reconciliation: list[str] = []
        self.termination_calls = 0
        self.retry_calls = 0

    def compare_and_set_state(self, job_id: str, *, expected_state: str, new_state: str, **kwargs: object) -> bool:
        self.transitions.append((expected_state, new_state))
        if new_state == self.refused:
            return False
        return super().compare_and_set_state(job_id, expected_state=expected_state, new_state=new_state, **kwargs)

    def mark_reconciliation_required(self, claim: JobClaim, *, expected_state: str, category: str,
                                     diagnostic_summary: str | None = None, publication_state: str = "commit_unknown") -> bool:
        self.reconciliation.append(category)
        return self.refused != "reconciliation"

    def mark_attempt_terminated(self, claim: JobClaim, **kwargs: object) -> bool:
        self.termination_calls += 1
        return self.refused != "termination"

    def schedule_retry(self, claim: JobClaim, **kwargs: object) -> bool:
        self.retry_calls += 1
        return self.refused != "retry"


@pytest.mark.parametrize("cancel_status,refused", [
    ("failed", "cancelling"), ("failed", "failed"),
    ("cancelled", "cancelling"), ("cancelled", "cancelled"),
])
def test_cancellation_terminal_cas_loss_retains_graph_lease_and_evidence(cancel_status, refused):
    store = RefusalStore(refused)
    store.state = "cancel_requested"
    retired: list[object] = []
    result = {"status": cancel_status, "publication_state": "rolled_back", "_termination_proved": True}
    coordinator = SyntheticCoordinator(store, "owner-fixture", lambda *_: result, publication_retirer=retired.append)
    coordinator.startup(lambda: None)
    try:
        assert coordinator.run_once() == "ownership_lost"
        assert not retired
        assert all(call[0] != "release" for call in store.calls)
        assert ("cancel_requested", "cancelling") in store.transitions
        if refused != "cancelling":
            assert ("cancelling", cancel_status) in store.transitions
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("kind,expected_category", [
    ("missing-marker", "protocol"), ("committed", "publication_unknown"),
    ("unproved-failure", "worker_crash"), ("ambiguous", "publication_unknown"),
    ("unsolicited-cancellation", "publication_unknown"),
])
def test_reconciliation_cas_refusal_prevents_fencing_and_retirement(kind, expected_category):
    store = RefusalStore("reconciliation")
    retired: list[object] = []
    result = terminal()
    if kind == "missing-marker":
        result.pop("source_generation")
    elif kind == "unproved-failure":
        result.update(status="failed", publication_state="rolled_back", _termination_proved=False)
    elif kind == "ambiguous":
        result.update(status="failed", publication_state="commit_unknown")
    elif kind == "unsolicited-cancellation":
        result.update(status="cancelled", publication_state="rolled_back")
    coordinator = SyntheticCoordinator(store, "owner-fixture", lambda *_: result, publication_retirer=retired.append)
    coordinator.startup(lambda: None)
    try:
        assert coordinator.run_once() == "ownership_lost"
        assert store.reconciliation == [expected_category]
        assert store.termination_calls == 0
        assert not retired
        assert all(call[0] != "release" for call in store.calls)
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("kind", ["committed", "missing-marker", "ambiguous", "unsolicited-cancellation"])
def test_lost_termination_record_cannot_settle_reconciliation(kind):
    store = RefusalStore("termination")
    result = terminal()
    if kind == "missing-marker":
        result.pop("source_generation")
    elif kind == "ambiguous":
        result.update(status="failed", publication_state="commit_unknown")
    elif kind == "unsolicited-cancellation":
        result.update(status="cancelled", publication_state="rolled_back")
    retired: list[object] = []
    coordinator = SyntheticCoordinator(store, "owner-fixture", lambda *_: result, publication_retirer=retired.append)
    coordinator.startup(lambda: None)
    try:
        assert coordinator.run_once() == "ownership_lost"
        assert store.termination_calls == 1
        assert not retired
        assert all(call[0] not in {"release", "reconcile-publication"} for call in store.calls)
    finally:
        coordinator.shutdown()


def test_refused_retry_settles_once_as_failure_without_reporting_queued():
    store = RefusalStore("retry")
    result = {"status": "failed", "publication_state": "rolled_back", "error_category": "transient", "_termination_proved": True}
    retired: list[object] = []
    coordinator = SyntheticCoordinator(store, "owner-fixture", lambda *_: result, publication_retirer=retired.append)
    coordinator.startup(lambda: None)
    try:
        assert coordinator.run_once() == "failed"
        assert store.retry_calls == 1
        assert ("running", "failed") in store.transitions
        assert len(retired) == 1
        assert any(call[0] == "release" for call in store.calls)
    finally:
        coordinator.shutdown()


def test_retirement_error_settles_terminal_disposal_without_deadlock() -> None:
    """A bounded control child proves residual recording and lease release settle."""
    repo_root = Path(__file__).resolve().parents[6]
    environment = prepare_child_coverage_environment(
        base_env={**os.environ, "PYTHONPATH": build_clean_explicit_pythonpath(repo_root)},
        family="unmeasured",
        extra_env={"PYTHONNOUSERSITE": "1"},
    )
    script = dedent("""
        import json
        from common_lore_index.coordinator.core import SyntheticCoordinator
        from repomap_test_support.coordinator_core_fakes import FakeStore

        store = FakeStore()
        def retire(_claim):
            raise FileNotFoundError("synthetic retirement failure")
        terminal = {
            "status": "failed", "publication_state": "rolled_back",
            "error_category": "permanent", "_termination_proved": True,
        }
        coordinator = SyntheticCoordinator(
            store, "retirement-fixture", lambda *_: dict(terminal),
            publication_retirer=retire,
        )
        coordinator.startup(lambda: None)
        try:
            outcome = coordinator.run_once()
            residuals = coordinator.residual_evidence
        finally:
            coordinator.shutdown()
        print(json.dumps({
            "outcome": outcome,
            "residuals": list(residuals),
            "released": any(call[0] == "release" for call in store.calls),
        }))
    """)
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=repo_root, env=environment,
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, "retirement control child failed"
    assert json.loads(completed.stdout) == {
        "outcome": "failed", "residuals": ["job-1:1:not_found"], "released": True,
    }
