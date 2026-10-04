"""Shared deterministic coordinator core store and terminal-result fixtures."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._coordinator_protocols import CleanupReport, CoordinatorStore


def Claim(*, priority_class: str = "automatic") -> JobClaim:
    return JobClaim(
        "job-1", "synthetic-a", 1, "coordinator-a", 1, priority_class, "sg1:synthetic", "cg1:synthetic"
    )


class FakeStore(CoordinatorStore):
    reconcile_publication: Callable[..., str]

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.claim: JobClaim | None = Claim()
        self.state: str = "running"
        self.reconcile_result: str = "succeeded"
        self.maintenance_active: bool = False
        self.reconcile_publication = self._reconcile_publication

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        assert self.maintenance_active is False
        self.maintenance_active = True
        try:
            yield
        finally:
            self.maintenance_active = False

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        self.calls.append(("acquire", instance_id, ttl))
        return 1

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
        self.calls.append(("stop", instance_id, fencing_epoch))
        return True

    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
        return ()

    def recover_abandoned_attempts(self, instance_id: str, epoch: int, limit: int) -> int:
        self.calls.append(("recover-abandoned", instance_id, epoch, limit))
        return 0

    def claim_next(self, instance_id: str, fencing_epoch: int, lease_ttl: timedelta, *, automatic_only: bool = False) -> JobClaim | None:
        self.calls.append(("claim", instance_id, fencing_epoch, lease_ttl, automatic_only))
        if automatic_only and self.claim is not None and self.claim.priority_class == "manual":
            return None
        claim, self.claim = self.claim, None
        return claim

    def compare_and_set_state(
        self, job_id: str, *, expected_state: str, new_state: str, **kwargs: object
    ) -> bool:
        self.calls.append(("cas", expected_state, new_state, kwargs))
        return True

    def mark_reconciliation_required(
        self, claim: JobClaim, *, expected_state: str, category: str,
        diagnostic_summary: str | None = None, publication_state: str = "commit_unknown",
    ) -> bool:
        self.calls.append(("reconcile", expected_state, category))
        return True

    def request_cancellation(self, job_id: str) -> str:
        self.calls.append(("cancel", job_id))
        if self.state in {"succeeded", "failed", "cancelled", "quarantined"}:
            raise ValueError("job cannot be cancelled")
        self.state = "cancel_requested"
        return "cancel_requested"

    def heartbeat_singleton(self, instance_id: str, fencing_epoch: int, ttl: timedelta) -> bool:
        self.calls.append(("heartbeat", instance_id, fencing_epoch, ttl))
        return True

    def release_graph_lease(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("release", args, kwargs))
        return True

    def mark_attempt_terminated(
        self, claim: JobClaim, *, process_cleanup_proved: bool, reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None, diagnostic_summary: str | None = None,
    ) -> bool:
        assert process_cleanup_proved is True
        self.calls.append(("terminated", claim.job_id))
        return True

    def cleanup_terminal(
        self, minimum_age: timedelta, *, limit: int, dry_run: bool,
        publication_retirer: Callable[[object], object] | None = None,
    ) -> CleanupReport:
        self.calls.append(("cleanup", minimum_age, limit, dry_run))
        return CleanupReport(deleted_job_ids=(), residuals=())

    def status(self, job_id: str) -> SimpleNamespace:
        return SimpleNamespace(state=self.state)

    def _reconcile_publication(self, claim: JobClaim, *, reconciler_instance_id: str | None = None, reconciler_epoch: int | None = None, **kwargs: object) -> str:
        self.calls.append(("reconcile-publication", claim.job_id))
        if self.reconcile_result == "succeeded":
            self.state = "succeeded"
            self.calls.append(("release", (), {}))
        return self.reconcile_result

    def schedule_retry(self, claim: JobClaim, **kwargs: object) -> bool:
        self.calls.append(("retry", claim.job_id, kwargs))
        return True

    def record_publication_marker(self, claim: JobClaim, **marker: object) -> bool:
        self.calls.append(("marker", claim.job_id, marker))
        return True


def terminal(status="succeeded", publication="committed"):
    return {
        "message_type": "result",
        "status": status,
        "publication_state": publication,
        "phase": "complete",
        "_termination_proved": True,
        "latest_run_identity": "run-public-1",
        "source_generation": "sg1:synthetic",
        "config_generation": "cg1:synthetic",
        "extractor_generation": "eg1:synthetic",
        "canonicalizer_generation": "kg1:synthetic",
    }


