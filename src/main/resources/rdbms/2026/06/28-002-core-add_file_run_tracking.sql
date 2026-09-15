--liquibase formatted sql
--changeset slair:2026_06_28-002-core-add_file_run_tracking

ALTER TABLE files
    ADD COLUMN last_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL;

CREATE INDEX idx_files_last_seen_run_id ON files(last_seen_run_id);

--rollback DROP INDEX idx_files_last_seen_run_id;
--rollback ALTER TABLE files DROP COLUMN last_seen_run_id;
