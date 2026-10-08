"""Configured graph storage fencing using stable repository identity."""

from __future__ import annotations

from typing import Any

from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.generations import configured_graph
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.storage.readback_driver import (
    _import_psycopg, _psycopg_connection_params_from_psql_args, psycopg_connection_params,
)
from repomap_kg.storage._staged_ingestion_stages import _ensure_repository
from repomap_kg.storage.publication_fencing import build_graph_publication_fence_statements
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId


def install_graph_publication_fence(
    resolver: Any, claim: object, *, reconciler_instance_id: str,
    reconciler_epoch: int, prior_lease_epoch: int,
    replacement_lease_epoch: int | None = None,
) -> bool:
    graph_id = getattr(claim, "graph_id")
    snapshot = resolver._snapshot(graph_id, discover_source=False)
    if snapshot.config_generation != getattr(claim, "config_generation"):
        raise PublicationRouteChangedError("configured storage route changed")
    claim_lease_epoch = getattr(claim, "graph_lease_fencing_epoch")
    if prior_lease_epoch == 0:
        if claim_lease_epoch != 0 or replacement_lease_epoch is None or replacement_lease_epoch <= 0:
            raise ValueError("replacement_lease_epoch is required and must be positive for exact legacy zeros")
        effective_lease_epoch = replacement_lease_epoch
    else:
        if replacement_lease_epoch is not None:
            raise ValueError("replacement_lease_epoch is only permitted for exact legacy zeros")
        if prior_lease_epoch <= 0 or prior_lease_epoch != claim_lease_epoch:
            raise ValueError("durable graph lease epoch is unavailable or mismatched")
        effective_lease_epoch = prior_lease_epoch
    params = psycopg_connection_params(
        _psycopg_connection_params_from_psql_args(snapshot.psql_args), snapshot.password,
    )
    graph = configured_graph(load_ops_config(resolver._config_path), graph_id, require_enabled=False)
    with _import_psycopg().connect(**params) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '250ms'")
            cursor.execute("SET LOCAL statement_timeout = '1000ms'")
            repository_id = _ensure_repository(
                connection, graph.repository_name, f"graph:{graph_id}",
                str(configured_repository_identity(graph_id)),
            )
            owner = StageOwner(
                repository_id=repository_id, operation_id=OperationId(str(getattr(claim, "job_id"))),
                job_id=JobId(str(getattr(claim, "job_id"))), attempt=AttemptNumber(int(getattr(claim, "attempt"))),
                execution_mode="coordinator", coordinator_instance_id=reconciler_instance_id,
                singleton_fencing_epoch=reconciler_epoch, graph_lease_fencing_epoch=effective_lease_epoch,
                **{key: str(getattr(claim, key)) for key in (
                    "source_generation", "config_generation", "extractor_generation", "canonicalizer_generation",
                )},
            )
            for statement in build_graph_publication_fence_statements(owner):
                cursor.execute(statement)
            cursor.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, "
                "coordinator_instance_id, job_id, attempt FROM graph_publication_authority "
                "WHERE repository_id = %s FOR UPDATE", (repository_id,),
            )
            if cursor.fetchone() != (
                reconciler_epoch, effective_lease_epoch, reconciler_instance_id,
                getattr(claim, "job_id"), getattr(claim, "attempt")
            ):
                raise RuntimeError("graph publication fence readback mismatch")
        connection.commit()
    return True
