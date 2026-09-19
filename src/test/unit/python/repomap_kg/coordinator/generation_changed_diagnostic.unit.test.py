from __future__ import annotations

from unittest.mock import MagicMock

from repomap_kg.coordinator._refresh_generation import (
    generation_changed_terminal,
    psql_configuration_terminal,
)
from repomap_kg.coordinator._core_disposition import CoreDispositionMixin


class SimpleClaim:
    def __init__(
        self,
        job_id: str,
        attempt: int,
        graph_id: str,
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
    ) -> None:
        self.job_id = job_id
        self.attempt = attempt
        self.graph_id = graph_id
        self.source_generation = source_generation
        self.config_generation = config_generation
        self.extractor_generation = extractor_generation
        self.canonicalizer_generation = canonicalizer_generation


class DummyCoordinator(CoreDispositionMixin):
    def __init__(self, store, retry_policy, instance_id="coord-test"):
        self._store = store
        self._retry_policy = retry_policy
        self._instance_id = instance_id
        self._publication_reader = None
        self.transitions = []

    def _require_started(self) -> int:
        return 1

    def _transition(
        self,
        claim,
        expected_state,
        new_state,
        publication_state=None,
        error_category=None,
        diagnostic_summary=None,
    ) -> bool:
        self.transitions.append({
            "claim": claim,
            "expected_state": expected_state,
            "new_state": new_state,
            "publication_state": publication_state,
            "error_category": error_category,
            "diagnostic_summary": diagnostic_summary,
        })
        return True

    def _release_terminal_lease(self, claim):
        pass


def test_generation_changed_terminal_carries_typed_diagnostic_summary() -> None:
    claim = SimpleClaim(
        job_id="test-job-1",
        attempt=1,
        graph_id="test-graph",
        source_generation="sg1",
        config_generation="cg1",
        extractor_generation="eg1",
        canonicalizer_generation="kg1",
    )
    terminal = generation_changed_terminal(claim)
    assert terminal["status"] == "failed"
    assert terminal["publication_state"] == "not_started"
    assert terminal["error_category"] == "generation_changed"
    assert terminal["_diagnostic_summary"] == "generation_changed:identity_mismatch"
    assert terminal["diagnostics"] == ["generation_changed:identity_mismatch"]


def test_psql_configuration_terminal_carries_typed_diagnostic_summary() -> None:
    claim = SimpleClaim(
        job_id="test-job-2",
        attempt=1,
        graph_id="test-graph",
        source_generation="sg1",
        config_generation="cg1",
        extractor_generation="eg1",
        canonicalizer_generation="kg1",
    )
    terminal = psql_configuration_terminal(claim)
    assert terminal["status"] == "failed"
    assert terminal["publication_state"] == "not_started"
    assert terminal["error_category"] == "configuration"
    assert terminal["_diagnostic_summary"] == "psql_authority_invalid"
    assert terminal["diagnostics"] == ["psql_authority_invalid"]


def test_dispose_terminal_passes_diagnostic_summary_to_transition() -> None:
    store = MagicMock()
    retry_policy = MagicMock()
    retry_policy.may_retry.return_value = False
    coord = DummyCoordinator(store=store, retry_policy=retry_policy)
    claim = MagicMock()
    claim.attempt = 1
    claim.job_id = "job-1"
    terminal = dict(
        generation_changed_terminal(
            SimpleClaim("job-1", 1, "g1", "s1", "c1", "e1", "k1")
        )
    )
    result = coord._dispose_terminal(claim, "running", terminal)
    assert result == "failed"
    assert len(coord.transitions) == 1
    t = coord.transitions[0]
    assert t["diagnostic_summary"] == "generation_changed:identity_mismatch"
    assert t["error_category"] == "generation_changed"
    assert t["publication_state"] == "not_started"


def test_dispose_terminal_passes_diagnostic_to_reconciliation_and_termination() -> None:
    store = MagicMock()
    store.mark_reconciliation_required.return_value = True
    store.mark_attempt_terminated.return_value = True
    store.reconcile_publication.return_value = "reconciled"
    retry_policy = MagicMock()
    coord = DummyCoordinator(store=store, retry_policy=retry_policy, instance_id="coord-42")
    claim = MagicMock()
    claim.attempt = 1
    claim.job_id = "job-2"

    terminal = {
        "status": "other",
        "publication_state": "prepared",
        "_termination_proved": True,
        "_error_category": "custom_category",
        "_diagnostic_summary": "custom:diagnostic_details",
    }
    result = coord._dispose_terminal(claim, "running", terminal)
    assert result == "reconciled"
    store.mark_reconciliation_required.assert_called_once_with(
        claim,
        expected_state="running",
        category="custom_category",
        diagnostic_summary="custom:diagnostic_details",
    )
    store.mark_attempt_terminated.assert_called_once_with(
        claim,
        process_cleanup_proved=True,
        reconciler_instance_id="coord-42",
        reconciler_epoch=1,
        diagnostic_summary="custom:diagnostic_details",
    )


def test_dispose_terminal_worker_crash_diagnostic_fallback() -> None:
    store = MagicMock()
    store.mark_reconciliation_required.return_value = True
    store.mark_attempt_terminated.return_value = True
    store.reconcile_publication.return_value = "reconciled"
    retry_policy = MagicMock()
    coord = DummyCoordinator(store=store, retry_policy=retry_policy, instance_id="coord-42")
    claim = MagicMock()
    claim.attempt = 1
    claim.job_id = "job-3"

    terminal = {
        "status": "other",
        "publication_state": "prepared",
        "_termination_proved": True,
        "_error_category": "worker_crash",
    }
    result = coord._dispose_terminal(claim, "running", terminal)
    assert result == "reconciled"
    store.mark_reconciliation_required.assert_called_once_with(
        claim,
        expected_state="running",
        category="worker_crash",
        diagnostic_summary="worker_crash:unproved_termination",
    )
    store.mark_attempt_terminated.assert_called_once_with(
        claim,
        process_cleanup_proved=True,
        reconciler_instance_id="coord-42",
        reconciler_epoch=1,
        diagnostic_summary="worker_crash:unproved_termination",
    )
