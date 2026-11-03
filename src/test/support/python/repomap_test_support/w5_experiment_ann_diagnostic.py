"""Bounded public-safe HNSW catalog lifecycle diagnostic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Protocol

from retrieval_semantic_ann_contracts import HnswIndexCatalogState
from retrieval_semantic_ann_lifecycle import (
    HnswCleanupReport,
    HnswCreationReceipt,
    capture_creation_receipt,
    cleanup_created_hnsw_index,
)
from retrieval_semantic_ann_models import HnswEvaluationError, JsonObject
from retrieval_semantic_ann_scope import index_name
from retrieval_semantic_ann_sql import (
    DEFAULT_OWNER_IDENTITY,
    HnswIndexSpec,
    build_hnsw_index_catalog_sql,
    build_hnsw_index_create_sql,
)
from retrieval_semantic_experiment_contracts import ExperimentRefusal


class DiagnosticPostgres(Protocol):
    """Minimal live handle needed by the default role-bound adapters."""

    psql_command: str
    psql_args: Sequence[str]

    def psql_scalar(self, sql: str) -> str: ...


class CatalogPayloadReader(Protocol):
    def __call__(self, sql: str, *, label: str) -> JsonObject: ...


class DdlExecutor(Protocol):
    def __call__(self, sql: str, *, label: str) -> None: ...


class MarkerSink(Protocol):
    def __call__(self, marker: Mapping[str, object]) -> None: ...


_DIAGNOSTIC_REBUILD_ID = "w5_ann_catalog_diagnostic"
_CATALOG_FIELDS = (
    "present", "index_oid", "table_oid", "index_attribute_count", "index_key_count",
    "index_schema", "index_name", "table_schema", "table_name", "access_method",
    "is_valid", "is_ready", "index_owner", "current_user", "opclass_schema",
    "opclass_name", "expression", "predicate", "reloptions",
)
_EXCEPTION_CLASSES = frozenset({
    "Exception", "ExperimentRefusal", "HnswEvaluationError", "OSError",
    "RuntimeError", "StorageSchemaError", "TypeError", "ValueError",
})
_CODES = frozenset({
    "catalog_read_failed", "cleanup_readback_failed", "creation_oid_mismatch",
    "drop_failed", "hnsw_catalog_invalid", "hnsw_catalog_sql_mismatch",
    "hnsw_creation_receipt_invalid", "hnsw_diagnostic_cleanup_failed",
    "hnsw_index_creation_failed", "hnsw_index_dimension_predicate_mismatch",
    "hnsw_index_expression_mismatch", "hnsw_index_identity_mismatch",
    "hnsw_index_key_shape_mismatch", "hnsw_index_not_ready", "hnsw_index_oid_missing",
    "hnsw_index_operator_mismatch", "hnsw_index_owner_mismatch",
    "hnsw_index_preexisting", "hnsw_index_reloptions_mismatch", "invalid_index_catalog",
})


def diagnostic_index_spec(attempt_identity: str = "w5-ann-catalog-diagnostic") -> HnswIndexSpec:
    """Build the fixed-dimension, invocation-bound diagnostic index identity."""
    query_digest = "sha256:" + hashlib.sha256(
        f"{_DIAGNOSTIC_REBUILD_ID}|{attempt_identity}".encode("utf-8")
    ).hexdigest()
    name = index_name(
        query_digest, _DIAGNOSTIC_REBUILD_ID, attempt_identity, DEFAULT_OWNER_IDENTITY,
    )
    return HnswIndexSpec(
        name=name,
        rebuild_id=_DIAGNOSTIC_REBUILD_ID,
        query_digest=query_digest,
        attempt_identity=attempt_identity,
        owner_identity=DEFAULT_OWNER_IDENTITY,
    ).validate()


def _type_family(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    return "unsupported"


def _catalog_types(payload: Mapping[str, object]) -> dict[str, str]:
    return {
        field: _type_family(payload[field]) if field in payload else "missing"
        for field in _CATALOG_FIELDS
    }


def _safe_exception_class(error: BaseException) -> str:
    name = type(error).__name__
    return name if name in _EXCEPTION_CLASSES else "Exception"


def _safe_code_value(candidate: object, fallback: str) -> str:
    safe_fallback = fallback if fallback in _CODES else "hnsw_catalog_invalid"
    return candidate if isinstance(candidate, str) and candidate in _CODES else safe_fallback


def _safe_code(error: BaseException | None, fallback: str) -> str:
    candidate = getattr(error, "code", None) if error is not None else None
    return _safe_code_value(candidate, fallback)


def _default_catalog_reader(
    postgres: DiagnosticPostgres,
) -> CatalogPayloadReader:
    from repomap_test_support.w5_experiment_postgres import _json_object

    def read_catalog(sql: str, *, label: str) -> JsonObject:
        return _json_object(postgres, sql, role=DEFAULT_OWNER_IDENTITY, label=label)

    return read_catalog


def _default_ddl_executor(postgres: DiagnosticPostgres) -> DdlExecutor:
    from repomap_test_support.w5_experiment_postgres import execute_sql

    def execute(sql: str, *, label: str) -> None:
        del label
        execute_sql(postgres, sql, role=DEFAULT_OWNER_IDENTITY)

    return execute


def _read_state(
    reader: CatalogPayloadReader,
    spec: HnswIndexSpec,
    *,
    label: str,
    phase: str,
    catalog_types: dict[str, dict[str, str]],
) -> HnswIndexCatalogState:
    sql = build_hnsw_index_catalog_sql(spec)
    payload = reader(sql, label=label)
    if not isinstance(payload, Mapping):
        raise HnswEvaluationError("invalid_index_catalog", "catalog payload is not an object")
    # Capture only fixed type families before the strict maintained parser sees it.
    catalog_types[phase] = _catalog_types(payload)
    return HnswIndexCatalogState.from_json(payload)


def _marker(
    *,
    status: str,
    primary: Mapping[str, object],
    cleanup: Mapping[str, object],
    catalog_types: Mapping[str, Mapping[str, str]],
) -> dict[str, object]:
    return {
        "schema": "w5-hnsw-catalog-diagnostic-v1",
        "operation": "hnsw_catalog_lifecycle",
        "status": status,
        "primary": dict(primary),
        "cleanup": dict(cleanup),
        "catalog_field_types": {
            phase: dict(types) for phase, types in catalog_types.items()
        },
    }


def _emit(marker: Mapping[str, object], sink: MarkerSink | None) -> None:
    if sink is None:
        encoded = json.dumps(marker, sort_keys=True, separators=(",", ":"), allow_nan=False)
        print(encoded, flush=True)
    else:
        sink(marker)


def _cleanup_details(
    report: HnswCleanupReport | None,
    error: BaseException | None,
) -> dict[str, object]:
    if error is not None:
        return {
            "status": "failed",
            "exception_class": _safe_exception_class(error),
            "code": _safe_code(error, "hnsw_diagnostic_cleanup_failed"),
        }
    if report is None:
        return {"status": "not_attempted", "exception_class": None, "code": None}
    if report.verified_absent:
        return {"status": "verified_absent", "exception_class": None, "code": None}
    status = "ownership_refused" if report.ownership_refused else "failed"
    code = _safe_code_value(report.failure_code, "hnsw_diagnostic_cleanup_failed")
    return {"status": status, "exception_class": None, "code": code}


def run_hnsw_catalog_diagnostic(
    postgres: DiagnosticPostgres,
    *,
    attempt_identity: str = "w5-ann-catalog-diagnostic",
    read_catalog_payload: CatalogPayloadReader | None = None,
    execute_ddl: DdlExecutor | None = None,
    marker_sink: MarkerSink | None = None,
) -> Mapping[str, object]:
    """Create, parse, receipt, and clean one exact disposable HNSW index."""
    spec = diagnostic_index_spec(attempt_identity)
    reader = read_catalog_payload or _default_catalog_reader(postgres)
    ddl = execute_ddl or _default_ddl_executor(postgres)
    catalog_types: dict[str, dict[str, str]] = {}
    primary_stage = "preflight"
    primary_error: BaseException | None = None
    receipt: HnswCreationReceipt | None = None
    try:
        before = _read_state(
            reader, spec, label="hnsw diagnostic preflight", phase="preflight",
            catalog_types=catalog_types,
        )
        if before.present:
            raise ExperimentRefusal("hnsw_index_preexisting")
        primary_stage = "create"
        ddl(build_hnsw_index_create_sql(spec), label="hnsw diagnostic creation")
        primary_stage = "catalog_readback"
        after = _read_state(
            reader, spec, label="hnsw diagnostic creation", phase="catalog_readback",
            catalog_types=catalog_types,
        )
        primary_stage = "receipt"
        receipt = capture_creation_receipt(
            before, after, spec, attempt_identity=attempt_identity,
        )
    except Exception as error:
        primary_error = error

    cleanup_report: HnswCleanupReport | None = None
    cleanup_error: BaseException | None = None
    if receipt is not None:
        try:
            expected_catalog_sql = build_hnsw_index_catalog_sql(spec)

            def read_cleanup(sql: str, *, label: str) -> HnswIndexCatalogState:
                if sql != expected_catalog_sql:
                    raise ExperimentRefusal("hnsw_catalog_sql_mismatch")
                return _read_state(
                    reader, spec, label=label, phase="cleanup", catalog_types=catalog_types,
                )

            cleanup_report = cleanup_created_hnsw_index(
                receipt, read_catalog=read_cleanup, execute_ddl=ddl,
            )
        except Exception as error:
            cleanup_error = error

    if primary_error is not None:
        primary_status = "refused" if isinstance(primary_error, ExperimentRefusal) else "failed"
        primary_fallback = {
            "preflight": "catalog_read_failed",
            "create": "hnsw_index_creation_failed",
            "catalog_readback": "hnsw_catalog_invalid",
            "receipt": "hnsw_creation_receipt_invalid",
        }[primary_stage]
        primary_code = _safe_code(primary_error, primary_fallback)
        marker = _marker(
            status=primary_status,
            primary={
                "status": primary_status, "stage": primary_stage,
                "exception_class": _safe_exception_class(primary_error),
                "code": primary_code,
            },
            cleanup=_cleanup_details(cleanup_report, cleanup_error),
            catalog_types=catalog_types,
        )
        _emit(marker, marker_sink)
        if isinstance(primary_error, ExperimentRefusal) and primary_error.code == primary_code:
            raise primary_error
        raise ExperimentRefusal(primary_code) from primary_error

    cleanup = _cleanup_details(cleanup_report, cleanup_error)
    if cleanup["status"] != "verified_absent":
        marker = _marker(
            status="failed",
            primary={
                "status": "completed", "stage": "complete",
                "exception_class": None, "code": None,
            },
            cleanup=cleanup,
            catalog_types=catalog_types,
        )
        _emit(marker, marker_sink)
        raise ExperimentRefusal("hnsw_diagnostic_cleanup_failed") from cleanup_error

    marker = _marker(
        status="completed",
        primary={
            "status": "completed", "stage": "complete",
            "exception_class": None, "code": None,
        },
        cleanup=cleanup,
        catalog_types=catalog_types,
    )
    _emit(marker, marker_sink)
    return marker


__all__ = ["diagnostic_index_spec", "run_hnsw_catalog_diagnostic"]
