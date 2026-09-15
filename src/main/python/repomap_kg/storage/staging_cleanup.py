"""SCALE6 receipt-first, bounded staging cleanup SQL."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_ownership import (
    StageOwner,
    StageOwnershipError,
)
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)

__all__ = (
    "CleanupContractError",
    "CleanupRequest",
    "build_stage_cleanup_statements",
    "execute_stage_cleanup",
)

_STAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_BATCH_SIZE = 100_000
_CLEANUP_STATES = (
    "published",
    "failed",
    "cancelled",
    "abandoned",
    "cleanup_pending",
)


class CleanupContractError(ValueError):
    """A staging cleanup request violates the accepted SCALE6 contract."""


@dataclass(frozen=True)
class CleanupRequest:
    """Caller proof and bounded settings for one stage cleanup transaction."""

    owner: StageOwner
    stage_id: str
    attempt_live: bool
    batch_size: int = 1_000

    def validate(self) -> "CleanupRequest":
        try:
            self.owner.validate()
        except (StageOwnershipError, TypeError, ValueError) as error:
            raise CleanupContractError("invalid cleanup request") from error
        if not isinstance(self.stage_id, str) or _STAGE_ID_PATTERN.fullmatch(
            self.stage_id
        ) is None:
            raise CleanupContractError("invalid cleanup stage")
        if not isinstance(self.attempt_live, bool) or self.attempt_live:
            raise CleanupContractError("cleanup requires no live attempt")
        if (
            not isinstance(self.batch_size, int)
            or isinstance(self.batch_size, bool)
            or not 1 <= self.batch_size <= _MAX_BATCH_SIZE
        ):
            raise CleanupContractError("invalid cleanup batch size")
        return self


def build_stage_cleanup_statements(
    request: CleanupRequest,
) -> tuple[str, ...]:
    """Build one caller-owned transaction for receipt-first stage cleanup."""

    request.validate()
    owner = request.owner
    stage = sql_literal(request.stage_id)
    owner_predicate = _owner_predicate(stage, owner)
    states = ", ".join(sql_literal(state) for state in _CLEANUP_STATES)
    deletes = "\n    ".join(
        _delete_family(descriptor.stage_table, stage, request.batch_size)
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values()
    )
    remaining = " OR ".join(
        f"EXISTS (SELECT 1 FROM {descriptor.stage_table} WHERE stage_id = {stage})"
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values()
    )
    return (
        f"""DO $scale6_cleanup$
BEGIN
    PERFORM 1 FROM ingestion_stages
    WHERE {owner_predicate}
      AND state IN ({states})
      AND publication_reconciliation_state = 'reconciled'
      AND cleanup_eligibility IN ('eligible', 'expired')
      AND expires_at <= now()
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SCALE6 cleanup ownership or reconciliation failed';
    END IF;
    UPDATE ingestion_stages
    SET state = 'cleanup_pending', cleanup_eligibility = 'expired',
        cleanup_eligible_at = COALESCE(cleanup_eligible_at, now()),
        updated_at = now()
    WHERE {owner_predicate}
      AND state IN ({states})
      AND publication_reconciliation_state = 'reconciled'
      AND cleanup_eligibility IN ('eligible', 'expired')
      AND expires_at <= now();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SCALE6 cleanup stage transition failed';
    END IF;
    {deletes}
    IF NOT ({remaining}) THEN
        UPDATE ingestion_stages
        SET state = 'cleaned', cleanup_eligibility = 'cleaned',
            updated_at = now()
        WHERE {owner_predicate} AND state = 'cleanup_pending';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'SCALE6 cleaned stage update failed';
        END IF;
    END IF;
END
$scale6_cleanup$;""",
    )


def execute_stage_cleanup(
    connection: Any,
    request: CleanupRequest,
    *,
    staging_measurements: StagingMeasurements | None = None,
) -> None:
    """Execute one cleanup batch with optional identifier-free attribution."""

    statements = build_stage_cleanup_statements(request)
    if staging_measurements is None:
        for statement in statements:
            connection.execute(statement)
        return
    with staging_measurements.timed(StagingMeasurementCategory.CLEANUP):
        with staging_measurements.operation("cleanup.stage"):
            for statement in statements:
                connection.execute(statement)


def _delete_family(table: str, stage: str, batch_size: int) -> str:
    return f"""DELETE FROM {table}
    WHERE ctid IN (
        SELECT ctid FROM {table}
        WHERE stage_id = {stage}
        ORDER BY ctid
        LIMIT {batch_size}
    );"""


def _owner_predicate(stage: str, owner: StageOwner) -> str:
    return " AND ".join(
        (
            f"stage_id = {stage}",
            f"repository_id = {owner.repository_id}",
            f"operation_id = {sql_literal(owner.operation_id)}",
            f"attempt = {owner.attempt}",
            f"execution_mode = {sql_literal(owner.execution_mode)}",
            f"job_id IS NOT DISTINCT FROM {_nullable(owner.job_id)}",
            "coordinator_instance_id IS NOT DISTINCT FROM "
            f"{_nullable(owner.coordinator_instance_id)}",
            f"singleton_fencing_epoch = {owner.singleton_fencing_epoch}",
            f"graph_lease_fencing_epoch = {owner.graph_lease_fencing_epoch}",
            f"source_generation = {sql_literal(owner.source_generation)}",
            f"config_generation = {sql_literal(owner.config_generation)}",
            f"extractor_generation = {sql_literal(owner.extractor_generation)}",
            f"canonicalizer_generation = {sql_literal(owner.canonicalizer_generation)}",
        )
    )


def _nullable(value: str | None) -> str:
    return "NULL" if value is None else sql_literal(value)
