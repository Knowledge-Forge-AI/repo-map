from __future__ import annotations

import inspect
import json
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import pytest

import repomap_kg.storage.summaries as summaries
from repomap_kg.storage import (
    BulkSummaryRecord,
    StorageSchemaError,
    build_bulk_summary_query_sql,
    bulk_manifest_summary_payload,
    bulk_summary_from_storage_payload,
    bulk_summary_to_jsonable,
    query_api_summary,
    query_bulk_summary,
)


EXPECTED_FIELDS = tuple(
    "root_path_summary repository_name bulk_runs sources source_ids "
    "corpus_kinds policy_statuses file_count_included file_count_skipped "
    "total_bytes_included extractor_counts skip_reasons diagnostic_counts "
    "redaction_counts limit_hit_count max_files_hit_count "
    "max_total_bytes_hit_count max_file_bytes_hit_count max_depth_hit_count "
    "archive_deferred warc_deferred email_export_runs mixed_corpus_runs "
    "observations_with_bulk_provenance no_provider_api no_external_fetch "
    "no_source_mutation no_archive_decompression".split()
)
COUNT_MAP_FIELDS = (
    "corpus_kinds",
    "policy_statuses",
    "extractor_counts",
    "skip_reasons",
    "diagnostic_counts",
    "redaction_counts",
)
BOOLEAN_FIELDS = EXPECTED_FIELDS[24:]
MISSING = object()


