"""Locked durable ownership and replacement publication fencing."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

from psycopg.rows import dict_row
from psycopg.errors import LockNotAvailable, QueryCanceled

from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim
from repomap_kg.coordinator._publication_phase import WorkerFencingProof, _issue_fencing_proof
from repomap_kg.coordinator._supervisor_registration import (
    FencingContentionError as FencingContentionError,
    StaleDurableAuthorityError as StaleDurableAuthorityError,
    lock_and_validate_current_durable as lock_and_validate_current_durable,
    _require_currency, _apply_fencing_timeouts,
    DEFAULT_FENCING_LOCK_TIMEOUT_MS as DEFAULT_FENCING_LOCK_TIMEOUT_MS,
    DEFAULT_FENCING_STATEMENT_TIMEOUT_MS as DEFAULT_FENCING_STATEMENT_TIMEOUT_MS,
    in_process_currency_context as in_process_currency_context,
    persist_supervisor_registration as persist_supervisor_registration,
)


def make_store_closure_context_factory(
    connect: ConnectionFactory, claim: JobClaim, *, reconciler_instance_id: str,
    reconciler_epoch: int, fence_callback: Callable[..., Any] | None,
) -> Callable[[], Any]:
    """Revalidate and durably fence before allowing an exclusive file decision."""
    @contextmanager
    def closure_context():
        if fence_callback is None:
            raise StaleDurableAuthorityError("durable graph fencing is unavailable")
        try:
            with connect() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    _apply_fencing_timeouts(cursor)
                    authority: dict[str, Any] = dict(reconciler_instance_id=reconciler_instance_id, reconciler_epoch=reconciler_epoch)
                    _require_currency(cursor, claim, **authority)
                    if fence_callback(claim, **authority, prior_lease_epoch=claim.graph_lease_fencing_epoch) is not True:
                        raise StaleDurableAuthorityError("durable graph fence installation was not verified")
                    # The external storage transaction may take time; recheck lease liveness.
                    _require_currency(cursor, claim, **authority)
                    yield connection
        except (LockNotAvailable, QueryCanceled) as error:
            raise FencingContentionError("durable lock contention") from error
    return closure_context


def build_store_fencing_proof(
    connect: ConnectionFactory, claim: JobClaim, *, reconciler_instance_id: str,
    reconciler_epoch: int, fence_callback: Callable[..., Any] | None = None,
) -> WorkerFencingProof | None:
    if fence_callback is None:
        return None
    try:
        with connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                _apply_fencing_timeouts(cursor)
                if lock_and_validate_current_durable(cursor, claim, reconciler_instance_id=reconciler_instance_id,
                                                     reconciler_epoch=reconciler_epoch) is None:
                    return None
    except (LockNotAvailable, QueryCanceled):
        return None
    context = make_store_closure_context_factory(
        connect, claim, reconciler_instance_id=reconciler_instance_id,
        reconciler_epoch=reconciler_epoch, fence_callback=fence_callback,
    )
    return _issue_fencing_proof(claim, "store_fenced", context)


def execute_durable_closure(
    connect: ConnectionFactory, claim: JobClaim, *, reconciler_instance_id: str,
    reconciler_epoch: int, fence_callback: Callable[..., Any] | None,
    file_closer: Callable[[JobClaim, WorkerFencingProof], bool] | None,
) -> bool:
    """Fence graph storage, close the gate, then persist not_started under locks."""
    if fence_callback is None or file_closer is None:
        return False
    context = make_store_closure_context_factory(
        connect, claim, reconciler_instance_id=reconciler_instance_id,
        reconciler_epoch=reconciler_epoch, fence_callback=fence_callback,
    )
    try:
        with context() as connection:
            active = True

            @contextmanager
            def locked_currency():
                if not active:
                    raise StaleDurableAuthorityError("store closure authority has expired")
                with connection.cursor(row_factory=dict_row) as cursor:
                    _require_currency(cursor, claim, reconciler_instance_id=reconciler_instance_id,
                                      reconciler_epoch=reconciler_epoch)
                yield connection

            proof = _issue_fencing_proof(claim, "store_fenced", locked_currency)
            try:
                if file_closer(claim, proof) is not True:
                    connection.rollback()
                    return False
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE jobs SET publication_state = 'not_started', updated_at = now() "
                        "WHERE job_id = %s AND current_attempt = %s AND state = 'reconciliation_required'",
                        (claim.job_id, claim.attempt),
                    )
                    if cursor.rowcount != 1:
                        raise StaleDurableAuthorityError("current job closure failed")
                    cursor.execute(
                        "UPDATE job_attempts SET publication_state = 'not_started', supervisor_registration_digest = NULL "
                        "WHERE job_id = %s AND attempt = %s AND is_current",
                        (claim.job_id, claim.attempt),
                    )
                    if cursor.rowcount != 1:
                        raise StaleDurableAuthorityError("current attempt closure failed")
                connection.commit()
                return True
            finally:
                active = False
    except (LockNotAvailable, QueryCanceled):
        return False
    except StaleDurableAuthorityError:
        raise
    except PermissionError:
        return False


def quarantine_legacy_attempt(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    reconciler_instance_id: str,
    reconciler_epoch: int,
    fence_callback: Callable[..., Any] | None,
) -> bool:
    """Safely fence graph storage and quarantine exact legacy zero-epoch attempts."""
    if fence_callback is None:
        return False
    if getattr(claim, "graph_lease_fencing_epoch", None) != 0:
        return False
    try:
        with connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                _apply_fencing_timeouts(cursor)
                authority: dict[str, Any] = dict(
                    reconciler_instance_id=reconciler_instance_id,
                    reconciler_epoch=reconciler_epoch,
                    allow_legacy=True,
                )
                if lock_and_validate_current_durable(cursor, claim, **authority) is None:
                    return False
                cursor.execute("SELECT txid_current() AS txid_current")
                tx_row = cursor.fetchone()
                if (not isinstance(tx_row, dict) or not isinstance(tx_row.get("txid_current"), int)
                        or isinstance(tx_row["txid_current"], bool) or tx_row["txid_current"] <= 0):
                    raise RuntimeError("durable replacement epoch allocation failed")
                new_lease_epoch = tx_row["txid_current"]

                if fence_callback(
                    claim,
                    reconciler_instance_id=reconciler_instance_id,
                    reconciler_epoch=reconciler_epoch,
                    prior_lease_epoch=0,
                    replacement_lease_epoch=new_lease_epoch,
                ) is not True:
                    raise StaleDurableAuthorityError("durable graph fence installation was not verified")

                if lock_and_validate_current_durable(cursor, claim, **authority) is None:
                    raise StaleDurableAuthorityError("current durable attempt or lease authority has turned over")

                cursor.execute(
                    """
                    UPDATE jobs SET state = 'quarantined', publication_state = 'commit_unknown',
                                    error_category = 'legacy_zero_epoch', finished_at = now(),
                                    updated_at = now()
                    WHERE job_id = %s AND current_attempt = %s AND state = 'reconciliation_required'
                    """,
                    (claim.job_id, claim.attempt),
                )
                if cursor.rowcount != 1:
                    raise StaleDurableAuthorityError("legacy attempt quarantine failed")

                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET is_current = false, finished_at = COALESCE(finished_at, now()),
                        publication_state = 'commit_unknown', result_category = 'legacy_zero_epoch',
                        supervisor_registration_digest = NULL
                    WHERE job_id = %s AND attempt = %s AND is_current
                      AND coordinator_instance_id = %s AND fencing_epoch = %s
                    """,
                    (claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
                )
                if cursor.rowcount != 1:
                    raise StaleDurableAuthorityError("legacy attempt closure failed")

                cursor.execute(
                    """
                    DELETE FROM graph_leases
                    WHERE graph_id = %s AND job_id = %s AND attempt = %s
                      AND coordinator_instance_id = %s AND fencing_epoch = %s
                      AND graph_lease_fencing_epoch = 0
                    """,
                    (claim.graph_id, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
                )
                if cursor.rowcount != 1:
                    raise StaleDurableAuthorityError("legacy lease deletion failed")

                cursor.execute(
                    """
                    UPDATE coalescing_state SET running_job_id = NULL
                    WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                      AND running_job_id = %s
                    """,
                    (claim.graph_id, claim.job_id),
                )
            connection.commit()
            return True
    except (LockNotAvailable, QueryCanceled):
        return False
    except StaleDurableAuthorityError:
        return False


class _FencingStoreMixin:
    _connect: ConnectionFactory

    def register_supervisor_launch(self, ticket: object, capability: object) -> None:
        from repomap_kg.coordinator._supervisor_fencing import bind_durable_launch

        bind_durable_launch(ticket, capability, self._connect)

    def set_durable_fence_callback(
        self, callback: Callable[..., Any] | None
    ) -> None:
        self._durable_fence_callback = callback

    def prove_worker_fenced(
        self, claim: JobClaim, *, reconciler_instance_id: str, reconciler_epoch: int,
    ) -> object | None:
        return build_store_fencing_proof(
            self._connect, claim,
            reconciler_instance_id=reconciler_instance_id,
            reconciler_epoch=reconciler_epoch,
            fence_callback=getattr(self, "_durable_fence_callback", None),
        )

    def close_unpublished_reconciliation(
        self,
        claim: JobClaim,
        *,
        reconciler_instance_id: str,
        reconciler_epoch: int,
        file_closer: Callable[[JobClaim, Any], bool],
    ) -> bool:
        return execute_durable_closure(
            self._connect,
            claim,
            reconciler_instance_id=reconciler_instance_id,
            reconciler_epoch=reconciler_epoch,
            fence_callback=getattr(self, "_durable_fence_callback", None),
            file_closer=file_closer,
        )

    def quarantine_legacy_attempt(
        self,
        claim: JobClaim,
        *,
        reconciler_instance_id: str,
        reconciler_epoch: int,
    ) -> bool:
        return quarantine_legacy_attempt(
            self._connect,
            claim,
            reconciler_instance_id=reconciler_instance_id,
            reconciler_epoch=reconciler_epoch,
            fence_callback=getattr(self, "_durable_fence_callback", None),
        )
