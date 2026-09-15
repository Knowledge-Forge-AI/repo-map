"""Descriptor-driven duplicate validation SQL for staging families."""

from __future__ import annotations

from repomap_kg.storage.staging_family_contracts import StageFamilyDescriptor


def identity_conflict_guard(
    descriptor: StageFamilyDescriptor,
    stage: str,
    label: str,
) -> str:
    """Build one deterministic semantic-payload duplicate guard."""

    identity = ", ".join(descriptor.identity_columns)
    payload = ", ".join(
        column
        for column in descriptor.payload_columns
        if column != descriptor.technical_ordinal
    )
    return f"""    IF EXISTS (
        SELECT 1
        FROM {descriptor.stage_table}
        WHERE stage_id = {stage}
        GROUP BY {identity}
        HAVING COUNT(DISTINCT (
            {payload}
        )) > 1
    ) THEN
        RAISE EXCEPTION '{label} stage validation conflict';
    END IF;
"""
