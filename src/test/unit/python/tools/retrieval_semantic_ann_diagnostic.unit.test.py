"""Unit boundaries for the disposable HNSW catalog diagnostic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json

import pytest

from repomap_test_support.w5_experiment_ann_diagnostic import (
    MarkerSink,
    diagnostic_index_spec,
    run_hnsw_catalog_diagnostic,
)
from retrieval_semantic_ann_models import JsonObject
from retrieval_semantic_ann_sql import build_hnsw_index_create_sql
from retrieval_semantic_experiment_contracts import ExperimentRefusal


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError("expected marker mapping")
    return value


class _FakePostgres:
    psql_command = "psql"
    psql_args: Sequence[str] = ()

    def psql_scalar(self, sql: str) -> str:
        raise AssertionError(f"unexpected live SQL: {sql}")


def _catalog(
    spec, *, present: bool, index_oid: int = 101, table_oid: int = 202
) -> JsonObject:
    return {
        "present": present,
        "index_oid": index_oid if present else None,
        "table_oid": table_oid if present else None,
        "index_attribute_count": 1 if present else None,
        "index_key_count": 1 if present else None,
        "index_schema": "repomap_enrichment" if present else None,
        "index_name": spec.name if present else None,
        "table_schema": "repomap_enrichment" if present else None,
        "table_name": "embeddings" if present else None,
        "access_method": "hnsw" if present else None,
        "is_valid": True if present else None,
        "is_ready": True if present else None,
        "index_owner": spec.owner_identity if present else None,
        "current_user": spec.owner_identity if present else None,
        "opclass_schema": "repomap_vector" if present else None,
        "opclass_name": "vector_cosine_ops" if present else None,
        "expression": "embedding::repomap_vector.vector(384)" if present else None,
        "predicate": (
            f"(rebuild_id = '{spec.rebuild_id}'::text) AND (dimensions = 384)"
            if present else None
        ),
        "reloptions": [] if present else None,
    }


def _reader(values: tuple[JsonObject, ...]):
    remaining = list(values)
    calls: list[tuple[str, str]] = []

    def read(sql: str, *, label: str) -> JsonObject:
        calls.append((sql, label))
        return remaining.pop(0)

    return read, calls


def _marker_sink(
    markers: list[Mapping[str, object]],
) -> MarkerSink:
    def record(marker: Mapping[str, object]) -> None:
        markers.append(marker)

    return record


def test_diagnostic_uses_exact_create_receipt_and_owned_cleanup() -> None:
    spec = diagnostic_index_spec()
    reader, catalog_calls = _reader((
        _catalog(spec, present=False),
        _catalog(spec, present=True),
        _catalog(spec, present=True),
        _catalog(spec, present=False),
    ))
    ddl_calls: list[tuple[str, str]] = []
    markers: list[Mapping[str, object]] = []

    def execute(sql: str, *, label: str) -> None:
        ddl_calls.append((sql, label))

    marker = run_hnsw_catalog_diagnostic(
        _FakePostgres(), read_catalog_payload=reader, execute_ddl=execute,
        marker_sink=_marker_sink(markers),
    )

    marker_map = _mapping(marker)
    assert marker_map["status"] == "completed"
    assert _mapping(marker_map["cleanup"])["status"] == "verified_absent"
    assert ddl_calls[0][0] == build_hnsw_index_create_sql(spec)
    assert ddl_calls[1][1] == "hnsw index cleanup"
    types = _mapping(marker_map["catalog_field_types"])
    assert _mapping(types["catalog_readback"])["index_oid"] == "int"
    assert _mapping(types["cleanup"])["index_oid"] == "null"
    assert len(catalog_calls) == 4
    assert "101" not in json.dumps(marker, sort_keys=True)
    assert markers == [marker]


def test_preexisting_index_refuses_without_mutation_or_cleanup() -> None:
    spec = diagnostic_index_spec()
    reader, _calls = _reader((_catalog(spec, present=True),))
    ddl_calls: list[str] = []
    markers: list[Mapping[str, object]] = []

    with pytest.raises(ExperimentRefusal, match="hnsw_index_preexisting"):
        run_hnsw_catalog_diagnostic(
            _FakePostgres(), read_catalog_payload=reader,
            execute_ddl=lambda sql, *, label: ddl_calls.append(sql),
            marker_sink=_marker_sink(markers),
        )

    assert ddl_calls == []
    marker = _mapping(markers[0])
    assert marker["status"] == "refused"
    assert _mapping(marker["primary"])["code"] == "hnsw_index_preexisting"
    assert _mapping(marker["cleanup"])["status"] == "not_attempted"


def test_ddl_failure_is_sanitized_and_does_not_claim_cleanup() -> None:
    spec = diagnostic_index_spec()
    reader, _calls = _reader((_catalog(spec, present=False),))
    markers: list[Mapping[str, object]] = []

    def fail(sql: str, *, label: str) -> None:
        del sql
        raise RuntimeError("raw server detail must not enter marker")

    with pytest.raises(ExperimentRefusal, match="hnsw_index_creation_failed"):
        run_hnsw_catalog_diagnostic(
            _FakePostgres(), read_catalog_payload=reader, execute_ddl=fail,
            marker_sink=_marker_sink(markers),
        )

    marker = markers[0]
    marker_map = _mapping(marker)
    assert marker_map["status"] == "failed"
    assert _mapping(marker_map["primary"])["stage"] == "create"
    assert _mapping(marker_map["cleanup"])["status"] == "not_attempted"
    assert "raw server detail" not in json.dumps(marker)


def test_malformed_catalog_records_raw_type_family_before_strict_parse() -> None:
    spec = diagnostic_index_spec()
    malformed = _catalog(spec, present=True)
    malformed["index_oid"] = "not-an-integer"
    reader, _calls = _reader((_catalog(spec, present=False), malformed))
    markers: list[Mapping[str, object]] = []

    with pytest.raises(ExperimentRefusal, match="invalid_index_catalog"):
        run_hnsw_catalog_diagnostic(
            _FakePostgres(), read_catalog_payload=reader,
            execute_ddl=lambda sql, *, label: None,
            marker_sink=_marker_sink(markers),
        )

    marker = markers[0]
    marker_map = _mapping(marker)
    assert _mapping(marker_map["primary"])["stage"] == "catalog_readback"
    types = _mapping(marker_map["catalog_field_types"])
    assert _mapping(types["catalog_readback"])["index_oid"] == "string"
    assert _mapping(marker_map["cleanup"])["status"] == "not_attempted"


def test_owned_cleanup_failure_preserves_completed_primary_state() -> None:
    spec = diagnostic_index_spec()
    reader, _calls = _reader((
        _catalog(spec, present=False),
        _catalog(spec, present=True),
        _catalog(spec, present=True),
    ))
    markers: list[Mapping[str, object]] = []

    def execute(sql: str, *, label: str) -> None:
        del sql
        if label == "hnsw index cleanup":
            raise RuntimeError("raw cleanup detail must not enter marker")

    with pytest.raises(ExperimentRefusal, match="hnsw_diagnostic_cleanup_failed"):
        run_hnsw_catalog_diagnostic(
            _FakePostgres(), read_catalog_payload=reader, execute_ddl=execute,
            marker_sink=_marker_sink(markers),
        )

    marker = markers[0]
    marker_map = _mapping(marker)
    assert marker_map["status"] == "failed"
    assert _mapping(marker_map["primary"])["status"] == "completed"
    cleanup = _mapping(marker_map["cleanup"])
    assert cleanup["status"] == "failed"
    assert cleanup["code"] == "drop_failed"
    assert "raw cleanup detail" not in json.dumps(marker)
