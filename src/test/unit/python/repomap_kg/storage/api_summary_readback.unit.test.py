from __future__ import annotations

import inspect
import json
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import pytest

import repomap_kg.storage.summaries as summaries
import repomap_kg.storage.summary_rows_manifest as manifest_rows
from repomap_kg.storage import (
    APISummaryRecord,
    StorageSchemaError,
    api_manifest_summary_payload,
    api_summary_from_storage_payload,
    api_summary_to_jsonable,
    build_api_summary_query_sql,
    query_api_summary,
    query_bulk_summary,
)


EXPECTED_FIELDS = tuple(
    "root_path_summary repository_name api_runs sources source_ids source_types "
    "api_source_classes provider_names provider_products policy_statuses requests "
    "responses endpoints endpoint_names methods downstream_routes response_types "
    "response_byte_count redacted_responses diagnostic_counts routed_artifacts "
    "observations_with_api_provenance config_documents_from_api no_network "
    "no_mutation no_credentials_resolved no_scheduler "
    "no_provider_specific_behavior".split()
)
COUNT_MAP_FIELDS = (
    "source_types", "api_source_classes", "provider_names", "provider_products",
    "policy_statuses", "methods", "downstream_routes", "response_types",
    "diagnostic_counts",
)
BOOLEAN_FIELDS = EXPECTED_FIELDS[23:]
FOLDED_BOOLEAN_FIELDS = BOOLEAN_FIELDS[:4]
MISSING = object()


def test_psycopg90_query_api_summary_uses_adapter_in_exact_order(tmp_path: Path) -> None:
    storage_payload = _storage_payload(
        observations_with_api_provenance="7",
        config_documents_from_api="2",
        extra_database_value="ignored",
    )
    manifest_payload = api_manifest_summary_payload(tmp_path)
    events: list[str] = []
    real_payload_int = summaries.payload_int
    real_optional_text = summaries.payload_optional_text
    real_converter = summaries.api_summary_from_storage_payload

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
        patch("repomap_kg.storage.summaries.api_manifest_summary_payload", side_effect=aggregate),
        patch("repomap_kg.storage.summaries.payload_int", side_effect=convert_int),
        patch("repomap_kg.storage.summaries.payload_optional_text", side_effect=convert_identity),
        patch("repomap_kg.storage.summaries.api_summary_from_storage_payload", side_effect=convert_final),
    ):
        record = query_api_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path=str(tmp_path),
            psql_command="custom-psql",
        )

    adapter.assert_called_once_with(
        build_api_summary_query_sql(str(tmp_path)),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="api summary",
        expected_shape="object",
    )
    assert events == [
        "adapter", "manifests", "text:repository_name",
        "int:observations_with_api_provenance", "int:config_documents_from_api", "final",
    ]
    assert tuple(field.name for field in fields(APISummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.observations_with_api_provenance == 7
    assert record.config_documents_from_api == 2
    assert api_summary_to_jsonable(record) == record.to_dict()
    assert "extra_database_value" not in record.to_dict()


def test_psycopg90_adapter_failure_prevents_manifest_access(tmp_path: Path) -> None:
    expected = StorageSchemaError("psycopg did not return api summary as a JSON object")

    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", side_effect=expected) as adapter,
        patch(
            "repomap_kg.storage.summaries.api_manifest_summary_payload",
            side_effect=AssertionError("manifest access must not occur"),
        ),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_api_summary(["-d", "postgres"], root_path=str(tmp_path))

    assert raised.value is expected
    adapter.assert_called_once()


@pytest.mark.parametrize("existing_empty", [False, True], ids=("absent", "empty"))
def test_psycopg90_absent_and_empty_manifest_defaults(
    tmp_path: Path,
    existing_empty: bool,
) -> None:
    if existing_empty:
        (tmp_path / ".repomap" / "api-runs").mkdir(parents=True)

    record = _query_payload(tmp_path, _storage_payload(repository_name=None))

    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.root_path_summary == "."
    assert record.repository_name is None
    assert record.api_runs == record.sources == 0
    assert record.source_ids == record.endpoint_names == ()
    assert all(record.to_dict()[field] == {} for field in COUNT_MAP_FIELDS)
    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)


def test_psycopg90_database_identity_counts_and_overwrite_remain_permissive(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        source="public-source",
        run="private-run",
        observations_with_api_provenance=100,
        config_documents_from_api=200,
    )

    record = _query_payload(
        tmp_path,
        _storage_payload(
            repository_name="public-api",
            observations_with_api_provenance=True,
            config_documents_from_api=-2,
        ),
    )

    assert record.repository_name == "public-api"
    assert record.observations_with_api_provenance == 1
    assert record.config_documents_from_api == -2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("repository_name", "", id="empty-identity"),
        pytest.param("repository_name", 7, id="invalid-identity"),
        pytest.param("observations_with_api_provenance", MISSING, id="missing-provenance"),
        pytest.param("observations_with_api_provenance", None, id="null-provenance"),
        pytest.param("config_documents_from_api", "not-a-count", id="invalid-config-count"),
    ],
)
def test_psycopg90_database_field_failures_follow_manifest_aggregation(
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
        return api_manifest_summary_payload(root)

    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload),
        patch("repomap_kg.storage.summaries.api_manifest_summary_payload", side_effect=aggregate),
    ):
        with pytest.raises(StorageSchemaError, match=field):
            query_api_summary(["-d", "postgres"], root_path=str(tmp_path))

    assert events == ["manifests"]


