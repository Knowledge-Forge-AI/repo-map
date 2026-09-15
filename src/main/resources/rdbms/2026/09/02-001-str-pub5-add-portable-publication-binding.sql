--liquibase formatted sql
--changeset slair:2026_09_02-001-str-pub5-add-portable-publication-binding

ALTER TABLE runs
    ADD COLUMN execution_route TEXT,
    ADD COLUMN snapshot_manifest_id TEXT,
    ADD COLUMN snapshot_vector_json TEXT,
    ADD COLUMN extraction_receipt_id TEXT,
    ADD COLUMN publication_bundle_id TEXT,
    ADD COLUMN graph_candidate_id TEXT,
    ADD COLUMN resolver_identity TEXT,
    ADD COLUMN portable_canonicalizer_identity TEXT,
    ADD COLUMN semantic_contract_identity TEXT,
    ADD COLUMN quality_rule_identity TEXT,
    ADD COLUMN portable_protocol_version TEXT,
    ADD COLUMN worker_capability_identity TEXT,
    ADD COLUMN portable_stage_id TEXT,
    ADD COLUMN portable_execution_mode TEXT,
    ADD COLUMN portable_singleton_fencing_epoch BIGINT,
    ADD COLUMN portable_graph_lease_fencing_epoch BIGINT,
    ADD COLUMN family_receipts_json TEXT,
    ADD CONSTRAINT runs_portable_publication_binding_all_or_none CHECK (
        (
            execution_route IS NULL
            AND snapshot_manifest_id IS NULL
            AND snapshot_vector_json IS NULL
            AND extraction_receipt_id IS NULL
            AND publication_bundle_id IS NULL
            AND graph_candidate_id IS NULL
            AND resolver_identity IS NULL
            AND portable_canonicalizer_identity IS NULL
            AND semantic_contract_identity IS NULL
            AND quality_rule_identity IS NULL
            AND portable_protocol_version IS NULL
            AND worker_capability_identity IS NULL
            AND portable_stage_id IS NULL
            AND portable_execution_mode IS NULL
            AND portable_singleton_fencing_epoch IS NULL
            AND portable_graph_lease_fencing_epoch IS NULL
            AND family_receipts_json IS NULL
        )
        OR (
            execution_route = 'portable-worker-v1'
            AND snapshot_manifest_id ~ '^snapmanifest1:[0-9a-f]{64}$'
            AND snapshot_vector_json IS NOT NULL
            AND extraction_receipt_id ~ '^receipt1:[0-9a-f]{64}$'
            AND publication_bundle_id ~ '^bundle1:[0-9a-f]{64}$'
            AND graph_candidate_id ~ '^cand1:[0-9a-f]{64}$'
            AND resolver_identity ~ '^resolver1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND portable_canonicalizer_identity ~ '^canon1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND semantic_contract_identity ~ '^semantic1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND quality_rule_identity ~ '^quality1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND portable_protocol_version = '1.0'
            AND worker_capability_identity ~ '^cap1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND portable_stage_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND portable_execution_mode IN ('direct', 'coordinator')
            AND portable_singleton_fencing_epoch >= 0
            AND portable_graph_lease_fencing_epoch >= 0
            AND family_receipts_json IS NOT NULL
        )
    );

COMMENT ON COLUMN runs.portable_stage_id IS
    'Publisher-owned physical execution evidence; never a semantic or public source identity.';

--rollback ALTER TABLE runs DROP CONSTRAINT runs_portable_publication_binding_all_or_none;
--rollback ALTER TABLE runs DROP COLUMN family_receipts_json;
--rollback ALTER TABLE runs DROP COLUMN portable_graph_lease_fencing_epoch;
--rollback ALTER TABLE runs DROP COLUMN portable_singleton_fencing_epoch;
--rollback ALTER TABLE runs DROP COLUMN portable_execution_mode;
--rollback ALTER TABLE runs DROP COLUMN portable_stage_id;
--rollback ALTER TABLE runs DROP COLUMN worker_capability_identity;
--rollback ALTER TABLE runs DROP COLUMN portable_protocol_version;
--rollback ALTER TABLE runs DROP COLUMN quality_rule_identity;
--rollback ALTER TABLE runs DROP COLUMN semantic_contract_identity;
--rollback ALTER TABLE runs DROP COLUMN portable_canonicalizer_identity;
--rollback ALTER TABLE runs DROP COLUMN resolver_identity;
--rollback ALTER TABLE runs DROP COLUMN graph_candidate_id;
--rollback ALTER TABLE runs DROP COLUMN publication_bundle_id;
--rollback ALTER TABLE runs DROP COLUMN extraction_receipt_id;
--rollback ALTER TABLE runs DROP COLUMN snapshot_vector_json;
--rollback ALTER TABLE runs DROP COLUMN snapshot_manifest_id;
--rollback ALTER TABLE runs DROP COLUMN execution_route;
