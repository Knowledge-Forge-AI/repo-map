"""SQL statement and clause builders for publication fencing."""

from __future__ import annotations

import json

from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner

__all__ = (
    "build_authority_check_sql",
    "build_authority_upsert_sql",
    "build_completeness_predicate_sql",
    "build_finalize_sql",
    "build_owner_predicate_sql",
    "build_prepare_update_sql",
    "build_receipt_predicate_sql",
    "build_reconcile_update_sql",
    "build_stage_guard_sql",
    "sql_nullable_literal",
    "sql_value_literal",
)


def build_stage_guard_sql(
    merge: MergeContext,
    receipt: RunPublicationReceipt,
    *,
    allowed_states: tuple[str, ...],
    label: str,
) -> str:
    context, owner = merge, merge.owner
    stage = sql_literal(context.stage_id)
    predicate = build_owner_predicate_sql(stage, owner)
    states = ", ".join(sql_literal(state) for state in allowed_states)
    completeness = build_completeness_predicate_sql(stage)
    run = str(context.run_id)
    receipt_sql = build_receipt_predicate_sql(receipt)
    authority_check = build_authority_check_sql(owner)
    return f"""DO $scale5_{label}$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ingestion_stages
        WHERE {predicate}
          AND state IN ({states})
          AND validation_status = 'passed'
          AND {completeness}
        FOR UPDATE
    ) THEN
        RAISE EXCEPTION 'SCALE5 stage ownership or completeness failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM runs
        WHERE id = {run} AND repository_id = {owner.repository_id}
          AND (
              (status = 'running' AND {receipt_sql['all_null']})
              OR (status = 'complete' AND {receipt_sql['matching']})
          )
        FOR UPDATE
    ) THEN
        RAISE EXCEPTION 'SCALE5 run receipt handoff failed';
    END IF;
    {authority_check}
END
$scale5_{label}$;"""


def build_prepare_update_sql(context: MergeContext) -> str:
    owner = context.owner
    stage = sql_literal(context.stage_id)
    return f"""UPDATE ingestion_stages
SET state = 'merging', merge_status = 'running', updated_at = now()
WHERE {build_owner_predicate_sql(stage, owner)}
  AND state IN ('validated', 'merging')
  AND validation_status = 'passed';"""


def build_finalize_sql(
    merge: MergeContext,
    receipt: RunPublicationReceipt,
) -> str:
    context = merge
    owner = context.owner
    stage = sql_literal(context.stage_id)
    run = str(context.run_id)
    receipt_map = receipt.to_mapping()
    matching = build_receipt_predicate_sql(receipt)["matching"]
    authority = build_authority_upsert_sql(owner, context.stage_id, run)
    return f"""DO $scale5_publish$
BEGIN
    UPDATE runs
    SET status = 'complete', finished_at = now(),
        {', '.join(f'{field} = {sql_value_literal(value)}' for field, value in receipt_map.items())}
    WHERE id = {run} AND repository_id = {owner.repository_id}
      AND status = 'running'
      AND {build_receipt_predicate_sql(receipt)['all_null']};
    IF NOT FOUND AND NOT EXISTS (
        SELECT 1 FROM runs
        WHERE id = {run} AND repository_id = {owner.repository_id}
          AND status = 'complete' AND {matching}
    ) THEN
        RAISE EXCEPTION 'SCALE5 publication receipt conflict';
    END IF;
    {authority}
    UPDATE ingestion_stages
    SET state = 'published', merge_status = 'committed',
        publication_reconciliation_state = 'reconciled',
        cleanup_eligibility = 'eligible', cleanup_eligible_at = now(),
        updated_at = now()
    WHERE {build_owner_predicate_sql(stage, owner)}
      AND state IN ('merging', 'published');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SCALE5 published stage update failed';
    END IF;
END
$scale5_publish$;"""