def test_psycopg90_nested_aggregation_order_and_strict_booleans(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        source="source-z",
        run="run-z",
        source_type="zeta",
        api_source_class="class-z",
        provider_name="provider-z",
        provider_product="product-z",
        policy_status="status-z",
        requests=[
            {
                "endpoint_name": "endpoint-z",
                "method": "POST",
                "downstream_route": "route-z",
                "response_type": "type-z",
            },
            "ignored",
        ],
        responses=[
            {
                "endpoint_name": "endpoint-a",
                "response_byte_count": "12",
                "redacted": True,
                "artifact_path": "private-artifact.json",
                "method": "IGNORED",
                "downstream_route": "ignored-route",
                "response_type": "ignored-type",
            },
            {"response_byte_count": -4, "redacted": 1, "artifact_path": ""},
        ],
    )
    _write_manifest(
        tmp_path,
        source="source-a",
        run="run-a",
        source_type="alpha",
        api_source_class="class-a",
        provider_name="provider-a",
        provider_product="product-a",
        policy_status="status-a",
        requests=[{"endpoint_name": "endpoint-a", "method": "GET"}],
    )

    record = _query_payload(tmp_path, _storage_payload())

    assert record.source_ids == ("source-a", "source-z")
    assert record.endpoint_names == ("endpoint-a", "endpoint-z")
    assert record.requests == 2
    assert record.responses == 2
    assert record.endpoints == 2
    assert record.response_byte_count == 12
    assert record.redacted_responses == 1
    assert record.routed_artifacts == 1
    assert tuple(record.methods) == ("GET", "POST")
    assert tuple(record.downstream_routes) == ("route-z",)
    assert tuple(record.response_types) == ("type-z",)
    for field in COUNT_MAP_FIELDS:
        assert tuple(record.to_dict()[field]) == tuple(sorted(record.to_dict()[field]))
    for field in BOOLEAN_FIELDS:
        payload = record.to_dict()
        payload["source_ids"] = list(record.source_ids)
        payload["endpoint_names"] = list(record.endpoint_names)
        payload[field] = 1
        with pytest.raises(StorageSchemaError, match=field):
            api_summary_from_storage_payload(payload)


@pytest.mark.parametrize("field", FOLDED_BOOLEAN_FIELDS)
def test_psycopg90_safety_false_is_sticky(tmp_path: Path, field: str) -> None:
    _write_manifest(tmp_path, source="source-a", run="run-a", **{field: False})
    _write_manifest(tmp_path, source="source-b", run="run-b", **{field: True})

    record = _query_payload(tmp_path, _storage_payload())

    assert record.to_dict()[field] is False
    assert record.no_provider_specific_behavior is True


