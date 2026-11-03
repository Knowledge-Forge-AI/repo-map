"""Disposable PostgreSQL import, exact-read, and maintained HNSW observation.

The optional experiment is deliberately a consumer of the evaluator-owned
ANN/lifecycle contracts. It never accepts a caller-supplied index name,
publication JSON, or unscoped candidate query as proof of native execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
import re
from typing import Any, Protocol

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.semantic_candidate_import import (
    build_embedding_import_sql,
    candidate_schema_sql,
)
from common_lore_index.storage.semantic_candidate_readback import query_semantic_candidates
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication,
    CandidateQuery,
    CandidateResult,
    EmbeddingProfile,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_ann import HnswResult
from retrieval_semantic_ann_contracts import HnswIndexCatalogState
from retrieval_semantic_ann_lifecycle import HnswCreationReceipt
from retrieval_semantic_ann_scope import match_candidate_publication
from retrieval_semantic_ann_sql import (
    DEFAULT_OWNER_IDENTITY,
    HnswIndexSpec,
    build_hnsw_index_catalog_sql,
)
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal
from retrieval_semantic_generator_output import GeneratedEnrichmentArtifact
from retrieval_semantic_provenance import VerifiedPublicationPin


READ_ROLE = "w5_experiment_reader"
WRITE_ROLE = "w5_experiment_enrichment"
HNSW_OWNER_ROLE = DEFAULT_OWNER_IDENTITY
_ROLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class PostgresHandle(Protocol):
    """Minimal disposable fixture surface; no arbitrary connection is accepted."""

    psql_command: str
    psql_args: Sequence[str]

    def psql_scalar(self, sql: str) -> str: ...


@dataclass(frozen=True, slots=True)
class HnswObservation:
    """Legacy experiment envelope carrying the maintained evaluator result."""

    cell: ExperimentCell
    plan: object
    plan_sha256: str
    candidates: tuple[dict[str, Any], ...] = ()
    result: HnswResult | None = None


def _role_sql(role: str) -> str:
    if type(role) is not str or _ROLE.fullmatch(role) is None:
        raise ExperimentRefusal("invalid_postgres_role")
    return '"' + role + '"'


def execute_sql(postgres: PostgresHandle, sql: str, *, role: str | None = None) -> None:
    text = (f"SET ROLE {_role_sql(role)};\n" if role is not None else "") + sql
    run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=text,
    )


def _output(postgres: PostgresHandle, sql: str, *, role: str, label: str) -> str:
    result = run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=f"SET ROLE {_role_sql(role)};\n{sql}",
    )
    output = result.stdout.strip()
    if not output:
        raise StorageSchemaError(f"psql did not return {label} as JSON")
    return output


def _json_object(postgres: PostgresHandle, sql: str, *, role: str, label: str) -> dict[str, Any]:
    raw = _output(postgres, sql, role=role, label=label)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageSchemaError(f"{label} did not return an object") from exc
    if not isinstance(value, dict):
        raise StorageSchemaError(f"{label} did not return an object")
    return value


def _json_array(postgres: PostgresHandle, sql: str, *, role: str, label: str) -> list[Any]:
    raw = _output(postgres, sql, role=role, label=label)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageSchemaError(f"{label} did not return an array") from exc
    if not isinstance(value, list):
        raise StorageSchemaError(f"{label} did not return an array")
    return value


def _catalog(
    postgres: PostgresHandle, spec: HnswIndexSpec, *, label: str
) -> HnswIndexCatalogState:
    payload = _json_object(
        postgres,
        build_hnsw_index_catalog_sql(spec),
        role=spec.owner_identity,
        label=label,
    )
    try:
        return HnswIndexCatalogState.from_json(payload)
    except (TypeError, ValueError) as exc:
        raise StorageSchemaError(f"{label} was malformed") from exc


def install_candidate_schema(postgres: PostgresHandle) -> None:
    """Install only the already-present extension and invocation-owned schema."""
    available = postgres.psql_scalar(
        "SELECT count(*) FROM pg_available_extension_versions "
        "WHERE name = 'vector' AND version = '0.8.7'"
    )
    if available != "1":
        raise ExperimentRefusal("extension_unsupported")
    execute_sql(
        postgres,
        f"CREATE ROLE {_role_sql(READ_ROLE)} NOLOGIN; "
        f"CREATE ROLE {_role_sql(WRITE_ROLE)} NOLOGIN; "
        f"CREATE ROLE {_role_sql(HNSW_OWNER_ROLE)} NOLOGIN; "
        "CREATE SCHEMA repomap_vector; "
        "CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';",
    )
    execute_sql(
        postgres,
        candidate_schema_sql(read_principal=READ_ROLE, enrichment_principal=WRITE_ROLE),
    )
    execute_sql(
        postgres,
        f"ALTER TABLE repomap_enrichment.rebuilds OWNER TO {_role_sql(HNSW_OWNER_ROLE)}; "
        f"ALTER TABLE repomap_enrichment.embeddings OWNER TO {_role_sql(HNSW_OWNER_ROLE)}; "
        f"GRANT USAGE, CREATE ON SCHEMA repomap_enrichment TO {_role_sql(HNSW_OWNER_ROLE)}; "
        f"GRANT USAGE ON SCHEMA repomap_vector TO {_role_sql(HNSW_OWNER_ROLE)}; "
        f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA repomap_vector TO {_role_sql(HNSW_OWNER_ROLE)}; "
        f"GRANT SELECT ON public.repositories, public.runs, public.canonical_nodes, "
        f"public.canonical_evidence, public.canonical_node_evidence TO {_role_sql(HNSW_OWNER_ROLE)};",
    )


def import_generation(
    postgres: PostgresHandle,
    publication: CandidatePublication,
    artifact: GeneratedEnrichmentArtifact,
    *,
    rebuild_id: str,
) -> None:
    if _IDENTITY.fullmatch(rebuild_id) is None:
        raise ExperimentRefusal("invalid_rebuild_id")
    entries = artifact.require_importable()
    sql = build_embedding_import_sql(
        publication,
        artifact.profile,
        entries,
        rebuild_id=rebuild_id,
        enrichment_principal=WRITE_ROLE,
        public_safe=True,
    )
    execute_sql(postgres, sql, role=WRITE_ROLE)


def _query(postgres: PostgresHandle, query: CandidateQuery) -> CandidateResult:
    previous = os.environ.get("PGOPTIONS")
    previous_driver = os.environ.get("REPOMAP_STORAGE_READBACK_DRIVER")
    try:
        os.environ["PGOPTIONS"] = f"-c role={READ_ROLE} -c default_transaction_read_only=on"
        os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] = "psql"
        return query_semantic_candidates(
            postgres.psql_args,
            query=query,
            psql_command=postgres.psql_command,
        )
    finally:
        if previous is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous
        if previous_driver is None:
            os.environ.pop("REPOMAP_STORAGE_READBACK_DRIVER", None)
        else:
            os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] = previous_driver


def _scope_for_query(
    query: CandidateQuery, pin: VerifiedPublicationPin
) -> tuple[tuple[str, str], ...]:
    try:
        match_candidate_publication(query.publication, pin)
        binding_id = query.source_binding_id
        if binding_id is None:
            raise ExperimentRefusal("selected_source_binding_required")
        if binding_id in pin.denied_bindings:
            raise ExperimentRefusal("source_scope_refused")
        if binding_id not in pin.admitted_public_bindings:
            raise ExperimentRefusal("unknown_source_binding")
        selected = pin.snapshot_by_binding().get(binding_id)
        if selected is None:
            raise ExperimentRefusal("source_snapshot_unavailable")
        return ((binding_id, selected[1]),)
    except ExperimentRefusal:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "publication_pin_invalid")
        raise ExperimentRefusal(code if isinstance(code, str) else "publication_pin_invalid") from exc


def exact_candidates(
    postgres: PostgresHandle,
    publication: CandidatePublication,
    profile: EmbeddingProfile,
    *,
    rebuild_id: str,
    vector: tuple[float, ...],
    task_id: str,
    publication_pin: VerifiedPublicationPin | None = None,
    source_binding_id: str | None = None,
    limit: int = 20,
    evidence_limit: int = 5,
) -> tuple[ExperimentCell, tuple[dict[str, Any], ...]]:
    if publication_pin is None or source_binding_id is None:
        return (
            ExperimentCell(
                "exact_vector", task_id, ExecutionState.REFUSED,
                "exact_source_scope_required", cleanup_status="not_applicable",
            ),
            (),
        )
    query = CandidateQuery(
        publication, profile, rebuild_id, vector, selected=True, limit=limit,
        evidence_limit=evidence_limit, source_binding_id=source_binding_id,
    )
    try:
        _scope_for_query(query, publication_pin)
        result = _query(postgres, query)
        publication_pin.revalidate_current()
    except ExperimentRefusal as exc:
        return (
            ExperimentCell("exact_vector", task_id, ExecutionState.REFUSED, exc.code,
                           cleanup_status="not_applicable"),
            (),
        )
    except StorageSchemaError as exc:
        return (
            ExperimentCell("exact_vector", task_id, ExecutionState.FAILED, type(exc).__name__,
                           cleanup_status="not_applicable"),
            (),
        )
    except (TypeError, ValueError):
        return (
            ExperimentCell("exact_vector", task_id, ExecutionState.REFUSED,
                           "invalid_exact_query", cleanup_status="not_applicable"),
            (),
        )
    if result.status != "ok":
        return (
            ExperimentCell("exact_vector", task_id, ExecutionState.UNAVAILABLE, result.reason,
                           cleanup_status="not_applicable"),
            (),
        )
    return (
        ExperimentCell("exact_vector", task_id, ExecutionState.COMPLETED,
                       cleanup_status="not_applicable"),
        tuple(result.candidates),
    )


from repomap_test_support.w5_experiment_ann import (
    cleanup_hnsw_index,
    create_hnsw_index,
    hnsw_candidates,
)


__all__ = (
    "HNSW_OWNER_ROLE", "HnswCreationReceipt", "HnswObservation", "READ_ROLE", "WRITE_ROLE",
    "cleanup_hnsw_index", "create_hnsw_index", "exact_candidates", "execute_sql",
    "hnsw_candidates", "import_generation", "install_candidate_schema",
)
