--liquibase formatted sql
--changeset slair:2026_06_28-004-core-add_edge_stable_key

ALTER TABLE edges
    ADD COLUMN stable_key TEXT;

UPDATE edges
SET stable_key = 'legacy:edge:' || id::text
WHERE stable_key IS NULL;

ALTER TABLE edges
    ALTER COLUMN stable_key SET NOT NULL;

ALTER TABLE edges
    ADD CONSTRAINT edges_repository_stable_key_key
    UNIQUE (repository_id, stable_key);

--rollback ALTER TABLE edges DROP CONSTRAINT edges_repository_stable_key_key;
--rollback ALTER TABLE edges DROP COLUMN stable_key;
