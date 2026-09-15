#!/usr/bin/env python3
"""Synthetic, public-safe SCALE7 ingestion measurement helper."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
TOOL_ROOT = REPO_ROOT / "tools"
for import_root in (SOURCE_ROOT, TEST_SUPPORT_ROOT, TOOL_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

import psycopg
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)
from repomap_kg.storage.authority import (
    AttemptNumber,
    OperationId,
)
from repomap_kg.storage.canonical_staging_merge import (
    build_canonical_merge_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_copy import (
    STAGING_COPY_TABLES,
    copy_stage_rows,
)
from repomap_kg.storage.staging_merge import (
    MergeContext,
    build_source_index_merge_statements,
)
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
    DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME,
    require_postgres_binaries,
    temporary_postgres,
)
from scale7_measure_workload import (
    FAMILIES,
    FIXTURE_LABEL,
    MeasurementContractError as MeasurementContractError,
    Workload,
    copy_text_row_bytes,
    prepare_workload,
    stage_rows,
)


STAT_KEYS = (
    "xact_commit",
    "xact_rollback",
    "temp_files",
    "temp_bytes",
    "blk_read_time",
    "blk_write_time",
    "tup_inserted",
    "tup_updated",
    "tup_deleted",
    "wal_bytes",
    "wal_records",
    "wal_fpi",
)


def sql_statement_count(chunks: tuple[str, ...]) -> int:
    """Count semicolon-terminated statements outside SQL string literals."""

    count = 0
    in_quote = False
    for chunk in chunks:
        index = 0
        while index < len(chunk):
            char = chunk[index]
            if in_quote:
                if char == "'" and index + 1 < len(chunk) and chunk[index + 1] == "'":
                    index += 2
                    continue
                if char == "'":
                    in_quote = False
            elif char == "'":
                in_quote = True
            elif char == ";":
                count += 1
            index += 1
    return count


def public_measurement_report(
    *,
    size: int,
    path: str,
    family_rows: dict[str, int],
    statement_count: int,
    encoded_bytes: int,
    elapsed_seconds: float,
    client_cpu_seconds: float,
    client_max_rss_bytes: int,
    postgres_stats: dict[str, int | float],
    mode: str = "unspecified",
    server_statement_count: int | None = None,
    normalized_bytes: int = 0,
) -> dict[str, object]:
    del path
    safe_stats = {key: postgres_stats.get(key, 0) for key in STAT_KEYS}
    return {
        "fixture": FIXTURE_LABEL,
        "mode": mode,
        "size": size,
        "family_rows": {family: int(family_rows.get(family, 0)) for family in FAMILIES},
        "statement_count": int(statement_count),
        "server_statement_count": int(
            statement_count if server_statement_count is None else server_statement_count
        ),
        "normalized_bytes": int(normalized_bytes),
        "encoded_bytes": int(encoded_bytes),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
        "client_cpu_seconds": round(max(0.0, client_cpu_seconds), 6),
        "client_max_rss_bytes": int(max(0, client_max_rss_bytes)),
        "postgres_stats": safe_stats,
    }


def _rusage() -> tuple[float, int]:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss = max(own.ru_maxrss, children.ru_maxrss)
    if sys.platform != "darwin":
        rss *= 1024
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime, rss


def _stats(connection: psycopg.Connection[Any]) -> dict[str, int | float]:
    columns = STAT_KEYS[:9]
    row = connection.execute(
        "SELECT xact_commit, xact_rollback, temp_files, temp_bytes, "
        "blk_read_time, blk_write_time, tup_inserted, tup_updated, tup_deleted "
        "FROM pg_stat_database WHERE datname = current_database()"
    ).fetchone()
    values: dict[str, int | float] = {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in zip(columns, row or (0,) * len(columns))
    }
    try:
        wal = connection.execute(
            "SELECT wal_bytes, wal_records, wal_fpi FROM pg_stat_wal"
        ).fetchone()
    except psycopg.Error:
        connection.rollback()
        wal = None
    values.update(
        {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in zip(STAT_KEYS[9:], wal or (0,) * 3)
        }
    )
    connection.commit()
    return values


def _stats_delta(
    before: dict[str, int | float], after: dict[str, int | float]
) -> dict[str, int | float]:
    return {key: max(0, after.get(key, 0) - before.get(key, 0)) for key in STAT_KEYS}


def _connect(postgres):
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    return psycopg.connect(psycopg.conninfo.make_conninfo("", **params))


def _measure(
    postgres,
    operation,
    *,
    family_rows,
    statement_count,
    normalized_bytes,
    encoded_bytes,
    mode,
    size,
    server_statement_count=None,
):
    with _connect(postgres) as stats_connection:
        before_stats = _stats(stats_connection)
        before_cpu, _ = _rusage()
        started = time.perf_counter()
        operation()
        elapsed = time.perf_counter() - started
        after_cpu, peak_rss = _rusage()
        after_stats = _stats(stats_connection)
    return public_measurement_report(
        size=size,
        path="synthetic-root",
        family_rows=family_rows,
        statement_count=statement_count,
        normalized_bytes=normalized_bytes,
        encoded_bytes=encoded_bytes,
        elapsed_seconds=elapsed,
        client_cpu_seconds=after_cpu - before_cpu,
        client_max_rss_bytes=peak_rss,
        postgres_stats=_stats_delta(before_stats, after_stats),
        mode=mode,
        server_statement_count=server_statement_count,
    )


def _create_stage(postgres, stage_id: str) -> tuple[int, int, StageOwner]:
    repository_id = int(
        postgres.psql_scalar(
            "INSERT INTO repositories(name, root_path) "
            "VALUES ('scale7-fixture', 'scale7-root'); "
            "SELECT id FROM repositories WHERE root_path = 'scale7-root';"
        )
    )
    run_id = int(
        postgres.psql_scalar(
            f"INSERT INTO runs(repository_id, git_commit) VALUES ({repository_id}, "
            "'scale7'); "
            f"SELECT id FROM runs WHERE repository_id = {repository_id} "
            "ORDER BY id DESC LIMIT 1;"
        )
    )
    operation_id = f"operation-{stage_id}"
    postgres.psql_scalar(
        "INSERT INTO ingestion_stages("
        "stage_id, repository_id, operation_id, attempt, execution_mode, "
        "source_generation, config_generation, extractor_generation, "
        "canonicalizer_generation, state, validation_status, expires_at) VALUES ("
        f"'{stage_id}', {repository_id}, '{operation_id}', 1, 'direct', "
        "'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer', "
        "'validated', 'passed', now() + interval '1 hour');"
    )
    owner = StageOwner(
        repository_id=repository_id,
        operation_id=OperationId(operation_id),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )
    return repository_id, run_id, owner


def _run_staged(postgres, workload: Workload) -> dict[str, object]:
    stage_id = f"stage-scale7-{workload.size}"
    repository_id, run_id, owner = _create_stage(postgres, stage_id)
    del repository_id
    rows = stage_rows(workload, stage_id)
    copy_bytes = sum(
        sum(
            len(copy_text_row_bytes(table.adapt_row(row, expected_stage_id=stage_id)))
            for row in rows[family]
        )
        for family, table in STAGING_COPY_TABLES.items()
    )
    context = MergeContext(stage_id, owner, run_id)
    merge_statements = (
        *build_source_index_merge_statements(context),
        *build_canonical_merge_statements(context),
    )

    def operation() -> None:
        with _connect(postgres) as connection:
            for family in FAMILIES:
                copy_stage_rows(
                    connection,
                    STAGING_COPY_TABLES[family],
                    rows[family],
                    expected_stage_id=stage_id,
                )
            for statement in merge_statements:
                connection.execute(statement)
            connection.commit()

    return _measure(
        postgres,
        operation,
        family_rows=workload.family_rows,
        statement_count=len(FAMILIES) + len(merge_statements),
        normalized_bytes=workload.normalized_bytes,
        encoded_bytes=copy_bytes
        + sum(len(statement.encode("utf-8")) for statement in merge_statements),
        mode="copy_set_based_merge",
        size=workload.size,
        server_statement_count=len(FAMILIES) + sql_statement_count(merge_statements),
    )


def measure_size(size: int) -> dict[str, object]:
    require_postgres_binaries()
    workload = prepare_workload(size)
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        staged = _run_staged(postgres, workload)
    return {"size": size, "staged": staged}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", action="append", type=int, dest="sizes")
    parser.add_argument("--pg-container-port", type=int, default=DEFAULT_TEST_POSTGRES_PORT)
    parser.add_argument("--pg-container-runtime", default=DEFAULT_TEST_POSTGRES_RUNTIME)
    args = parser.parse_args()
    sizes = tuple(args.sizes or (4, 16, 64))
    if any(size < 1 or size > 512 for size in sizes):
        parser.error("--size must be between 1 and 512")
    os.environ["REPOMAP_TEST_PG_CONTAINER_PORT"] = str(args.pg_container_port)
    os.environ["REPOMAP_TEST_PG_CONTAINER_RUNTIME"] = args.pg_container_runtime
    print(
        json.dumps(
            {
                "schema": "scale7.synthetic.v2",
                "fixture": FIXTURE_LABEL,
                "results": [measure_size(size) for size in sizes],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
