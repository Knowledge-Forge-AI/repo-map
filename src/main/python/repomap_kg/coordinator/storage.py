"""Public facade for the isolated ASYNC2 PostgreSQL control store."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta

import psycopg

from repomap_kg.coordinator import (
    _control_coalescing as coalescing, _control_listing as listing,
    _control_maintenance as maintenance, _control_ownership as ownership,
    _control_polling as polling, _control_reconciliation as reconciliation,
    _control_schema as schema, _control_startup as startup,
    _control_state as state, _control_submission as submission,
)
from repomap_kg.coordinator._control_types import (
    ConnectionFactory, ControlSchemaError, ControlStoreError, JobClaim,
    JobListPage, JobStatus, SingletonActiveError, SubmissionResult,
)
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.limits import DEFAULT_LIMITS, HARD_MAX_LIMITS, CoordinatorLimits
from repomap_kg.runtime import maintenance as runtime_maintenance


CONTROL_SCHEMA_VERSION = schema.CONTROL_SCHEMA_VERSION
CONTROL_TABLES = schema.CONTROL_TABLES


class ControlStore:
    """Transactional access to the dedicated coordinator control database."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        limits: CoordinatorLimits = DEFAULT_LIMITS,
    ) -> None:
        limits.validate(hard_maxima=HARD_MAX_LIMITS)
        self._connect = connection_factory
        self._limits = limits

    def initialize_schema(self, *, migration_sql: str | None = None) -> None:
        schema.initialize_schema(self._connect, migration_sql=migration_sql)

    def check_schema_version(self) -> int:
        return schema.check_schema_version(self._connect)

    def schema_readiness(self) -> schema.ControlSchemaReadiness:
        return schema.control_schema_readiness(self._connect)

    def schema_manifest(self) -> tuple[str, ...]:
        return schema.control_schema_manifest(self._connect)

    def adopt_preledger_schema(
        self,
        *,
        expected_manifest: tuple[str, ...],
        backup_verified: bool,
    ) -> None:
        schema.adopt_preledger_schema(
            self._connect,
            expected_manifest=expected_manifest,
            backup_verified=backup_verified,
        )

    def maintenance_activity(self) -> AbstractContextManager[None]:
        return runtime_maintenance.maintenance_activity(self._connect)

    def maintenance_window(self) -> AbstractContextManager[None]:
        return runtime_maintenance.maintenance_window(self._connect)

    def maintenance_ready(self) -> bool:
        return runtime_maintenance.maintenance_ready(self._connect)

    def list_recent_jobs(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> JobListPage:
        return listing.list_recent_jobs(
            self._connect,
            limit=limit,
            graph_id=graph_id,
            cursor=cursor,
        )

    def submit(
        self,
        request: JobRequest,
        *,
        requester: str = "local",
    ) -> SubmissionResult:
        return submission.submit(
            self._connect, request, requester=requester, limits=self._limits
        )

    def coalesce_automatic(
        self,
        request: JobRequest,
        *,
        requester: str = "watcher",
    ) -> SubmissionResult:
        return coalescing.coalesce_automatic(
            self._connect,
            request,
            requester=requester,
            limits=self._limits,
        )

    def record_reconciliation_current(
        self,
        graph_id: str,
        generations: tuple[str, str, str, str],
        *,
        next_reconcile_seconds: float,
    ) -> bool:
        return polling.record_current(
            self._connect,
            graph_id,
            generations,
            next_reconcile_seconds=next_reconcile_seconds,
        )

    def record_reconciliation_condition(
        self,
        graph_id: str,
        category: str,
        *,
        next_reconcile_seconds: float,
    ) -> bool:
        return polling.record_condition(
            self._connect,
            graph_id,
            category,
            next_reconcile_seconds=next_reconcile_seconds,
        )

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        return ownership.acquire_singleton(self._connect, instance_id, ttl)

    def heartbeat_singleton(
        self, instance_id: str, fencing_epoch: int, ttl: timedelta
    ) -> bool:
        return ownership.heartbeat_singleton(
            self._connect, instance_id, fencing_epoch, ttl
        )

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
        return ownership.stop_singleton(
            self._connect, instance_id, fencing_epoch
        )

    def claim_next(
        self,
        instance_id: str,
        fencing_epoch: int,
        lease_ttl: timedelta,
        *,
        automatic_only: bool = False,
    ) -> JobClaim | None:
        seconds = ownership.positive_seconds(lease_ttl)
        for _ in range(3):
            try:
                return self._claim_once(
                    instance_id, fencing_epoch, seconds,
                    automatic_only=automatic_only,
                )
            except psycopg.errors.UniqueViolation as error:
                if not ownership.is_expected_graph_lease_race(error):
                    raise ControlStoreError(
                        "unexpected control-store uniqueness violation"
                    ) from None
        return None

    def _claim_once(
        self,
        instance_id: str,
        fencing_epoch: int,
        lease_seconds: float,
        *,
        automatic_only: bool = False,
    ) -> JobClaim | None:
        return ownership.claim_once(
            self._connect,
            instance_id,
            fencing_epoch,
            lease_seconds,
            max_attempts=self._limits.max_retry_attempts,
            automatic_only=automatic_only,
        )

    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
        """Return a stable bounded startup-reconciliation working set."""

        return startup.reconciliation_claims(self._connect, limit)

    def recover_abandoned_attempts(
        self, instance_id: str, fencing_epoch: int, limit: int
    ) -> int:
        """Fence nonterminal attempts owned by a superseded singleton."""

        return startup.recover_abandoned_attempts(
            self._connect, instance_id, fencing_epoch, limit
        )

    def compare_and_set_state(
        self,
        job_id: str,
        *,
        expected_state: str,
        new_state: str,
        attempt: int,
        instance_id: str,
        fencing_epoch: int,
        publication_state: str | None = None,
        error_category: str | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        return state.compare_and_set_state(
            self._connect,
            job_id,
            expected_state=expected_state,
            new_state=new_state,
            attempt=attempt,
            instance_id=instance_id,
            fencing_epoch=fencing_epoch,
            publication_state=publication_state,
            error_category=error_category,
            diagnostic_summary=diagnostic_summary,
        )

    def release_graph_lease(
        self,
        graph_id: str,
        job_id: str,
        attempt: int,
        owner_instance_id: str,
        owner_epoch: int,
        *,
        reconciler_instance_id: str,
        reconciler_epoch: int,
    ) -> bool:
        return ownership.release_graph_lease(
            self._connect,
            graph_id,
            job_id,
            attempt,
            owner_instance_id,
            owner_epoch,
            reconciler_instance_id=reconciler_instance_id,
            reconciler_epoch=reconciler_epoch,
        )

    def heartbeat_attempt(
        self,
        claim: JobClaim,
        lease_ttl: timedelta,
        *,
        phase: str | None = None,
        completed: int | None = None,
        total: int | None = None,
    ) -> bool:
        return state.heartbeat_attempt(
            self._connect,
            claim,
            lease_ttl,
            phase=phase,
            completed=completed,
            total=total,
            progress_counter_delta=self._limits.progress_counter_delta,
            progress_min_interval_seconds=self._limits.progress_min_interval_seconds,
            max_counter=self._limits.max_counter,
        )

    def request_cancellation(self, job_id: str) -> str:
        return state.request_cancellation(self._connect, job_id)

    def mark_reconciliation_required(
        self, claim: JobClaim, *, expected_state: str, category: str,
        diagnostic_summary: str | None = None,
    ) -> bool:
        return self.compare_and_set_state(
            claim.job_id,
            expected_state=expected_state, new_state="reconciliation_required",
            attempt=claim.attempt, instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch, publication_state="commit_unknown",
            error_category=category, diagnostic_summary=diagnostic_summary,
        )

    def mark_quarantined(
        self, claim: JobClaim, *, expected_state: str, category: str
    ) -> bool:
        return self.compare_and_set_state(
            claim.job_id,
            expected_state=expected_state, new_state="quarantined",
            attempt=claim.attempt, instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch, error_category=category,
        )

    def mark_attempt_terminated(
        self, claim: JobClaim, *, process_cleanup_proved: bool,
        reconciler_instance_id: str | None = None, reconciler_epoch: int | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        return state.mark_attempt_terminated(
            self._connect, claim, process_cleanup_proved=process_cleanup_proved,
            reconciler_instance_id=reconciler_instance_id or claim.instance_id,
            reconciler_epoch=reconciler_epoch if reconciler_epoch is not None else claim.fencing_epoch,
            diagnostic_summary=diagnostic_summary,
        )

    def reconcile_publication(
        self, claim: JobClaim, *,
        reconciler_instance_id: str | None = None, reconciler_epoch: int | None = None,
    ) -> str:
        return reconciliation.reconcile_publication(
            self._connect, claim, max_attempts=self._limits.max_retry_attempts,
            reconciler_instance_id=reconciler_instance_id or claim.instance_id,
            reconciler_epoch=reconciler_epoch if reconciler_epoch is not None else claim.fencing_epoch,
        )

    def schedule_retry(
        self, claim: JobClaim, *, expected_state: str, delay: timedelta,
        category: str, diagnostic_summary: str | None = None,
    ) -> bool:
        return state.schedule_retry(
            self._connect, claim, expected_state=expected_state, delay=delay,
            category=category, max_attempts=self._limits.max_retry_attempts,
            diagnostic_summary=diagnostic_summary,
        )

    def record_publication_marker(
        self,
        claim: JobClaim,
        *,
        run_identity: str,
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
        outcome: str,
    ) -> bool:
        return maintenance.record_publication_marker(
            self._connect,
            claim,
            run_identity=run_identity,
            source_generation=source_generation,
            config_generation=config_generation,
            extractor_generation=extractor_generation,
            canonicalizer_generation=canonicalizer_generation,
            outcome=outcome,
        )

    def cleanup_terminal(
        self, minimum_age: timedelta, *, limit: int, dry_run: bool
    ) -> tuple[str, ...]:
        return maintenance.cleanup_terminal(
            self._connect,
            minimum_age,
            limit=limit,
            dry_run=dry_run,
        )

    def status(self, job_id: str) -> JobStatus:
        return state.status(self._connect, job_id)


__all__ = [
    "CONTROL_SCHEMA_VERSION", "CONTROL_TABLES", "ControlSchemaError",
    "ControlStore", "ControlStoreError", "JobClaim", "JobStatus",
    "SingletonActiveError", "SubmissionResult",
]