def build_reconcile_update_sql(
    merge: MergeContext,
    receipt: RunPublicationReceipt | None = None,
    *,
    label: str,
    target_state: str,
    allowed_states: tuple[str, ...],
    idempotent: str,
) -> str:
    owner = merge.owner
    stage = sql_literal(merge.stage_id)
    states = ", ".join(sql_literal(state) for state in allowed_states)
    if target_state == "quarantined":
        merge_status, reconciliation, cleanup = "unknown", "conflicting", "quarantined"
    else:
        merge_status, reconciliation, cleanup = (
            ("committed", "reconciled", "eligible")
            if target_state == "published" else ("rolled_back", "reconciled", "eligible")
        )
    cleanup_at = ", cleanup_eligible_at = now()" if cleanup == "eligible" else ""
    assignments = f"""state = {sql_literal(target_state)}, merge_status = {sql_literal(merge_status)},
    publication_reconciliation_state = {sql_literal(reconciliation)},
    cleanup_eligibility = {sql_literal(cleanup)}{cleanup_at}, updated_at = now()"""
    return f"""DO $scale5_reconcile_{label}$
DECLARE
    stage_updated BOOLEAN := false;
BEGIN
    UPDATE ingestion_stages
    SET {assignments}
    WHERE {build_owner_predicate_sql(stage, owner)}
      AND state IN ({states});
    stage_updated := FOUND;
    IF NOT stage_updated AND NOT EXISTS (
        SELECT 1 FROM ingestion_stages
        WHERE {build_owner_predicate_sql(stage, owner)}
          AND {idempotent}
    ) THEN
        RAISE EXCEPTION 'SCALE5 reconciliation stage update failed';
    END IF;
END
$scale5_reconcile_{label}$;"""


def build_authority_upsert_sql(
    owner: StageOwner,
    stage_id: str,
    run: str,
    *,
    stale_message: str = "SCALE5 stale publication fence",
) -> str:
    if owner.execution_mode == "direct":
        return "-- direct mode authority is supplied by its explicit local adapter"
    return f"""INSERT INTO graph_publication_authority(
    repository_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    job_id, attempt, coordinator_instance_id, source_generation,
    config_generation, extractor_generation, canonicalizer_generation,
    last_stage_id, last_run_id, updated_at
)
VALUES (
    {owner.repository_id}, {owner.singleton_fencing_epoch},
    {owner.graph_lease_fencing_epoch}, {sql_literal(owner.job_id)}, {owner.attempt},
    {sql_literal(owner.coordinator_instance_id)},
    {sql_literal(owner.source_generation)}, {sql_literal(owner.config_generation)},
    {sql_literal(owner.extractor_generation)},
    {sql_literal(owner.canonicalizer_generation)}, {sql_literal(stage_id)},
    {run}, now()
)
ON CONFLICT (repository_id) DO UPDATE SET
    singleton_fencing_epoch = EXCLUDED.singleton_fencing_epoch,
    graph_lease_fencing_epoch = EXCLUDED.graph_lease_fencing_epoch,
    job_id = EXCLUDED.job_id, attempt = EXCLUDED.attempt,
    coordinator_instance_id = EXCLUDED.coordinator_instance_id,
    source_generation = EXCLUDED.source_generation,
    config_generation = EXCLUDED.config_generation,
    extractor_generation = EXCLUDED.extractor_generation,
    canonicalizer_generation = EXCLUDED.canonicalizer_generation,
    last_stage_id = EXCLUDED.last_stage_id, last_run_id = EXCLUDED.last_run_id,
    updated_at = now()
WHERE (
    graph_publication_authority.singleton_fencing_epoch
        <= EXCLUDED.singleton_fencing_epoch
    AND graph_publication_authority.graph_lease_fencing_epoch
        < EXCLUDED.graph_lease_fencing_epoch
) OR (
    graph_publication_authority.singleton_fencing_epoch
        = EXCLUDED.singleton_fencing_epoch
    AND graph_publication_authority.graph_lease_fencing_epoch
        = EXCLUDED.graph_lease_fencing_epoch
    AND graph_publication_authority.job_id = EXCLUDED.job_id
    AND graph_publication_authority.attempt = EXCLUDED.attempt
    AND graph_publication_authority.coordinator_instance_id
        = EXCLUDED.coordinator_instance_id
    AND graph_publication_authority.source_generation
        = EXCLUDED.source_generation
    AND graph_publication_authority.config_generation
        = EXCLUDED.config_generation
    AND graph_publication_authority.extractor_generation
        = EXCLUDED.extractor_generation
    AND graph_publication_authority.canonicalizer_generation
        = EXCLUDED.canonicalizer_generation
    AND graph_publication_authority.last_stage_id = EXCLUDED.last_stage_id
);
IF NOT FOUND THEN
    RAISE EXCEPTION {sql_literal(stale_message)};
END IF;"""


