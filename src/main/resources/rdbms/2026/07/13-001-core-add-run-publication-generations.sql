--liquibase formatted sql
--changeset slair:2026_07_13-001-core-add-run-publication-generations

ALTER TABLE runs
    ADD COLUMN source_generation TEXT,
    ADD COLUMN config_generation TEXT,
    ADD COLUMN extractor_generation TEXT,
    ADD COLUMN canonicalizer_generation TEXT,
    ADD CONSTRAINT runs_publication_generations_all_or_none CHECK (
        (
            source_generation IS NULL
            AND config_generation IS NULL
            AND extractor_generation IS NULL
            AND canonicalizer_generation IS NULL
        )
        OR (
            source_generation IS NOT NULL
            AND config_generation IS NOT NULL
            AND extractor_generation IS NOT NULL
            AND canonicalizer_generation IS NOT NULL
            AND source_generation ~ '^sg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
            AND config_generation ~ '^cg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
            AND extractor_generation ~ '^eg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
            AND canonicalizer_generation ~ '^kg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        )
    );

--rollback ALTER TABLE runs DROP CONSTRAINT runs_publication_generations_all_or_none;
--rollback ALTER TABLE runs DROP COLUMN canonicalizer_generation;
--rollback ALTER TABLE runs DROP COLUMN extractor_generation;
--rollback ALTER TABLE runs DROP COLUMN config_generation;
--rollback ALTER TABLE runs DROP COLUMN source_generation;