def test_psycopg87_query_bulk_summary_uses_adapter_in_exact_order(tmp_path: Path) -> None:
    storage_payload = _storage_payload(
        observations_with_bulk_provenance="7",
        redacted_observations="2",
        extra_database_value="ignored",
    )
    manifest_payload = bulk_manifest_summary_payload(tmp_path)
    manifest_payload["redaction_counts"] = {"raw_observations": 1}
    events: list[str] = []
    real_payload_int = summaries.payload_int
    real_optional_text = summaries.payload_optional_text
    real_converter = summaries.bulk_summary_from_storage_payload

    def execute(*args, **kwargs):
        events.append("adapter")
        return storage_payload

    def aggregate(root: Path):
        events.append("manifests")
        assert root == tmp_path
        return manifest_payload

    def convert_int(payload, key, *, label):
        events.append(f"int:{key}")
        return real_payload_int(payload, key, label=label)

    def convert_identity(payload, key, *, label):
        events.append(f"text:{key}")
        return real_optional_text(payload, key, label=label)

    def convert_final(payload):
        events.append("final")
        return real_converter(payload)

    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", side_effect=execute) as adapter,
        patch("repomap_kg.storage.summaries.bulk_manifest_summary_payload", side_effect=aggregate),
        patch("repomap_kg.storage.summaries.payload_int", side_effect=convert_int),
        patch("repomap_kg.storage.summaries.payload_optional_text", side_effect=convert_identity),
        patch("repomap_kg.storage.summaries.bulk_summary_from_storage_payload", side_effect=convert_final),
        patch("repomap_kg.storage.summaries.run_psql", side_effect=AssertionError("Bulk must use adapter")),
    ):
        record = query_bulk_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path=str(tmp_path),
            psql_command="custom-psql",
        )

    adapter.assert_called_once_with(
        build_bulk_summary_query_sql(str(tmp_path)),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="bulk summary",
        expected_shape="object",
    )
    assert events == [
        "adapter",
        "manifests",
        "int:redacted_observations",
        "text:repository_name",
        "int:observations_with_bulk_provenance",
        "final",
    ]
    assert tuple(field.name for field in fields(BulkSummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.observations_with_bulk_provenance == 7
    assert record.redaction_counts == {"raw_observations": 2}
    assert bulk_summary_to_jsonable(record) == record.to_dict()
    assert "extra_database_value" not in record.to_dict()


def test_psycopg87_adapter_failure_prevents_manifest_access(tmp_path: Path) -> None:
    expected = StorageSchemaError("psycopg did not return bulk summary as a JSON object")

    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", side_effect=expected) as adapter,
        patch(
            "repomap_kg.storage.summaries.bulk_manifest_summary_payload",
            side_effect=AssertionError("manifest access must not occur"),
        ),
        patch("repomap_kg.storage.summaries.run_psql", side_effect=AssertionError("no fallback")),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_bulk_summary(["-d", "postgres"], root_path=str(tmp_path))

    assert raised.value is expected
    adapter.assert_called_once()


@pytest.mark.parametrize("existing_empty", [False, True], ids=("absent", "empty"))
def test_psycopg87_absent_and_empty_manifest_defaults(
    tmp_path: Path,
    existing_empty: bool,
) -> None:
    if existing_empty:
        (tmp_path / ".repomap" / "bulk-runs").mkdir(parents=True)

    record = _query_payload(tmp_path, _storage_payload(repository_name=None))

    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.root_path_summary == "."
    assert record.repository_name is None
    assert record.bulk_runs == record.sources == 0
    assert record.source_ids == ()
    assert all(record.to_dict()[field] == {} for field in COUNT_MAP_FIELDS)
    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)


def test_psycopg87_database_identity_and_counts_remain_permissive(tmp_path: Path) -> None:
    record = _query_payload(
        tmp_path,
        _storage_payload(
            repository_name="public-bulk",
            observations_with_bulk_provenance=True,
            redacted_observations=-2,
        ),
    )

    assert record.repository_name == "public-bulk"
    assert record.observations_with_bulk_provenance == 1
    assert record.redaction_counts == {"raw_observations": 0}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("repository_name", "", id="empty-identity"),
        pytest.param("observations_with_bulk_provenance", MISSING, id="missing-provenance"),
        pytest.param("observations_with_bulk_provenance", None, id="null-provenance"),
        pytest.param("redacted_observations", "not-a-count", id="invalid-redaction"),
    ],
)
def test_psycopg87_database_field_failures_follow_manifest_aggregation(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    storage_payload = _storage_payload()
    if value is MISSING:
        del storage_payload[field]
    else:
        storage_payload[field] = value
    events: list[str] = []

    def aggregate(root: Path):
        events.append("manifests")
        return bulk_manifest_summary_payload(root)

    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload),
        patch("repomap_kg.storage.summaries.bulk_manifest_summary_payload", side_effect=aggregate),
    ):
        with pytest.raises(StorageSchemaError, match=field):
            query_bulk_summary(["-d", "postgres"], root_path=str(tmp_path))

    assert events == ["manifests"]


@pytest.mark.parametrize(
    ("manifest_value", "database_value", "expected"),
    [
        pytest.param(MISSING, 0, {}, id="absent-database-zero"),
        pytest.param(MISSING, 4, {"raw_observations": 4}, id="absent-database-positive"),
        pytest.param(2, 5, {"raw_observations": 5}, id="database-greater"),
        pytest.param(5, 2, {"raw_observations": 5}, id="manifest-greater"),
        pytest.param(3, 3, {"raw_observations": 3}, id="equal"),
        pytest.param(MISSING, True, {"raw_observations": 1}, id="database-true"),
        pytest.param(4, -2, {"raw_observations": 4}, id="negative-with-manifest"),
        pytest.param(MISSING, -2, {"raw_observations": 0}, id="negative-without-manifest"),
        pytest.param("bad", 0, {}, id="malformed-manifest"),
        pytest.param(0, 0, {}, id="zero-manifest"),
        pytest.param(-1, 0, {}, id="negative-manifest"),
        pytest.param(False, 0, {}, id="false-manifest"),
        pytest.param(2, 3, {"raw_observations": 3}, id="not-additive"),
    ],
)
def test_psycopg87_redaction_merge_matrix(
    tmp_path: Path,
    manifest_value: object,
    database_value: object,
    expected: dict[str, int],
) -> None:
    redactions = {} if manifest_value is MISSING else {"raw_observations": manifest_value}
    _write_manifest(
        tmp_path,
        source="source-a",
        run="run-a",
        redaction_counts=redactions,
    )

    record = _query_payload(
        tmp_path,
        _storage_payload(redacted_observations=database_value),
    )

    assert record.redaction_counts == expected


