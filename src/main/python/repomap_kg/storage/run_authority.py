"""Explicit recorded-run, import, and publication freshness contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from repomap_kg.storage.authority import GraphRunId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from repomap_kg.storage.psql import parse_psql_json, run_psql
from repomap_kg.storage.sql_core import sql_literal


class RunStatus(StrEnum):
    """Closed durable graph-run status vocabulary."""

    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class RecordedRun:
    """One recorded graph run independent of publication authority."""

    run_id: GraphRunId
    status: RunStatus
    started_at: str
    finished_at: str | None


@dataclass(frozen=True)
class SuccessfulImport(RecordedRun):
    """One complete receiptless compatibility import run."""


@dataclass(frozen=True)
class ReceiptBearingPublication:
    """One complete run carrying the full authoritative publication receipt."""

    run: RecordedRun
    receipt: RunPublicationReceipt

    @property
    def run_id(self) -> GraphRunId:
        return self.run.run_id


@dataclass(frozen=True)
class RunAuthoritySnapshot:
    """The three non-interchangeable latest-run concepts for one repository."""

    latest_recorded_run: RecordedRun | None
    latest_successful_import: SuccessfulImport | None
    latest_receipt_bearing_publication: ReceiptBearingPublication | None


def receipt_presence_predicate(alias: str, *, present: bool) -> str:
    """Return the all-present or all-null publication receipt predicate."""

    operator = "IS NOT NULL" if present else "IS NULL"
    return " AND ".join(
        f"{alias}.{field} {operator}"
        for field in RunPublicationReceipt.base_field_names()
    )


def run_record_json_sql(alias: str, *, include_receipt: bool = False) -> str:
    """Return one bounded JSON run projection for an existing SQL alias."""

    fields = [
        f"'run_id', {alias}.id",
        f"'status', {alias}.status",
        "'started_at', "
        f"to_char({alias}.started_at AT TIME ZONE 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')",
        "'finished_at', "
        f"to_char({alias}.finished_at AT TIME ZONE 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')",
    ]
    if include_receipt:
        fields.extend(
            f"'{field}', {alias}.{field}"
            for field in RunPublicationReceipt.field_names()
        )
    return "json_build_object(" + ", ".join(fields) + ")"


def run_authority_json_sql() -> str:
    """Return the standard three-way authority projection over named CTEs."""

    recorded = run_record_json_sql("latest_recorded_run")
    imported = run_record_json_sql("latest_successful_import")
    publication = run_record_json_sql(
        "latest_receipt_bearing_publication",
        include_receipt=True,
    )
    return (
        "json_build_object("
        "'latest_recorded_run', (SELECT "
        f"{recorded} FROM latest_recorded_run), "
        "'latest_successful_import', (SELECT "
        f"{imported} FROM latest_successful_import), "
        "'latest_receipt_bearing_publication', (SELECT "
        f"{publication} FROM latest_receipt_bearing_publication)"
        ")"
    )


def build_run_authority_query_sql(repository_name: str) -> str:
    """Build dedicated typed authority readback for one repository name."""

    quoted_name = sql_literal(repository_name)
    receipt_present = receipt_presence_predicate("runs", present=True)
    receipt_absent = receipt_presence_predicate("runs", present=False)
    authority_json = run_authority_json_sql()
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE repositories.name = {quoted_name} ORDER BY id DESC LIMIT 1"
        "), "
        "latest_recorded_run AS ("
        "SELECT runs.* FROM runs JOIN repo ON repo.id = runs.repository_id "
        "ORDER BY runs.id DESC LIMIT 1"
        "), "
        "latest_successful_import AS ("
        "SELECT runs.* FROM runs JOIN repo ON repo.id = runs.repository_id "
        "WHERE runs.status = 'complete' "
        f"AND {receipt_absent} ORDER BY runs.id DESC LIMIT 1"
        "), "
        "latest_receipt_bearing_publication AS ("
        "SELECT runs.* FROM runs JOIN repo ON repo.id = runs.repository_id "
        "WHERE runs.status = 'complete' "
        f"AND {receipt_present} ORDER BY runs.id DESC LIMIT 1"
        ") "
        "SELECT json_build_object("
        f"'run_authority', {authority_json}"
        ")::text;"
    )


def parse_run_authority(payload: Mapping[str, object]) -> RunAuthoritySnapshot:
    """Parse one bounded three-way run authority projection."""

    authority = payload.get("run_authority")
    if not isinstance(authority, Mapping):
        raise StorageSchemaError("storage returned malformed run authority")
    try:
        recorded = _parse_record(authority.get("latest_recorded_run"), RecordedRun)
        imported = _parse_record(
            authority.get("latest_successful_import"),
            SuccessfulImport,
        )
        publication_payload = authority.get("latest_receipt_bearing_publication")
        if publication_payload is None:
            publication = None
        elif isinstance(publication_payload, Mapping):
            run = _parse_record(publication_payload, RecordedRun)
            receipt = publication_receipt_from_mapping(publication_payload)
            if run is None or receipt is None:
                raise ValueError("missing publication authority")
            publication = ReceiptBearingPublication(run, receipt)
        else:
            raise ValueError("invalid publication authority")
        return RunAuthoritySnapshot(recorded, imported, publication)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError("storage returned malformed run authority") from error


def read_run_authority(
    psql_args: Sequence[str],
    repository_name: str,
    *,
    psql_command: str = "psql",
    env: Mapping[str, str] | None = None,
) -> RunAuthoritySnapshot:
    """Read the explicit three-way authority snapshot for one repository."""

    completed = run_psql(
        [
            psql_command,
            *psql_args,
            "-At",
            "-c",
            build_run_authority_query_sql(repository_name),
        ],
        env=dict(env) if env is not None else None,
    )
    payload = parse_psql_json(completed.stdout, label="run authority")
    if not isinstance(payload, Mapping):
        raise StorageSchemaError("psql returned malformed run authority")
    return parse_run_authority(payload)


def _parse_record(payload: object, record_type):
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("invalid run authority")
    run_id = int(payload["run_id"])
    status = RunStatus(str(payload["status"]))
    started_at = payload["started_at"]
    finished_at = payload.get("finished_at")
    if (
        run_id <= 0
        or not isinstance(started_at, str)
        or len(started_at) > 64
        or (finished_at is not None and not isinstance(finished_at, str))
        or (isinstance(finished_at, str) and len(finished_at) > 64)
    ):
        raise ValueError("invalid run authority")
    return record_type(GraphRunId(run_id), status, started_at, finished_at)


__all__ = [
    "build_run_authority_query_sql",
    "ReceiptBearingPublication",
    "RecordedRun",
    "RunAuthoritySnapshot",
    "RunStatus",
    "SuccessfulImport",
    "parse_run_authority",
    "read_run_authority",
    "receipt_presence_predicate",
    "run_authority_json_sql",
    "run_record_json_sql",
]
