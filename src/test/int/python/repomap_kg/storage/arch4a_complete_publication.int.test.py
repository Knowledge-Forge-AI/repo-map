from __future__ import annotations

import json
from pathlib import Path

from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _file(path: str, digest: str) -> RawObservation:
    return RawObservation(
        kind="file",
        source_id=path,
        path=path,
        confidence="extracted",
        extractor="fixture-discovery",
        extractor_version="1.0.0",
        metadata={
            "content_hash": digest,
            "generated": False,
            "executable": False,
            "language": "markdown",
            "role": "documentation",
        },
    )


def _load(postgres, jsonl_path: Path) -> tuple[int, str, str]:
    return run_repo_map_in_process(
        "storage",
        "load-files",
        str(jsonl_path),
        "--repository-name",
        "fixture",
        "--root-path",
        "synthetic-root",
        "--pg-host",
        str(postgres.socket_dir),
        "--pg-port",
        str(postgres.port),
        "--pg-user",
        postgres.user,
        "--pg-database",
        postgres.database,
        "--psql-command",
        postgres.psql_command,
        "--json",
    )


def test_arch4a_storage_load_files_publishes_receipt_and_replaces_generation(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    jsonl_path = tmp_path / "observations.jsonl"
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        write_observations_jsonl(
            [_file("README.md", "a" * 64), _file("OLD.md", "b" * 64)],
            jsonl_path,
        )
        first_exit, _, first_error = _load(postgres, jsonl_path)
        write_observations_jsonl([_file("README.md", "c" * 64)], jsonl_path)
        second_exit, second_output, second_error = _load(postgres, jsonl_path)

        receipt = postgres.psql_scalar(
            """
SELECT (publication_job_id IS NOT NULL)::text
       || '|'
       || (publication_attempt IS NOT NULL)::text
       || '|'
       || (source_generation IS NOT NULL)::text
       || '|'
       || (config_generation IS NOT NULL)::text
       || '|'
       || (extractor_generation IS NOT NULL)::text
       || '|'
       || (canonicalizer_generation IS NOT NULL)::text
FROM runs
ORDER BY id DESC
LIMIT 1;
"""
        )
        paths = postgres.psql_scalar(
            """
SELECT string_agg(path, ',' ORDER BY path)
FROM files
WHERE last_seen_run_id = (SELECT max(id) FROM runs);
"""
        )

    assert first_exit == 0, first_error
    assert second_exit == 0, second_error
    assert json.loads(second_output)["files"] == 1
    assert receipt == "true|true|true|true|true|true"
    assert paths == "README.md"