def test_psycopg90_non_boolean_safety_values_are_ignored(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        source="source-a",
        run="run-a",
        no_network=None,
        no_mutation=0,
        no_credentials_resolved="false",
        no_scheduler=[],
        no_provider_specific_behavior=False,
    )

    record = _query_payload(tmp_path, _storage_payload())

    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)


def test_psycopg90_manifest_reader_defects_remain_nonfatal(tmp_path: Path) -> None:
    _write_manifest(tmp_path, source="valid", run="valid")
    _manifest_path(tmp_path, "bad-json", "run").write_text("{bad", encoding="utf-8")
    _manifest_path(tmp_path, "not-object", "run").write_text("[]\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-manifest.json"
    outside.write_text(json.dumps({"api_run_id": "outside"}), encoding="utf-8")
    _manifest_path(tmp_path, "escape", "run").symlink_to(outside)

    record = _query_payload(tmp_path, _storage_payload())

    assert record.api_runs == 1
    assert record.source_ids == ("valid",)
    assert record.diagnostic_counts == {"manifest_parse_error": 3}


def test_psycopg90_escaped_run_root_remains_nonfatal(tmp_path: Path) -> None:
    escaped = tmp_path.parent / f"{tmp_path.name}-escaped-api-runs"
    _write_manifest_at(escaped, "source", "run", {"api_run_id": "private-run"})
    (tmp_path / ".repomap").mkdir()
    (tmp_path / ".repomap" / "api-runs").symlink_to(escaped, target_is_directory=True)

    record = _query_payload(tmp_path, _storage_payload())

    assert record.api_runs == 0
    assert record.diagnostic_counts == {"manifest_parse_error": 1}


def test_psycopg90_final_converter_ignores_extras_and_bounds_malformed(
    tmp_path: Path,
) -> None:
    payload = api_manifest_summary_payload(tmp_path)
    payload["unexpected_raw_manifest"] = "excluded"

    record = api_summary_from_storage_payload(payload)

    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert "unexpected_raw_manifest" not in record.to_dict()
    del payload["root_path_summary"]
    with pytest.raises(StorageSchemaError, match="root_path_summary"):
        api_summary_from_storage_payload(payload)


def test_psycopg90_api_drops_direct_psql_while_bulk_stays_facade_backed() -> None:
    api_source = inspect.getsource(query_api_summary)
    bulk_source = inspect.getsource(query_bulk_summary)

    assert "execute_json_readback(" in api_source
    assert "run_psql(" not in api_source
    assert "parse_psql_json(" not in api_source
    assert "execute_json_readback(" in bulk_source
    assert "run_psql(" not in bulk_source
    assert hasattr(manifest_rows, "read_api_manifest_payloads")
    assert hasattr(manifest_rows, "read_bulk_manifest_payloads")


def _query_payload(root: Path, storage_payload: dict[str, object]) -> APISummaryRecord:
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=storage_payload,
    ):
        return query_api_summary(["-d", "postgres"], root_path=str(root))


def _storage_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository_name": "public-api",
        "observations_with_api_provenance": 0,
        "config_documents_from_api": 0,
    }
    payload.update(overrides)
    return payload


def _write_manifest(root: Path, *, source: str, run: str, **values: object) -> None:
    payload: dict[str, object] = {
        "source_id": source,
        "api_run_id": run,
        "source_type": "api.rest",
        "api_source_class": "api.custom_documented_api",
        "provider_name": "Public Provider",
        "provider_product": "Public API",
        "policy_status": "allowed",
    }
    payload.update(values)
    _write_manifest_at(root / ".repomap" / "api-runs", source, run, payload)


def _write_manifest_at(
    run_root: Path, source: str, run: str, payload: dict[str, object]
) -> None:
    path = run_root / source / run / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _manifest_path(root: Path, source: str, run: str) -> Path:
    path = root / ".repomap" / "api-runs" / source / run / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
