--liquibase formatted sql
--changeset repomap:repair6-persist-supervisor-digest

ALTER TABLE job_attempts
    ADD COLUMN supervisor_registration_digest TEXT
    CHECK (supervisor_registration_digest IS NULL OR supervisor_registration_digest ~ '^[0-9a-f]{64}$'),
    ADD COLUMN supervisor_registration_consumed BOOLEAN NOT NULL DEFAULT FALSE;

--rollback ALTER TABLE job_attempts DROP COLUMN supervisor_registration_digest;
--rollback ALTER TABLE job_attempts DROP COLUMN supervisor_registration_consumed;