def build_authority_check_sql(owner: StageOwner) -> str:
    if owner.execution_mode == "direct":
        return "-- direct mode uses its explicit local mutation authority"
    return f"""PERFORM 1 FROM graph_publication_authority
    WHERE repository_id = {owner.repository_id} FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM graph_publication_authority
        WHERE repository_id = {owner.repository_id}
          AND (singleton_fencing_epoch > {owner.singleton_fencing_epoch}
               OR graph_lease_fencing_epoch > {owner.graph_lease_fencing_epoch})
    ) THEN
        RAISE EXCEPTION 'SCALE5 stale publication fence';
    END IF;"""


def build_owner_predicate_sql(stage: str, owner: StageOwner) -> str:
    return " AND ".join((f"stage_id = {stage}", f"repository_id = {owner.repository_id}",
        f"operation_id = {sql_literal(owner.operation_id)}", f"attempt = {owner.attempt}",
        f"execution_mode = {sql_literal(owner.execution_mode)}",
        f"job_id IS NOT DISTINCT FROM {sql_nullable_literal(owner.job_id)}",
        f"coordinator_instance_id IS NOT DISTINCT FROM {sql_nullable_literal(owner.coordinator_instance_id)}",
        f"singleton_fencing_epoch = {owner.singleton_fencing_epoch}",
        f"graph_lease_fencing_epoch = {owner.graph_lease_fencing_epoch}",
        f"source_generation = {sql_literal(owner.source_generation)}",
        f"config_generation = {sql_literal(owner.config_generation)}",
        f"extractor_generation = {sql_literal(owner.extractor_generation)}",
        f"canonicalizer_generation = {sql_literal(owner.canonicalizer_generation)}"))


def build_completeness_predicate_sql(stage: str) -> str:
    count_checks = " AND ".join(
        f"(SELECT count(*) FROM {descriptor.stage_table} WHERE stage_id = {stage}) "
        f"= (expected_row_counts->>{sql_literal(family)})::bigint"
        for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items()
    )
    family_count = len(STAGING_FAMILY_DESCRIPTORS)
    family_manifest = json.dumps(
        list(STAGING_FAMILY_DESCRIPTORS), separators=(",", ":")
    )
    return " AND ".join(
        (
            "expected_row_counts = observed_row_counts",
            "(SELECT count(*) FROM jsonb_object_keys(expected_row_counts)) "
            f"= {family_count}",
            "(SELECT count(*) FROM jsonb_object_keys(observed_row_counts)) "
            f"= {family_count}",
            "(SELECT count(*) FROM jsonb_object_keys(family_checksums)) "
            f"= {family_count}",
            "(SELECT count(*) FROM jsonb_object_keys(normalized_byte_counts)) "
            f"= {family_count}",
            "expected_family_manifest->>'schema_version' = '1'",
            f"expected_family_manifest->'families' = '{family_manifest}'::jsonb",
            count_checks,
        )
    )


def build_receipt_predicate_sql(receipt: RunPublicationReceipt) -> dict[str, str]:
    values = receipt.to_mapping()
    all_null = " AND ".join(f"{field} IS NULL" for field in values)
    matching = " AND ".join(
        f"{field} = {sql_value_literal(value)}" for field, value in values.items()
    )
    return {"all_null": all_null, "matching": matching}


def sql_nullable_literal(value: str | None) -> str:
    return "NULL" if value is None else sql_literal(value)


def sql_value_literal(value: str | int) -> str:
    return str(value) if isinstance(value, int) else sql_literal(value)
