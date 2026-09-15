--liquibase formatted sql
--changeset slair:2026_06_28-003-core-add_evidence_stable_key

ALTER TABLE evidence
    ADD COLUMN stable_key TEXT NOT NULL;

ALTER TABLE evidence
    ADD CONSTRAINT evidence_repository_stable_key_key
    UNIQUE (repository_id, stable_key);

--rollback ALTER TABLE evidence DROP CONSTRAINT evidence_repository_stable_key_key;
--rollback ALTER TABLE evidence DROP COLUMN stable_key;
