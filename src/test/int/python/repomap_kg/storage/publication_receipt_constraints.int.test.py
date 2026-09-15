import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres


def test_publication_receipt_constraints_are_atomic_and_unique():
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        with psycopg.connect(
            host=postgres.host,
            port=postgres.port,
            user=postgres.user,
            dbname=postgres.database,
            password=postgres.password,
            autocommit=True,
        ) as connection:
            row = connection.execute(
                "INSERT INTO repositories(name, root_path) "
                "VALUES ('fixture', '/public/fixture') RETURNING id"
            ).fetchone()
            assert row is not None
            repository_id = row[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO runs(repository_id, status, source_generation) "
                    "VALUES (%s, 'complete', 'sg1:partial')",
                    (repository_id,),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO runs("
                    "repository_id, status, publication_job_id"
                    ") VALUES (%s, 'complete', 'job-partial')",
                    (repository_id,),
                )
            values = (
                repository_id,
                "job-unique",
                1,
                "sg1:source",
                "cg1:config",
                "eg1:extractor",
                "kg1:canonicalizer",
            )
            sql = (
                "INSERT INTO runs("
                "repository_id, status, publication_job_id, publication_attempt, "
                "source_generation, config_generation, extractor_generation, "
                "canonicalizer_generation) VALUES (%s, 'complete', %s, %s, %s, "
                "%s, %s, %s)"
            )
            connection.execute(sql, values)
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(sql, values)
