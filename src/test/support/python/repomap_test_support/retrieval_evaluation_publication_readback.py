"""Low-dependency matched PostgreSQL publication readback for evaluator support."""

from __future__ import annotations

from collections.abc import Mapping

from common_lore_index.ops.config_local import local_graph_binding
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference
from common_lore_index.storage.context_postgres_identity import (
    format_postgres_accepted_publication,
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from common_lore_index.storage.readback_driver import execute_json_readback


def sqlite_publication_mapping(
    accepted: AcceptedPublicationReference,
    receipt: RunPublicationReceipt,
) -> dict[str, object]:
    """Format identity read with its receipt in one verified SQLite transaction."""
    portable = receipt.portable
    if portable is None or accepted.accepted_generation is None:
        raise ValueError("accepted SQLite publication is incomplete")
    return {
        "run_id": accepted.run_id,
        "generation": accepted.accepted_generation,
        "job_id": str(receipt.attempt.job_id),
        "attempt": int(receipt.attempt.attempt),
        "publication_bundle_id": portable.publication_bundle_id,
        "snapshot_manifest_id": portable.snapshot_manifest_id,
        "extraction_receipt_id": portable.extraction_receipt_id,
        "graph_candidate_id": portable.candidate_id,
        "snapshot_vector": [list(item) for item in portable.snapshot_vector],
        "source_generation": str(receipt.generations.source_generation),
        "config_generation": str(receipt.generations.config_generation),
        "extractor_generation": str(receipt.generations.extractor_generation),
        "canonicalizer_generation": str(receipt.generations.canonicalizer_generation),
    }


def read_postgres_matched_accepted_publication(
    config: OpsConfig,
    graph_id: str = "mixed-v1",
    *,
    psql_command: str = "psql",
) -> tuple[AcceptedPublicationReference, RunPublicationReceipt, dict[str, object]]:
    """Read the matched-repository accepted PostgreSQL run and portable receipt."""
    graph = next((c for c in config.graphs if c.id == graph_id), None)
    if graph is None:
        raise ValueError(f"unknown graph_id {graph_id!r}")
    database = graph.database or config.postgres.database
    psql_args = config.postgres.psql_args_for_database(database)
    binding = local_graph_binding(graph)
    repo_pred = postgres_repo_predicate_sql(
        str(binding.repository_identity), str(binding.root_path), context_identity=True
    )
    receipt_fields = ", ".join(
        f"'{field}', r.{field}" for field in RunPublicationReceipt.field_names()
    )
    sql = (
        f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {repo_pred} ORDER BY repo.id DESC LIMIT 1),\n"
        f"{postgres_accepted_run_cte_sql(context_identity=True)}\n"
        f"SELECT json_build_object(\n"
        f"  'accepted', (SELECT {postgres_accepted_json_sql(context_identity=True)} FROM accepted_run acc),\n"
        f"  'receipt_row', (SELECT json_build_object({receipt_fields}) FROM public.runs r JOIN accepted_run acc ON r.id = acc.run_id JOIN matched_repo mr ON mr.repository_id = r.repository_id WHERE r.status = 'complete')\n"
        f")::text;"
    )
    payload = execute_json_readback(
        sql,
        psql_args=psql_args,
        psql_command=psql_command,
        label="w5_pg_accepted_publication",
        expected_shape="object",
        password=config.postgres.password,
    )
    if not isinstance(payload, dict):
        raise LookupError(f"PostgreSQL graph {graph_id!r} has no accepted portable publication")
    accepted = payload.get("accepted")
    receipt_row = payload.get("receipt_row")
    if not isinstance(accepted, Mapping) or not isinstance(receipt_row, Mapping):
        raise LookupError(f"PostgreSQL graph {graph_id!r} has no accepted portable publication")
    formatted_acc = format_postgres_accepted_publication(accepted, context_identity=True)
    receipt = publication_receipt_from_mapping(dict(receipt_row))
    if receipt is None or receipt.portable is None:
        raise LookupError(f"PostgreSQL graph {graph_id!r} has no accepted portable publication")
    portable = receipt.portable
    candidate_id = formatted_acc.get("graph_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise LookupError("accepted publication candidate identity missing")
    snap_vec = [
        [item["binding_id"], item.get("binding_revision", item.get("revision")), item["snapshot_id"]]
        if isinstance(item, Mapping) else list(item)
        for item in (formatted_acc.get("snapshot_vector") or ())
    ]
    pub_map: dict[str, object] = {
        "run_id": int(formatted_acc["run_id"]),
        "generation": int(formatted_acc["generation"]),
        "job_id": str(receipt.attempt.job_id),
        "attempt": int(receipt.attempt.attempt),
        "publication_bundle_id": str(formatted_acc["publication_bundle_id"]),
        "snapshot_manifest_id": str(formatted_acc["snapshot_manifest_id"]),
        "extraction_receipt_id": str(formatted_acc["extraction_receipt_id"]),
        "graph_candidate_id": candidate_id,
        "snapshot_vector": snap_vec,
        "source_generation": str(receipt.generations.source_generation),
        "config_generation": str(receipt.generations.config_generation),
        "extractor_generation": str(receipt.generations.extractor_generation),
        "canonicalizer_generation": str(receipt.generations.canonicalizer_generation),
    }
    accepted_ref = AcceptedPublicationReference(
        graph_id=graph_id,
        repository_id=binding.repository_identity,
        backend="postgresql",
        run_id=int(formatted_acc["run_id"]),
        publication_bundle_id=portable.publication_bundle_id,
        job_id=str(receipt.attempt.job_id),
        attempt=int(receipt.attempt.attempt),
        accepted_generation=int(formatted_acc["generation"]),
        snapshot_manifest_id=portable.snapshot_manifest_id,
        extraction_receipt_id=portable.extraction_receipt_id,
        trusted_caller=True,
    ).validate()
    return accepted_ref, receipt, pub_map


__all__ = ["read_postgres_matched_accepted_publication", "sqlite_publication_mapping"]
