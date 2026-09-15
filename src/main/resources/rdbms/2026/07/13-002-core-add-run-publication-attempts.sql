--liquibase formatted sql
--changeset slair:2026_07_13-002-core-add-run-publication-attempts

ALTER TABLE runs
    ADD COLUMN publication_job_id TEXT,
    ADD COLUMN publication_attempt INTEGER,
    ADD CONSTRAINT runs_publication_attempt_receipt CHECK (
        (
            publication_job_id IS NULL
            AND publication_attempt IS NULL
            AND source_generation IS NULL
        )
        OR (
            publication_job_id IS NOT NULL
            AND publication_attempt IS NOT NULL
            AND source_generation IS NOT NULL
            AND publication_job_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            AND publication_job_id NOT LIKE '%--%'
            AND publication_attempt > 0
        )
    );

CREATE UNIQUE INDEX runs_publication_attempt_unique
    ON runs(publication_job_id, publication_attempt)
    WHERE publication_job_id IS NOT NULL;

--rollback DROP INDEX runs_publication_attempt_unique;
--rollback ALTER TABLE runs DROP CONSTRAINT runs_publication_attempt_receipt;
--rollback ALTER TABLE runs DROP COLUMN publication_attempt;
--rollback ALTER TABLE runs DROP COLUMN publication_job_id;
