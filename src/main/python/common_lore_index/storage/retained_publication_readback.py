"""Read-only authoritative proof for one retained portable attempt."""

from __future__ import annotations

import json

from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.readback import execute_ops_json_readback
from common_lore_index.storage.authority import AttemptNumber, GraphRunId, JobId
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.sql_core import sql_literal

_PUBLICATION_FAMILIES = frozenset(
    {
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    }
)


def read_retained_publication(
    config: OpsConfig,
    *,
    database: str,
    repository_identity: str,
    job_id: str,
    attempt: int,
    portable_stage_id: str,
    psql_command: str | None = None,
) -> RunPublicationRecord | None:
    """Read one complete run joined to its exact configured repository."""
    if type(attempt) is not int or attempt <= 0:
        raise StorageSchemaError("invalid retained publication attempt")
    fields = ", ".join(f"'{field}', run.{field}" for field in RunPublicationReceipt.field_names())
    sql = f"""SELECT json_build_object('publication', (
        SELECT json_build_object('run_id', run.id, {fields})
        FROM public.runs run
        JOIN public.repositories repo ON repo.id = run.repository_id
        WHERE repo.repository_identity = {sql_literal(repository_identity)}
          AND run.publication_job_id = {sql_literal(job_id)}
          AND run.publication_attempt = {attempt}
          AND run.portable_stage_id = {sql_literal(portable_stage_id)}
          AND run.status = 'complete'
        ORDER BY run.id DESC LIMIT 1
    ))::text;"""
    payload = execute_ops_json_readback(
        config,
        database=database,
        sql=sql,
        label="retained publication proof",
        expected_shape="object",
        mode="host_then_container",
        psql_command=psql_command,
    )
    if not isinstance(payload, dict) or set(payload) != {"publication"}:
        raise StorageSchemaError("malformed retained publication proof")
    if payload["publication"] is None:
        return None
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        raise StorageSchemaError("malformed retained publication proof")
    try:
        if set(publication) != {"run_id", *RunPublicationReceipt.field_names()}:
            raise ValueError
        run_id = publication.get("run_id")
        _strict_receipt_payload(publication)
        receipt = publication_receipt_from_mapping(publication)
        if type(run_id) is not int or run_id <= 0 or receipt is None:
            raise ValueError
        if receipt.attempt.job_id != JobId(job_id) or receipt.attempt.attempt != AttemptNumber(attempt):
            raise ValueError
        return RunPublicationRecord(GraphRunId(run_id), receipt)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError("malformed retained publication proof") from error


def _strict_receipt_payload(payload: dict[str, object]) -> None:
    integer_fields = {
        "publication_attempt", "portable_singleton_fencing_epoch",
        "portable_graph_lease_fencing_epoch",
    }
    for field in RunPublicationReceipt.field_names():
        value = payload.get(field)
        if field in integer_fields:
            if type(value) is not int:
                raise ValueError
        elif field == "snapshot_vector_json" or field == "family_receipts_json":
            if not isinstance(value, str):
                raise ValueError
            parsed = json.loads(value, object_pairs_hook=_unique_json_object)
            if field == "snapshot_vector_json":
                if not isinstance(parsed, list) or not parsed or any(
                    not isinstance(item, list)
                    or len(item) != 3
                    or not isinstance(item[0], str)
                    or type(item[1]) is not int
                    or not isinstance(item[2], str)
                    for item in parsed
                ):
                    raise ValueError
            elif (
                not isinstance(parsed, dict)
                or set(parsed) != _PUBLICATION_FAMILIES
                or any(
                    not isinstance(item, dict)
                    or set(item) != {"count", "byte_length", "digest"}
                    or type(item.get("count")) is not int
                    or item["count"] < 0
                    or type(item.get("byte_length")) is not int
                    or item["byte_length"] < 0
                    or not isinstance(item.get("digest"), str)
                    or not item["digest"].startswith("sha256:")
                    for item in parsed.values()
                )
            ):
                raise ValueError
        elif not isinstance(value, str):
            raise ValueError


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate publication proof key")
        value[key] = item
    return value


__all__ = ("read_retained_publication",)
