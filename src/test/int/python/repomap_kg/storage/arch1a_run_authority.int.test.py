from __future__ import annotations

import importlib.util
import json
from typing import TypeVar

import psycopg

from repomap_kg.ops.config import build_graph_storage_status_sql
from repomap_kg.ops.refresh_sql import build_graph_summary_sql, build_refresh_status_sql
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.sql_canonical import build_canonical_storage_summary_query_sql
from repomap_kg.storage.run_authority import (
    build_run_authority_query_sql,
    parse_run_authority,
)
from repomap_test_support.postgres_harness import temporary_postgres


_RowValue = TypeVar("_RowValue")


def _first(row: tuple[_RowValue, ...] | None) -> _RowValue:
    assert row is not None, "Expected a persisted readback row"
    return row[0]


def test_arch1a_receiptless_run_diverges_from_publication_freshness() -> None:
    spec = importlib.util.find_spec("repomap_kg.storage.run_authority")
    assert spec is not None, "ARCH1A requires typed run authority readback"

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
            repository_id = _first(connection.execute(
                "INSERT INTO repositories(name, root_path) "
                "VALUES ('public-repository', '/public/repository') RETURNING id"
            ).fetchone())
            publication_run_id = _first(connection.execute(
                "INSERT INTO runs("
                "repository_id, status, finished_at, publication_job_id, "
                "publication_attempt, source_generation, config_generation, "
                "extractor_generation, canonicalizer_generation"
                ") VALUES (%s, 'complete', CURRENT_TIMESTAMP, 'job-publication', "
                "1, 'sg1:source', 'cg1:config', 'eg1:extractor', "
                "'kg1:canonicalizer') RETURNING id",
                (repository_id,),
            ).fetchone())
            import_run_id = _first(connection.execute(
                "INSERT INTO runs(repository_id, status, finished_at) "
                "VALUES (%s, 'complete', CURRENT_TIMESTAMP) RETURNING id",
                (repository_id,),
            ).fetchone())
            connection.execute(
                "INSERT INTO raw_observations("
                "repository_id, run_id, ordinal, schema_version, kind, source_id, "
                "path, payload_json, payload_hash"
                ") VALUES "
                "(%s, %s, 0, 1, 'file', 'published.py', 'published.py', "
                "'{}'::jsonb, %s), "
                "(%s, %s, 0, 1, 'file', 'imported.py', 'imported.py', "
                "'{}'::jsonb, %s)",
                (
                    repository_id,
                    publication_run_id,
                    "1" * 64,
                    repository_id,
                    import_run_id,
                    "2" * 64,
                ),
            )

            authority_payload = json.loads(_first(connection.execute(
                build_run_authority_query_sql("public-repository")
            ).fetchone()))
            payloads = (
                json.loads(_first(connection.execute(
                    build_refresh_status_sql(
                        [("public", "public-repository")]
                    )
                ).fetchone()))["graphs"][0],
                json.loads(_first(connection.execute(
                    build_graph_summary_sql("public-repository")
                ).fetchone())),
                json.loads(_first(connection.execute(
                    build_graph_storage_status_sql(["public-repository"])
                ).fetchone()))["graphs"][0],
                json.loads(_first(connection.execute(
                    build_canonical_storage_summary_query_sql("/public/repository")
                ).fetchone())),
                json.loads(_first(connection.execute(
                    build_canonical_storage_summary_query_sql("/public/repository")
                ).fetchone())),
            )

    for payload in payloads:
        assert "run_authority" not in payload

    assert payloads[0]["latest_run_id"] == import_run_id
    assert payloads[1]["latest_run_id"] == import_run_id
    assert payloads[2]["latest_run_raw_observations"] == 1
    assert payloads[3]["latest_run_raw_observations"] == 1
    assert payloads[4]["latest_run_id"] == import_run_id

    snapshot = parse_run_authority(authority_payload)
    assert snapshot.latest_recorded_run is not None
    assert snapshot.latest_recorded_run.run_id == import_run_id
    assert snapshot.latest_successful_import is not None
    assert snapshot.latest_successful_import.run_id == import_run_id
    assert snapshot.latest_receipt_bearing_publication is not None
    assert snapshot.latest_receipt_bearing_publication.run_id == publication_run_id
