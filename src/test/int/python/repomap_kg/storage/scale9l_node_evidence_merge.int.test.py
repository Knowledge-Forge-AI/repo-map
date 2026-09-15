from __future__ import annotations

import psycopg

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.canonical_staging_merge import (
    build_canonical_merge_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_kg.storage.staged_ingestion import (
    _refresh_canonical_node_evidence_statistics,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _create_repository_run_stage(postgres, stage_id: str) -> tuple[int, int]:
    repository_id = int(
        postgres.psql_scalar(
            """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', 'fixture-root');
SELECT id FROM repositories WHERE root_path = 'fixture-root';
"""
        )
    )
    run_id = int(
        postgres.psql_scalar(
            f"""
INSERT INTO runs(repository_id, git_commit)
VALUES ({repository_id}, 'fixture-commit');
SELECT id FROM runs WHERE repository_id = {repository_id};
"""
        )
    )
    postgres.psql_scalar(
        f"""
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, validation_status, expires_at
)
VALUES (
    '{stage_id}', {repository_id}, 'operation-{stage_id}', 1, 'direct',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'validated', 'passed', now() + interval '1 hour'
);
"""
    )
    return repository_id, run_id


def _context(repository_id: int, run_id: int, stage_id: str) -> MergeContext:
    return MergeContext(
        stage_id=stage_id,
        owner=StageOwner(
            repository_id=repository_id,
            operation_id=OperationId(f"operation-{stage_id}"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=run_id,
    )


def _seed_references(connection, repository_id: int, run_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
INSERT INTO canonical_nodes(
    repository_id, graph_key_version, canonical_key, kind, display_name,
    metadata_json, confidence, first_seen_run_id, last_seen_run_id
)
VALUES (%s, 1, 'node:fixture', 'function', 'fixture', '{}'::jsonb,
        'extracted', %s, %s)
""",
            (repository_id, run_id, run_id),
        )
        cursor.execute(
            """
INSERT INTO canonical_evidence(
    repository_id, run_id, graph_key_version, evidence_key,
    raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id,
    path, extractor, extractor_version, confidence, metadata_json
)
VALUES (%s, %s, 1, 'evidence:fixture', 0, 1, 'fixture', 'fixture:source',
        'fixture/root', 'fixture', 'fixture-1', 'extracted', '{}'::jsonb)
""",
            (repository_id, run_id),
        )
        cursor.execute(
            """
INSERT INTO canonical_node_evidence(
    canonical_node_id, canonical_evidence_id, link_kind
)
SELECT node.id, evidence.id, 'definition'
FROM canonical_nodes node
JOIN canonical_evidence evidence
  ON evidence.repository_id = node.repository_id
WHERE node.repository_id = %s
  AND evidence.run_id = %s
""",
            (repository_id, run_id),
        )


def _copy_duplicate_links(connection, stage_id: str) -> None:
    copies_per_link = 1024
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_node_evidence"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": ordinal,
                "graph_key_version": 1,
                "canonical_key": "node:fixture",
                "evidence_key": "evidence:fixture",
                "link_kind": (
                    "definition" if ordinal < copies_per_link else "reference"
                ),
            }
            for ordinal in range(copies_per_link * 2)
        ],
        expected_stage_id=stage_id,
    )


def _plan_nodes(plan: dict[str, object]) -> list[dict[str, object]]:
    nodes = [plan]
    children = plan.get("Plans", [])
    if not isinstance(children, list):
        return nodes
    for child in children:
        if isinstance(child, dict):
            nodes.extend(_plan_nodes(child))
    return nodes


def _final_link_count(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM canonical_node_evidence")
        return int(cursor.fetchone()[0])


def test_node_evidence_merge_avoids_ordered_staged_deduplication() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_id = "stage-node-evidence-merge"
        repository_id, run_id = _create_repository_run_stage(postgres, stage_id)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            _copy_duplicate_links(connection, stage_id)
            _refresh_canonical_node_evidence_statistics(connection)
            _seed_references(connection, repository_id, run_id)
            connection.commit()
            merge = build_canonical_merge_statements(
                _context(repository_id, run_id, stage_id)
            )[8]

            with connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN (FORMAT JSON) {merge}")
                row = cursor.fetchone()
                assert row is not None
                plan_value = row[0]
                assert isinstance(plan_value, list)
                assert plan_value and isinstance(plan_value[0], dict)
                plan = plan_value[0]["Plan"]
                assert isinstance(plan, dict)
            nodes = _plan_nodes(plan)

            assert any(
                node.get("Node Type") in {"Aggregate", "Group"} for node in nodes
            ), [
                f"{node.get('Node Type')}:{node.get('Strategy', '')}"
                for node in nodes
            ]
            assert all(
                node.get("Node Type") not in {"Sort", "Unique"} for node in nodes
            ), [
                f"{node.get('Node Type')}:{node.get('Strategy', '')}"
                for node in nodes
            ]

            with connection.cursor() as cursor:
                cursor.execute(merge)
            connection.commit()

            assert _final_link_count(connection) == 2
