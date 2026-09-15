"""SCALE stage transition and COPY completeness checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_observability import StagingMeasurements


def mark_validating(connection: Any, stage_id: str) -> None:
    """Move a prepared stage into set-based validation."""

    cursor = connection.execute(
        """
UPDATE ingestion_stages
SET state = 'validating', validation_status = 'running', updated_at = now()
WHERE stage_id = %s AND state = 'prepared'
""",
        (stage_id,),
    )
    if cursor.rowcount != 1:
        raise StorageSchemaError("staged validating transition failed")


def validate_stage(
    connection: Any,
    stage_id: str,
    expected_counts: Mapping[str, int],
    *,
    staging_measurements: StagingMeasurements | None = None,
) -> None:
    """Verify every typed stage table contains its expected COPY rows."""

    for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
        if staging_measurements is None:
            row = connection.execute(
                f"SELECT count(*) FROM {descriptor.stage_table} WHERE stage_id = %s",
                (stage_id,),
            ).fetchone()
        else:
            with staging_measurements.operation(f"completeness.{family}"):
                row = connection.execute(
                    f"SELECT count(*) FROM {descriptor.stage_table} WHERE stage_id = %s",
                    (stage_id,),
                ).fetchone()
        if row is None or int(row[0]) != expected_counts[family]:
            raise StorageSchemaError("staged family completeness failed")


def mark_validated(connection: Any, stage_id: str) -> None:
    """Record successful set-based validation."""

    cursor = connection.execute(
        """
UPDATE ingestion_stages
SET state = 'validated', validation_status = 'passed', updated_at = now()
WHERE stage_id = %s AND state = 'validating'
""",
        (stage_id,),
    )
    if cursor.rowcount != 1:
        raise StorageSchemaError("staged validated transition failed")
