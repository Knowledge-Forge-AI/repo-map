"""Bounded authoritative readback for coordinator publication receipts."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from repomap_kg.storage.authority import AttemptNumber, GraphRunId, JobId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import parse_psql_json, run_psql
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)


@dataclass(frozen=True)
class RunPublicationRecord:
    """One completed graph run and its exact coordinator receipt."""

    run_id: GraphRunId
    receipt: RunPublicationReceipt

    def publication_authority_marker(self) -> dict[str, str]:
        return {
            "latest_receipt_bearing_publication_identity": f"run-{self.run_id}",
            **{
                key: str(value)
                for key, value in zip(
                    self.receipt.generations.field_names(),
                    self.receipt.generations.values(),
                    strict=True,
                )
            },
            **{key: str(value) for key, value in self.receipt.public_mapping().items()},
        }

    def marker(self) -> dict[str, str]:
        """Return the established coordinator compatibility marker."""

        return {
            "latest_run_identity": f"run-{self.run_id}",
            **{
                key: str(value)
                for key, value in self.receipt.to_mapping().items()
                if key not in {"publication_job_id", "publication_attempt"}
            },
        }


def read_run_publication(
    psql_args: Sequence[str],
    *,
    job_id: str,
    attempt: int,
    psql_command: str = "psql",
    env: dict[str, str] | None = None,
) -> RunPublicationRecord | None:
    """Read at most one completed run by exact publication attempt."""

    identity = RunPublicationAttempt(
        JobId(job_id), AttemptNumber(attempt)
    ).validate()
    safe_job_id = identity.job_id.replace("'", "''")
    fields = ", ".join(
        f"'{field}', {field}" for field in RunPublicationReceipt.field_names()
    )
    sql = (
        "SELECT COALESCE((SELECT json_build_object("
        f"'run_id', id, {fields})::text FROM runs "
        f"WHERE publication_job_id = '{safe_job_id}' "
        f"AND publication_attempt = {identity.attempt} "
        "AND status = 'complete'), 'null');"
    )
    completed = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=env,
    )
    payload = parse_psql_json(completed.stdout, "publication receipt")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed publication receipt")
    try:
        receipt = publication_receipt_from_mapping(payload)
        if receipt is None:
            raise ValueError("missing publication receipt")
        run_id = int(payload["run_id"])
        if run_id <= 0:
            raise ValueError("invalid run identity")
        return RunPublicationRecord(GraphRunId(run_id), receipt)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError(
            "psql returned a malformed publication receipt"
        ) from error


def read_latest_receipt_bearing_publication(
    psql_args: Sequence[str],
    *,
    psql_command: str = "psql",
    env: dict[str, str] | None = None,
) -> RunPublicationRecord | None:
    """Read the newest complete run carrying one full publication receipt."""

    fields = ", ".join(
        f"'{field}', {field}" for field in RunPublicationReceipt.field_names()
    )
    receipt_fields = " AND ".join(
        f"{field} IS NOT NULL" for field in RunPublicationReceipt.base_field_names()
    )
    sql = (
        "SELECT COALESCE((SELECT json_build_object("
        f"'run_id', id, {fields})::text FROM runs "
        "WHERE status = 'complete' "
        f"AND {receipt_fields} "
        "ORDER BY id DESC LIMIT 1), 'null');"
    )
    completed = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=env,
    )
    payload = parse_psql_json(completed.stdout, "latest publication receipt")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed publication receipt")
    try:
        receipt = publication_receipt_from_mapping(payload)
        if receipt is None:
            raise ValueError("missing publication receipt")
        run_id = int(payload["run_id"])
        if run_id <= 0:
            raise ValueError("invalid run identity")
        return RunPublicationRecord(GraphRunId(run_id), receipt)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError(
            "psql returned a malformed publication receipt"
        ) from error


read_latest_publication = read_latest_receipt_bearing_publication


__all__ = [
    "RunPublicationRecord",
    "read_latest_publication",
    "read_latest_receipt_bearing_publication",
    "read_run_publication",
]
