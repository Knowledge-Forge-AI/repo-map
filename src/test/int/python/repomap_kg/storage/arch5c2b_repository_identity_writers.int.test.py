from __future__ import annotations

import psycopg

from repomap_kg.observations import RawObservation
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_arch5c2b_stable_writer_relocates_and_historical_writer_remains_compatible() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            row = connection.execute(
                """
INSERT INTO repositories(name, root_path, repository_identity)
VALUES (%s, %s, %s)
RETURNING id
""",
                ("fixture-old", "/workspace/old", "repo1:fixture"),
            ).fetchone()
            assert row is not None
            repository_id = row[0]

        stable = run_staged_full_refresh(
            postgres.psql_args,
            _observations(),
            repository_name="fixture",
            root_path="/workspace/current",
            repository_identity="repo1:fixture",
            authority=_authority("arch5c2b-stable"),
        )
        historical = publish_observation_generation(
            postgres.psql_args,
            _observations(),
            repository_name="fixture",
            root_path="/workspace/current",
            psql_command=postgres.psql_command,
        )
        with psycopg.connect(conninfo) as connection:
            rows = connection.execute(
                "SELECT id, name, root_path, repository_identity FROM repositories"
            ).fetchall()

    assert stable.repository_id == repository_id
    assert historical.repository_id == repository_id
    assert rows == [
        (repository_id, "fixture", "/workspace/current", "repo1:fixture")
    ]


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="arch5c2b-fixture",
            extractor_version="1.0.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        ),
    )


def _authority(operation_id: str) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(operation_id),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:arch5c2b-source",
        config_generation="cg1:arch5c2b-config",
        extractor_generation="eg1:arch5c2b-extractor",
        canonicalizer_generation="kg1:arch5c2b-canonicalizer",
    )
