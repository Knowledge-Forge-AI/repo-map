from __future__ import annotations

from collections import Counter

import pytest

from repomap_test_support.storage_rows_contracts import (
JSONABLE_ROW_EXPORT_NAMES,
TABLE_ROW_EXPORT_NAMES,
)

from repomap_kg.storage import rows
from repomap_kg.storage.errors import StorageSchemaError


def test_storage_jsonable_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.jsonable_rows as jsonable_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert jsonable_rows.__all__ == JSONABLE_ROW_EXPORT_NAMES

    for name in JSONABLE_ROW_EXPORT_NAMES:
        jsonable_name = getattr(jsonable_rows, name)
        assert getattr(rows, name) is jsonable_name
        assert getattr(storage, name) is jsonable_name
        assert getattr(storage_main, name) is jsonable_name
        assert getattr(storage_rows_facade, name) is jsonable_name

def test_storage_table_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.table_rows as table_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert table_rows.__all__ == TABLE_ROW_EXPORT_NAMES

    for name in TABLE_ROW_EXPORT_NAMES:
        table_name = getattr(table_rows, name)
        assert getattr(rows, name) is table_name
        assert getattr(storage, name) is table_name
        assert getattr(storage_main, name) is table_name
        assert getattr(storage_rows_facade, name) is table_name

def test_payload_helpers_preserve_false_zero_empty_and_current_error_shapes() -> None:
    payload = {
        "text": "",
        "flag": False,
        "optional_flag": False,
        "optional_none": None,
        "count": 0,
        "object": {"z": 2, "a": 0},
        "counts": {"b": "2", "a": 0},
    }

    assert rows.payload_string(payload, "text", label="fixture") == ""
    assert rows.payload_bool(payload, "flag", label="fixture") is False
    assert rows.payload_optional_bool(payload, "optional_flag", label="fixture") is False
    assert rows.payload_optional_bool(payload, "optional_none", label="fixture") is None
    assert rows.payload_int(payload, "count", label="fixture") == 0
    assert rows.payload_json_object(payload, "object", label="fixture") == {
        "a": 0,
        "z": 2,
    }
    assert rows.payload_count_map(payload, "counts", label="fixture") == {
        "a": 0,
        "b": 2,
    }

    with pytest.raises(
        StorageSchemaError,
        match="psql returned a malformed fixture: missing",
    ):
        rows.payload_string({}, "missing", label="fixture")
    with pytest.raises(
        StorageSchemaError,
        match="psql returned a malformed fixture: counts",
    ):
        rows.payload_count_map({"counts": {"": 1}}, "counts", label="fixture")
    with pytest.raises(
        StorageSchemaError,
        match="psql returned a malformed fixture: optional",
    ):
        rows.payload_optional_text({"optional": ""}, "optional", label="fixture")

def test_manifest_helpers_preserve_conservative_coercion_defaults() -> None:
    assert rows.optional_manifest_text({"name": "repo"}, "name") == "repo"
    assert rows.optional_manifest_text({"name": ""}, "name") is None
    assert rows.optional_manifest_text({"name": 7}, "name") is None
    assert rows.manifest_int({"count": "5"}, "count") == 5
    assert rows.manifest_int({"count": "-3"}, "count") == 0
    assert rows.manifest_int({"count": "not-an-int"}, "count") == 0
    assert rows.manifest_counter({"ok": "2", "zero": 0, "bad": "x", "": 3}) == Counter(
        {"ok": 2}
    )
    assert rows.manifest_list([{"a": 1}, "skip", {"b": 2}]) == (
        {"a": 1},
        {"b": 2},
    )
    assert rows.manifest_list({"not": "a list"}) == ()

def test_payload_decoders_raise_current_malformed_payload_messages() -> None:
    with pytest.raises(
        StorageSchemaError,
        match="psql returned a malformed canonical node record: graph_key_version",
    ):
        rows.canonical_node_record_from_storage_payload({"canonical_key": "file:README"})
def test_jsonable_projection_and_formatter_edge_cases_are_pinned() -> None:
    summary = rows.CanonicalStorageSummaryRecord(
        root_path="/repo",
        repository_name="",
        latest_run_id=None,
        runs=0,
        files=0,
        raw_observations=0,
        canonical_nodes=0,
        canonical_edges=0,
        canonical_evidence=0,
    )

    assert rows.canonical_storage_summary_to_jsonable(summary) == {
        "root_path": "/repo",
        "repository_name": "",
        "latest_run_id": None,
        "runs": 0,
        "files": 0,
        "raw_observations": 0,
        "raw_observations_total": 0,
        "latest_run_raw_observations": None,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "canonical_evidence": 0,
    }
    assert "canonical_nodes" in rows.format_canonical_storage_summary_table(summary)
    assert (
        rows.format_count_summary({"zero": 0, "two": 2, "empty_list": []})
        == "zero=0, two=2, empty_list=[]"
    )
    assert (
        rows.format_bool_summary({"false": False, "true": True, "zero": 0})
        == "false=false, true=true, zero=0"
    )

def test_storage_sql_facing_active_row_surfaces_remain_available() -> None:
    import repomap_kg.storage.sql as sql_module
    assert sql_module.FileRow is rows.FileRow
    assert sql_module.RawObservationRow is rows.RawObservationRow
    assert sql_module.CanonicalLoadRows is rows.CanonicalLoadRows


@pytest.mark.parametrize("invalid", [False, True])
def test_prepare_load_preserves_raw_rows_and_withholds_failed_canonical_rows(invalid: bool) -> None:
    from repomap_kg.storage import canonicalization_error_message, prepare_canonical_load
    from repomap_test_support.storage_rows_contracts import _file_observation

    observations = [_file_observation("README.md")]
    if invalid:
        observations.append(_file_observation("../outside.md"))
    prepared = prepare_canonical_load(observations)
    assert len(prepared.raw_rows) == len(observations)
    assert prepared.result.ok is not invalid
    if invalid:
        assert prepared.result.graph.nodes  # Valid partial facts must not become write rows.
        assert prepared.canonical_rows == rows.CanonicalLoadRows((), (), (), (), ())
        assert canonicalization_error_message(prepared.result) == "file path must not escape the repository"
    else:
        assert [node.canonical_key for node in prepared.canonical_rows.nodes] == ["file:README.md"]
        assert len(prepared.canonical_rows.evidence) == 1
        assert canonicalization_error_message(prepared.result) == "unknown canonicalization error"
