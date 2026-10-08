import unittest
from dataclasses import replace
import json

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    raw_observation_rows_from_observations,
    raw_observation_upsert_sql,
)



class StorageRawObservationLoadIntegrationTests(unittest.TestCase):
    def test_raw_observation_upsert_is_idempotent_for_same_payload_hash(self):
        require_postgres_binaries()
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "documentation"},
        )
        row = raw_observation_rows_from_observations([observation])[0]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            count = postgres.psql_scalar(
                f"""
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset repo_
INSERT INTO runs(repository_id, status)
VALUES (:repo_id, 'complete')
RETURNING id
\\gset run_
{raw_observation_upsert_sql(row)}
{raw_observation_upsert_sql(row)}
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
            )

        self.assertEqual(count, "1")

    def test_raw_observation_upsert_rejects_same_ordinal_different_hash(self):
        require_postgres_binaries()
        original = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "documentation"},
        )
        changed = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "source"},
        )
        original_row = raw_observation_rows_from_observations([original])[0]
        changed_row = raw_observation_rows_from_observations([changed])[0]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            with self.assertRaisesRegex(
                AssertionError,
                "raw observation payload hash mismatch",
            ):
                postgres.psql_scalar(
                    f"""
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset repo_
INSERT INTO runs(repository_id, status)
VALUES (:repo_id, 'complete')
RETURNING id
\\gset run_
{raw_observation_upsert_sql(original_row)}
{raw_observation_upsert_sql(changed_row)}
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
                )

    def test_raw_observation_transactional_batch_unicode_escaping_replay_and_schema_rollback(self):
        require_postgres_binaries()
        batch = [
            RawObservation(
                kind="file",
                source_id="src/日本語/🚀_app.py",
                path="src/日本語/🚀_app.py",
                confidence="manual",
                extractor="fixture-unicode",
                extractor_version="0.1.0",
                metadata={"language": "python", "role": "source"},
            ),
            RawObservation(
                kind="config.document",
                source_id="config/'spécial'.json#section",
                path="config/'spécial'.json",
                confidence="manual",
                extractor="fixture-unicode",
                extractor_version="0.1.0",
                metadata={
                    "note": "quote ' test \\ and \n and 🚀 emoji",
                    "tags": ["日本語", "utf8"],
                },
            ),
        ]
        rows = raw_observation_rows_from_observations(batch)
        upsert_stmts = "\n".join(raw_observation_upsert_sql(r) for r in rows)

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            # A conflicting ordinal after valid inserts rolls the whole transaction back.
            conflicting = raw_observation_rows_from_observations([replace(batch[0], metadata={"language": "python", "role": "changed"})])[0]
            with self.assertRaisesRegex(AssertionError, "raw observation payload hash mismatch"):
                postgres.psql_scalar(
                    f"""
BEGIN;
INSERT INTO repositories(name, root_path) VALUES ('fixture-rollback', '/tmp/fixture-rollback') RETURNING id \\gset repo_
INSERT INTO runs(repository_id, status) VALUES (:repo_id, 'complete') RETURNING id \\gset run_
{upsert_stmts}
{raw_observation_upsert_sql(conflicting)}
COMMIT;
"""
                )
            self.assertEqual(postgres.psql_scalar("SELECT count(*) FROM raw_observations;"), "0")
            self.assertEqual(postgres.psql_scalar("SELECT count(*) FROM repositories;"), "0")

            # 2. Transactional batch commit and readback with Unicode / quotes preserved
            committed_count = postgres.psql_scalar(
                f"""
BEGIN;
INSERT INTO repositories(name, root_path) VALUES ('fixture-commit', '/tmp/fixture-commit') RETURNING id \\gset repo_
INSERT INTO runs(repository_id, status) VALUES (:repo_id, 'complete') RETURNING id \\gset run_
{upsert_stmts}
COMMIT;
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
            )
            self.assertEqual(committed_count, "2")

            readback_path = postgres.psql_scalar(
                "SELECT path FROM raw_observations WHERE ordinal = 0;"
            )
            self.assertEqual(readback_path, "src/日本語/🚀_app.py")

            readback_note = postgres.psql_scalar(
                "SELECT (payload_json->'metadata'->'note')::text FROM raw_observations WHERE ordinal = 1;"
            )
            self.assertEqual(json.loads(readback_note), "quote ' test \\ and \n and 🚀 emoji")

            # Each psql call starts a fresh session: bind the committed identities again.
            # 3. Batch replay idempotency
            replayed_count = postgres.psql_scalar(
                f"""
BEGIN;
SELECT id FROM repositories WHERE name = 'fixture-commit'
\\gset repo_
SELECT id FROM runs WHERE repository_id = :repo_id
\\gset run_
{upsert_stmts}
COMMIT;
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
            )
            self.assertEqual(replayed_count, "2")