def test_psycopg87_manifest_output_order_and_safety_contract(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        source="source-z",
        run="run-z",
        corpus_kind="zeta",
        extractor_counts={"zeta": 1, "alpha": 2},
    )
    _write_manifest(
        tmp_path,
        source="source-a",
        run="run-a",
        corpus_kind="alpha",
        extractor_counts={"beta": 3},
    )

    record = _query_payload(tmp_path, _storage_payload())

    assert record.source_ids == ("source-a", "source-z")
    assert tuple(record.corpus_kinds) == ("alpha", "zeta")
    assert tuple(record.extractor_counts) == ("alpha", "beta", "zeta")
    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)

    for field in BOOLEAN_FIELDS:
        payload = record.to_dict()
        payload["source_ids"] = list(record.source_ids)
        payload[field] = 1
        with pytest.raises(StorageSchemaError, match=field):
            bulk_summary_from_storage_payload(payload)


def test_psycopg87_manifest_reader_defects_remain_nonfatal(tmp_path: Path) -> None:
    _write_manifest(tmp_path, source="valid", run="valid")
    _manifest_path(tmp_path, "bad-json", "run").write_text("{bad", encoding="utf-8")
    _manifest_path(tmp_path, "not-object", "run").write_text("[]\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-manifest.json"
    outside.write_text(json.dumps({"bulk_run_id": "outside"}), encoding="utf-8")
    _manifest_path(tmp_path, "escape", "run").symlink_to(outside)

    record = _query_payload(tmp_path, _storage_payload())

    assert record.bulk_runs == 1
    assert record.source_ids == ("valid",)
    assert record.diagnostic_counts == {"manifest_parse_error": 3}


def test_psycopg87_final_converter_ignores_extras_and_bounds_malformed(
    tmp_path: Path,
) -> None:
    payload = bulk_manifest_summary_payload(tmp_path)
    payload["unexpected_raw_manifest"] = "excluded"

    record = bulk_summary_from_storage_payload(payload)

    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert "unexpected_raw_manifest" not in record.to_dict()
    del payload["root_path_summary"]
    with pytest.raises(StorageSchemaError, match="root_path_summary"):
        bulk_summary_from_storage_payload(payload)


def test_psycopg87_bulk_and_api_use_the_readback_facade() -> None:
    bulk_source = inspect.getsource(query_bulk_summary)
    api_source = inspect.getsource(query_api_summary)

    assert "run_psql(" not in bulk_source
    assert "parse_psql_json(" not in bulk_source
    assert "execute_json_readback(" in api_source
    assert "run_psql(" not in api_source
    assert "parse_psql_json(" not in api_source


def _query_payload(root: Path, storage_payload: dict[str, object]) -> BulkSummaryRecord:
    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload),
        patch("repomap_kg.storage.summaries.run_psql", side_effect=AssertionError("no direct psql")),
    ):
        return query_bulk_summary(["-d", "postgres"], root_path=str(root))


def _storage_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository_name": "public-bulk",
        "observations_with_bulk_provenance": 0,
        "redacted_observations": 0,
    }
    payload.update(overrides)
    return payload


def _write_manifest(root: Path, *, source: str, run: str, **values: object) -> None:
    payload: dict[str, object] = {
        "source_id": source,
        "bulk_run_id": run,
        "corpus_kind": "mixed_corpus",
        "policy_status": "allowed_with_limits",
    }
    payload.update(values)
    _manifest_path(root, source, run).write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def _manifest_path(root: Path, source: str, run: str) -> Path:
    path = root / ".repomap" / "bulk-runs" / source / run / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
