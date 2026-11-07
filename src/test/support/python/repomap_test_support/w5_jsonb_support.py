"""Cohesive test support for the W5 disposable PostgreSQL JSONB evidence experiment (ADR 0137)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from common_lore_index.ops.config_local import local_graph_binding
from common_lore_index.ops.config import OpsConfig
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.readback_credentials import psql_environment
from common_lore_index.storage.readback_driver import execute_json_readback
from retrieval_jsonb_evidence import (
    GIN_OPS_INDEX,
    GIN_PATH_OPS_INDEX,
    JsonbFacetFilter,
    NamedEvidenceWorkloadItem,
    NodeLocationsQuery,
)

__all__ = [
    "GIN_OPS_INDEX",
    "GIN_PATH_OPS_INDEX",
    "JsonbFacetFilter",
    "NamedEvidenceWorkloadItem",
    "NodeLocationsQuery",
    "build_mixed_v1_jsonb_workload",
    "make_postgres_jsonb_executors",
    "make_synthetic_explain_json",
    "make_synthetic_node_locations_raw_payload",
]


def make_postgres_jsonb_executors(
    config: OpsConfig,
    graph_id: str,
    *,
    psql_command: str = "psql",
) -> tuple[
    Callable[[str], Mapping[str, Any]],
    Callable[[str], None],
    Callable[[str], Sequence[Any]],
    str,
    str,
]:
    """Bind disposable PostgreSQL psql executors and repository identity for a configured graph."""
    graph = next(c for c in config.graphs if c.id == graph_id)
    database = graph.database or config.postgres.database
    psql_args = tuple(config.postgres.psql_args_for_database(database))
    password = config.postgres.password
    binding = local_graph_binding(graph)

    def json_executor(sql: str) -> Mapping[str, Any]:
        res = execute_json_readback(
            sql,
            psql_args=psql_args,
            psql_command=psql_command,
            label="w5_jsonb_json",
            expected_shape="object",
            password=password,
        )
        assert isinstance(res, Mapping)
        return res

    def ddl_executor(sql: str) -> None:
        run_psql(
            [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
            input_text=sql,
            env=psql_environment(password),
        )

    def explain_executor(sql: str) -> Sequence[Any]:
        explain_sql = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" + sql
        res = execute_json_readback(
            explain_sql,
            psql_args=psql_args,
            psql_command=psql_command,
            label="w5_jsonb_explain",
            expected_shape="array",
            password=password,
        )
        assert isinstance(res, Sequence)
        return res

    return json_executor, ddl_executor, explain_executor, str(binding.repository_identity), str(binding.root_path)


def build_mixed_v1_jsonb_workload(
    *,
    primary_key: str,
    secondary_key: str = "file:core/pkg/pipeline.py",
    core_binding_id: str,
    core_snapshot_id: str,
    sample_relative_path: str = "pkg/pipeline.py",
) -> tuple[NamedEvidenceWorkloadItem, ...]:
    """Construct the predeclared named node-evidence workload over mixed-v1."""
    return (
        NamedEvidenceWorkloadItem(
            workload_id="direct_unfiltered_std",
            query=NodeLocationsQuery(canonical_key=primary_key, evidence_role="direct", limit=5),
            context_identity=False,
        ),
        NamedEvidenceWorkloadItem(
            workload_id="direct_unfiltered_ctx_id",
            query=NodeLocationsQuery(canonical_key=primary_key, evidence_role="direct", limit=5),
            context_identity=True,
        ),
        NamedEvidenceWorkloadItem(
            workload_id="all_roles_with_history",
            query=NodeLocationsQuery(canonical_key=primary_key, evidence_role="all", limit=10),
            context_identity=True,
        ),
        NamedEvidenceWorkloadItem(
            workload_id="facet_binding_snapshot_containment",
            query=NodeLocationsQuery(canonical_key=primary_key, evidence_role="all", limit=5),
            context_identity=True,
            facet_filter=JsonbFacetFilter(binding_id=core_binding_id, snapshot_id=core_snapshot_id),
        ),
        NamedEvidenceWorkloadItem(
            workload_id="facet_binding_snapshot_and_path",
            query=NodeLocationsQuery(canonical_key=secondary_key, evidence_role="direct", limit=5),
            context_identity=True,
            facet_filter=JsonbFacetFilter(
                binding_id=core_binding_id,
                snapshot_id=core_snapshot_id,
                source_relative_path=sample_relative_path,
            ),
        ),
        NamedEvidenceWorkloadItem(
            workload_id="facet_nonmatching_path_empty",
            query=NodeLocationsQuery(canonical_key=primary_key, evidence_role="direct", limit=5),
            context_identity=True,
            facet_filter=JsonbFacetFilter(
                binding_id=core_binding_id,
                snapshot_id=core_snapshot_id,
                source_relative_path="pkg/does_not_exist.py",
            ),
        ),
        NamedEvidenceWorkloadItem(
            workload_id="missing_node_unavailable",
            query=NodeLocationsQuery(canonical_key="file:nonexistent/missing.py", evidence_role="direct", limit=5),
            context_identity=True,
            expected_status="unavailable",
        ),
    )


def make_synthetic_node_locations_raw_payload(
    *,
    run_id: int = 1,
    generation: int = 1,
    binding_id: str = "bind1:" + ("1" * 64),
    snapshot_id: str = "snap1:" + ("a" * 64),
    source_relative_path: str = "pkg/pipeline.py",
    projection_stale: bool = False,
    malformed_metadata_count: int = 0,
    transport_overflow: bool = False,
    has_accepted: bool = True,
    has_node: bool = True,
) -> dict[str, Any]:
    """Build a synthetic raw SQL JSON readback payload for unit testing decode and equality gates."""
    ch = "a" if generation == 1 else "b"
    h64 = ch * 64
    row = {
        "evidence_key": "ev:1",
        "link_kind": "defined_in",
        "run_id": run_id,
        "raw_observation_ordinal": 1,
        "payload_hash": f"sha256:{h64}",
        "raw_kind": "symbol",
        "raw_source_id": "src:1",
        "path": f"core/{source_relative_path}",
        "start_line": 10,
        "end_line": 20,
        "extractor": "python-ast",
        "extractor_version": "1.0",
        "confidence": "1.0",
        "metadata_json": {
            "binding_id": binding_id,
            "snapshot_id": snapshot_id,
            "source_relative_path": source_relative_path,
        },
        "publication_bundle_id": f"bundle1:{h64}",
        "snapshot_manifest_id": f"snapmanifest1:{h64}",
        "extraction_receipt_id": f"receipt1:{h64}",
        "graph_candidate_id": f"cand1:{h64}",
        "snapshot_vector_json": [[binding_id, generation, snapshot_id]],
        "evidence_role": "direct",
    }
    return {
        "has_accepted": has_accepted,
        "projection_stale": projection_stale,
        "malformed_metadata_count": malformed_metadata_count,
        "transport_overflow": transport_overflow,
        "accepted": {
            "run_id": run_id,
            "generation": generation,
            "publication_bundle_id": f"bundle1:{h64}",
            "snapshot_manifest_id": f"snapmanifest1:{h64}",
            "extraction_receipt_id": f"receipt1:{h64}",
            "graph_candidate_id": f"cand1:{h64}",
            "snapshot_vector_json": [[binding_id, generation, snapshot_id]],
        } if has_accepted else None,
        "has_node": has_node,
        "node": {
            "id": 101,
            "kind": "class",
            "display_name": "RetrievalPipeline",
            "metadata_json": {"binding_id": binding_id, "snapshot_id": snapshot_id, "source_relative_path": source_relative_path},
            "first_seen_run_id": 1,
            "last_seen_run_id": run_id,
        } if has_node else None,
        "selected_run_id": run_id if has_node else None,
        "current_rows": [row] if has_node and not transport_overflow else [],
        "historical_rows": [],
    }


def make_synthetic_explain_json(*, used_gin: bool = False, index_name: str | None = None) -> list[dict[str, Any]]:
    """Build a synthetic PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) payload for unit tests."""
    child_plan: dict[str, Any] = {
        "Node Type": "Bitmap Index Scan" if used_gin else "Seq Scan",
        "Total Cost": 4.25,
        "Actual Rows": 1,
        "Shared Hit Blocks": 3,
        "Shared Read Blocks": 1,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0,
    }
    if index_name is not None:
        child_plan["Index Name"] = index_name
    elif used_gin:
        child_plan["Index Name"] = GIN_OPS_INDEX
    return [
        {
            "Planning Time": 0.15,
            "Execution Time": 0.42,
            "Plan": {
                "Node Type": "Result",
                "Total Cost": 8.5,
                "Actual Rows": 1,
                "Shared Hit Blocks": 5,
                "Shared Read Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0,
                "Plans": [child_plan],
            },
        }
    ]
