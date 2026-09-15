from __future__ import annotations

import json
import scale11_profile_normalized_ingestion as profiler

import psycopg

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)


def _migrate(postgres) -> None:
    apply_migrations(
        default_rdbms_root(),
        postgres.psql_args,
        psql_command=postgres.psql_command,
    )


def _unresolved_stage_count(postgres) -> int:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    conninfo = " ".join(f"{k}={v}" for k, v in params.items())
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT count(*) FROM ingestion_stages "
            "WHERE state <> 'published' OR merge_status <> 'committed' "
            "OR publication_reconciliation_state <> 'reconciled'"
        ).fetchone()
        assert row is not None
        return int(row[0])


def test_profiled_publication_is_receipt_bearing_deterministic_and_clean() -> None:
    require_postgres_binaries()
    workload = profiler.build_workload("mixed", 32)

    with temporary_postgres() as postgres:
        _migrate(postgres)
        first = profiler.profile_publication(
            postgres.psql_args,
            workload,
            repetition=1,
            instrumented=True,
        )
        second = profiler.profile_publication(
            postgres.psql_args,
            workload,
            repetition=2,
            instrumented=True,
        )

        assert _unresolved_stage_count(postgres) == 0

    assert isinstance(first, profiler.ProfileResult)
    assert first.receipt_complete is True
    assert first.cleanup_complete is True
    assert second.generation > first.generation
    assert second.structural_digest == first.structural_digest
    assert tuple(family.family for family in first.families) == FAMILIES
    assert all(family.row_count > 0 for family in first.families)
    assert all(
        family.preparation_seconds.availability == "available"
        and family.checksum_seconds.availability == "available"
            and family.copy_seconds.availability == "available"
            and family.statistics_seconds.reason == "aggregate_scope"
            and family.completeness_validation_seconds.reason == "aggregate_scope"
            and family.semantic_guard_seconds.reason == "aggregate_scope"
            and family.merge_seconds.reason == "aggregate_scope"
            and family.cleanup_seconds.reason == "aggregate_scope"
        for family in first.families
    )
    for category in (
        "statistics_seconds",
        "completeness_validation_seconds",
        "semantic_guard_seconds",
        "merge_seconds",
        "receipt_seconds",
    ):
        assert first.aggregate_metrics[category].availability == "available"
    assert first.aggregate_metrics["cleanup_seconds"].to_payload() == {
        "availability": "unavailable",
        "reason": "not_emitted",
        "value": None,
    }
    assert len(json.dumps(first.to_payload(), sort_keys=True).encode()) < 1_048_576


def test_instrumentation_preserves_seven_family_semantics() -> None:
    require_postgres_binaries()
    workload = profiler.build_workload("mixed", 32)

    with temporary_postgres() as instrumented_postgres:
        _migrate(instrumented_postgres)
        instrumented = profiler.profile_publication(
            instrumented_postgres.psql_args,
            workload,
            repetition=1,
            instrumented=True,
        )
    with temporary_postgres() as plain_postgres:
        _migrate(plain_postgres)
        plain = profiler.profile_publication(
            plain_postgres.psql_args,
            workload,
            repetition=1,
            instrumented=False,
        )

    assert instrumented.structural_digest == plain.structural_digest
    assert tuple(family.row_count for family in instrumented.families) == tuple(
        family.row_count for family in plain.families
    )
    assert all(
        family.preparation_seconds.reason == "instrumentation_disabled"
        for family in plain.families
    )
