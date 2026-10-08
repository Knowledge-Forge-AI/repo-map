"""Transactional one-use launch registration on the current durable attempt."""
from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any

from psycopg.errors import LockNotAvailable, QueryCanceled
from psycopg.rows import dict_row

from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim


class FencingContentionError(PermissionError):
    """Expected bounded PostgreSQL fencing contention."""


class StaleDurableAuthorityError(PermissionError):
    """Current singleton, attempt or graph lease cannot authorize closure."""


def lock_and_validate_current_durable(
    cursor: Any, claim: JobClaim, *, reconciler_instance_id: str,
    reconciler_epoch: int, restart: bool = True, allow_legacy: bool = False,
    expected_registration_digest: str | None = None,
) -> dict[str, Any] | None:
    """Lock singleton, current attempt and exact graph lease in that order."""
    cursor.execute(
        """SELECT 1 FROM coordinator_instances
           WHERE singleton_scope = 'control' AND instance_id = %s
             AND fencing_epoch = %s AND status = 'active'
             AND expires_at > clock_timestamp() FOR UPDATE""",
        (reconciler_instance_id, reconciler_epoch),
    )
    if cursor.fetchone() is None:
        return None
    cursor.execute(
        """SELECT a.*, j.graph_id, j.state AS job_state,
                  j.publication_state AS job_publication_state
           FROM job_attempts AS a JOIN jobs AS j ON j.job_id = a.job_id
           WHERE a.job_id = %s AND a.attempt = %s AND a.is_current
             AND j.current_attempt = a.attempt FOR UPDATE OF j, a""",
        (claim.job_id, claim.attempt),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    fields = ("source_generation", "config_generation", "extractor_generation", "canonicalizer_generation")
    if (row["graph_id"] != claim.graph_id
            or row["coordinator_instance_id"] != claim.instance_id
            or row["fencing_epoch"] != claim.fencing_epoch
            or any(row[key] != getattr(claim, key) for key in fields)):
        return None
    if expected_registration_digest is not None:
        stored_digest = row.get("supervisor_registration_digest")
        if (not stored_digest or stored_digest != expected_registration_digest
                or row.get("supervisor_registration_consumed", False)):
            return None
    if not allow_legacy:
        if (row["graph_lease_fencing_epoch"] <= 0
                or row["graph_lease_fencing_epoch"] != claim.graph_lease_fencing_epoch):
            return None
    else:
        if (row["graph_lease_fencing_epoch"] != 0
                or claim.graph_lease_fencing_epoch != 0
                or claim.fencing_epoch >= reconciler_epoch):
            return None
    if restart:
        if row["job_state"] != "reconciliation_required" or reconciler_epoch <= claim.fencing_epoch:
            return None
    elif (reconciler_instance_id != claim.instance_id or reconciler_epoch != claim.fencing_epoch
          or row["job_state"] not in {"starting", "running", "cancel_requested", "cancelling"}):
        return None
    cursor.execute(
        """SELECT *, expires_at > clock_timestamp() AS lease_active
           FROM graph_leases WHERE graph_id = %s FOR UPDATE""", (claim.graph_id,),
    )
    lease = cursor.fetchone()
    if lease is None:
        return None
    expected_matches = {
        "job_id": claim.job_id, "attempt": claim.attempt,
        "coordinator_instance_id": claim.instance_id, "fencing_epoch": claim.fencing_epoch,
    }
    if any(lease[key] != expected for key, expected in expected_matches.items()):
        return None
    if not allow_legacy:
        if lease["graph_lease_fencing_epoch"] != claim.graph_lease_fencing_epoch:
            return None
    else:
        if lease["graph_lease_fencing_epoch"] != 0:
            return None
    if bool(lease["lease_active"]) == restart:
        return None
    return row


def _require_currency(
    cursor: Any, claim: JobClaim, *, allow_legacy: bool = False,
    expected_registration_digest: str | None = None, **authority: Any
) -> None:
    if lock_and_validate_current_durable(
        cursor, claim, allow_legacy=allow_legacy,
        expected_registration_digest=expected_registration_digest, **authority
    ) is None:
        raise StaleDurableAuthorityError("current durable attempt or lease authority has turned over")


DEFAULT_FENCING_LOCK_TIMEOUT_MS: int = 250
DEFAULT_FENCING_STATEMENT_TIMEOUT_MS: int = 1000


def _apply_fencing_timeouts(
    cursor: Any,
    *,
    lock_timeout_ms: int = DEFAULT_FENCING_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_FENCING_STATEMENT_TIMEOUT_MS,
) -> None:
    cursor.execute(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'")
    cursor.execute(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'")


def validate_supervisor_registration(connect: ConnectionFactory, claim: JobClaim, registration_digest: str) -> None:
    try:
        with connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                _apply_fencing_timeouts(cursor)
                _require_currency(
                    cursor, claim, reconciler_instance_id=claim.instance_id,
                    reconciler_epoch=claim.fencing_epoch, restart=False,
                    expected_registration_digest=registration_digest,
                )
    except (LockNotAvailable, QueryCanceled) as error:
        raise FencingContentionError("durable lock contention") from error


def persist_supervisor_registration(connect: ConnectionFactory, claim: JobClaim, registration_digest: str) -> None:
    if type(registration_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", registration_digest) is None:
        raise PermissionError("invalid supervisor registration digest")
    try:
        with connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                _apply_fencing_timeouts(cursor)
                row = lock_and_validate_current_durable(
                    cursor, claim, reconciler_instance_id=claim.instance_id,
                    reconciler_epoch=claim.fencing_epoch, restart=False,
                )
                if row is None:
                    raise StaleDurableAuthorityError("current durable attempt or lease authority has turned over")
                if row.get("supervisor_registration_digest") is not None or row.get("supervisor_registration_consumed", False):
                    raise PermissionError("supervisor registration already exists or was consumed for this attempt")
                cursor.execute(
                    """UPDATE job_attempts SET supervisor_registration_digest = %s
                       WHERE job_id = %s AND attempt = %s AND is_current
                         AND coordinator_instance_id = %s AND fencing_epoch = %s""",
                    (registration_digest, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
                )
                if cursor.rowcount != 1:
                    raise StaleDurableAuthorityError("failed to record supervisor registration digest")
            connection.commit()
    except (LockNotAvailable, QueryCanceled) as error:
        raise FencingContentionError("durable lock contention") from error


@contextmanager
def in_process_currency_context(connect: ConnectionFactory, claim: JobClaim, registration_digest: str | None = None):
    if type(registration_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", registration_digest) is None:
        raise StaleDurableAuthorityError("durable launch registration is required")
    try:
        with connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                _apply_fencing_timeouts(cursor)
                _require_currency(
                    cursor, claim, reconciler_instance_id=claim.instance_id,
                    reconciler_epoch=claim.fencing_epoch, restart=False,
                    expected_registration_digest=registration_digest,
                )
                cursor.execute(
                    """UPDATE job_attempts SET supervisor_registration_consumed = TRUE
                       WHERE job_id = %s AND attempt = %s AND is_current
                         AND coordinator_instance_id = %s AND fencing_epoch = %s""",
                    (claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
                )
                if cursor.rowcount != 1:
                    raise StaleDurableAuthorityError("failed to consume supervisor registration digest")
            # Currency locks remain held during the exclusive filesystem decision.
            # Consume even a refused/erroring decision, preventing durable replay.
            try:
                yield connection
            finally:
                connection.commit()
    except (LockNotAvailable, QueryCanceled) as error:
        raise FencingContentionError("durable lock contention") from error
