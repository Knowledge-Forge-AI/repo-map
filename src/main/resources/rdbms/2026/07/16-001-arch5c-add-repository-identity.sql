--liquibase formatted sql
--changeset slair:2026_07_16-001-arch5c-add-repository-identity

ALTER TABLE repositories
    ADD COLUMN repository_identity TEXT;

CREATE UNIQUE INDEX repositories_repository_identity_key
    ON repositories(repository_identity)
    WHERE repository_identity IS NOT NULL;
