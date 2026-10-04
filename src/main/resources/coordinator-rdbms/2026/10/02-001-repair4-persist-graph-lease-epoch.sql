--liquibase formatted sql
--changeset repomap:repair4-persist-graph-lease-epoch

ALTER TABLE job_attempts
    ADD COLUMN graph_lease_fencing_epoch BIGINT NOT NULL DEFAULT 0
    CHECK (graph_lease_fencing_epoch >= 0);

ALTER TABLE graph_leases
    ADD COLUMN graph_lease_fencing_epoch BIGINT NOT NULL DEFAULT 0
    CHECK (graph_lease_fencing_epoch >= 0);

--rollback ALTER TABLE graph_leases DROP COLUMN graph_lease_fencing_epoch;
--rollback ALTER TABLE job_attempts DROP COLUMN graph_lease_fencing_epoch;
