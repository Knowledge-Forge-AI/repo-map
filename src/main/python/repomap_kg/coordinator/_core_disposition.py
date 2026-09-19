"""Terminal disposition and reconciliation helpers for SyntheticCoordinator."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import random
import threading

from repomap_kg.coordinator._coordinator_protocols import (
    CoordinatorStore,
    PublicationReader,
    _Claim,
)
from repomap_kg.coordinator.semantics import RetryPolicy


class CoreDispositionMixin:
    """Provide terminal outcome handling, retries, and reconciliation."""

    _store: CoordinatorStore
    _instance_id: str
    _publication_reader: PublicationReader | None
    _retry_policy: RetryPolicy

    def _require_started(self) -> int:
        raise NotImplementedError

    def _transition(
        self,
        claim: _Claim,
        expected_state: str,
        new_state: str,
        publication_state: str | None = None,
        error_category: str | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        raise NotImplementedError

    def _active_expected_state(
        self, claim: _Claim, cancel_event: threading.Event
    ) -> str:
        status_reader = getattr(self._store, "status", None)
        if status_reader is not None:
            if status_reader(claim.job_id).state == "cancel_requested":
                cancel_event.set()
        return "cancel_requested" if cancel_event.is_set() else "running"

    def _finish_prestart_cancel(self, claim: _Claim) -> str:
        status_reader = getattr(self._store, "status", None)
        if status_reader is None:
            return "ownership_lost"
        if status_reader(claim.job_id).state != "cancel_requested":
            return "ownership_lost"
        if not self._transition(claim, "cancel_requested", "cancelling"):
            return "ownership_lost"
        if not self._transition(
            claim,
            "cancelling",
            "cancelled",
            publication_state="not_started",
            error_category="cancelled",
        ):
            return "ownership_lost"
        self._release_terminal_lease(claim)
        return "cancelled"

    def _release_terminal_lease(self, claim: _Claim) -> None:
        epoch = self._require_started()
        if not self._store.release_graph_lease(
            claim.graph_id,
            claim.job_id,
            claim.attempt,
            claim.instance_id,
            claim.fencing_epoch,
            reconciler_instance_id=self._instance_id,
            reconciler_epoch=epoch,
        ):
            raise RuntimeError("terminal graph lease release failed")

    def _record_marker_if_available(
        self, claim: _Claim, terminal: Mapping[str, object]
    ) -> bool:
        recorder = getattr(self._store, "record_publication_marker", None)
        required = (
            "latest_run_identity",
            "source_generation",
            "config_generation",
            "extractor_generation",
            "canonicalizer_generation",
        )
        if recorder is None or any(terminal.get(field) is None for field in required):
            return False
        recorder(
            claim,
            run_identity=terminal["latest_run_identity"],
            source_generation=terminal["source_generation"],
            config_generation=terminal["config_generation"],
            extractor_generation=terminal["extractor_generation"],
            canonicalizer_generation=terminal["canonicalizer_generation"],
            outcome="committed",
        )
        return True

    def _reconcile_current(self, claim: _Claim) -> str:
        if self._publication_reader is not None:
            try:
                marker = self._publication_reader(claim)
            except (OSError, RuntimeError, ValueError):
                marker = None
            if marker is not None:
                try:
                    self._record_marker_if_available(claim, marker)
                except ValueError:
                    pass
        return self._store.reconcile_publication(
            claim,
            reconciler_instance_id=self._instance_id,
            reconciler_epoch=self._require_started(),
        )

    def _dispose_terminal(
        self, claim: _Claim, expected: str, terminal: dict[str, object]
    ) -> str:
        termination_proved = terminal.pop("_termination_proved", False) is True
        supervised_category = terminal.pop(
            "_error_category", "publication_unknown"
        )
        raw_diag = terminal.pop("_diagnostic_summary", None)
        diagnostic_summary = str(raw_diag) if isinstance(raw_diag, str) else None
        publication = terminal.get("publication_state")
        status = terminal.get("status")
        if status == "succeeded" and publication == "committed":
            try:
                marker_recorded = self._record_marker_if_available(claim, terminal)
            except ValueError:
                marker_recorded = True
            if not marker_recorded:
                if not self._store.mark_reconciliation_required(
                    claim,
                    expected_state=expected,
                    category="protocol",
                    diagnostic_summary=diagnostic_summary,
                ):
                    return "ownership_lost"
                if not termination_proved:
                    return "reconciliation_required"
                if not self._store.mark_attempt_terminated(
                    claim, process_cleanup_proved=True
                ):
                    return "ownership_lost"
                return self._reconcile_current(claim)
            if not self._store.mark_reconciliation_required(
                claim,
                expected_state=expected,
                category="publication_unknown",
                diagnostic_summary=diagnostic_summary,
            ):
                return "ownership_lost"
            if termination_proved and not self._store.mark_attempt_terminated(
                claim, process_cleanup_proved=True
            ):
                return "ownership_lost"
            return self._reconcile_current(claim)
        if not termination_proved:
            if not self._store.mark_reconciliation_required(
                claim,
                expected_state=expected,
                category="worker_crash",
                diagnostic_summary=diagnostic_summary,
            ):
                return "ownership_lost"
            return "reconciliation_required"
        if publication in {"transaction_started", "commit_unknown"}:
            if not self._store.mark_reconciliation_required(
                claim,
                expected_state=expected,
                category=str(supervised_category),
                diagnostic_summary=diagnostic_summary,
            ):
                return "ownership_lost"
            if termination_proved and not self._store.mark_attempt_terminated(
                claim, process_cleanup_proved=True
            ):
                return "ownership_lost"
            if termination_proved and self._publication_reader is not None:
                return self._reconcile_current(claim)
            return "reconciliation_required"
        if status == "failed" and publication in {"not_started", "rolled_back"}:
            category = str(terminal.get("error_category") or "permanent")
            if expected == "cancel_requested":
                if not self._transition(
                    claim, "cancel_requested", "cancelling"
                ):
                    return "ownership_lost"
                if self._transition(
                    claim,
                    "cancelling",
                    "failed",
                    publication_state=str(publication),
                    error_category="cancel_failed",
                    diagnostic_summary=diagnostic_summary,
                ):
                    self._release_terminal_lease(claim)
                    return "failed"
                return "ownership_lost"
            if self._retry_policy.may_retry(claim.attempt, category, str(publication)):
                delay = self._retry_policy.delay_seconds(
                    claim.attempt, category, random.SystemRandom()
                )
                if self._store.schedule_retry(
                    claim,
                    expected_state="running",
                    delay=timedelta(seconds=delay),
                    category=category,
                    diagnostic_summary=diagnostic_summary,
                ):
                    return "queued"
            if self._transition(
                claim,
                "running",
                "failed",
                publication_state=str(publication),
                error_category=category,
                diagnostic_summary=diagnostic_summary,
            ):
                self._release_terminal_lease(claim)
                return "failed"
            return "ownership_lost"
        if (
            status == "cancelled"
            and expected == "cancel_requested"
            and publication in {"not_started", "prepared", "rolled_back"}
        ):
            if not self._transition(
                claim, "cancel_requested", "cancelling"
            ):
                return "ownership_lost"
            if self._transition(
                claim,
                "cancelling",
                "cancelled",
                publication_state=str(publication),
                error_category="cancelled",
            ):
                self._release_terminal_lease(claim)
                return "cancelled"
            return "ownership_lost"
        effective_diagnostic = diagnostic_summary
        if supervised_category == "worker_crash" and effective_diagnostic is None:
            effective_diagnostic = "worker_crash:unproved_termination"
        if not self._store.mark_reconciliation_required(
            claim,
            expected_state=expected,
            category=str(supervised_category),
            diagnostic_summary=effective_diagnostic,
        ):
            return "ownership_lost"
        if termination_proved and not self._store.mark_attempt_terminated(
            claim,
            process_cleanup_proved=True,
            reconciler_instance_id=self._instance_id,
            reconciler_epoch=self._require_started(),
            diagnostic_summary=effective_diagnostic,
        ):
            return "ownership_lost"
        return self._reconcile_current(claim)
