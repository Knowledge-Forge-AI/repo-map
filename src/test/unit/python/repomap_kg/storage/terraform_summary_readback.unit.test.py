from __future__ import annotations

from collections.abc import Callable
import inspect
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    StorageSchemaError,
    TerraformSummaryRecord,
    build_terraform_summary_query_sql,
    query_terraform_summary,
    terraform_summary_from_storage_payload,
    terraform_summary_to_jsonable,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "terraform_observations",
    "terraform_files",
    "file_families",
    "terraform",
    "references",
    "tfvars",
    "redactions",
    "diagnostics",
    "generic_config",
    "safety",
)

COUNT_MAP_KEYS = {
    "file_families": ("tf", "tfvars", "terraform.tfvars", "auto.tfvars"),
    "terraform": (
        "blocks",
        "providers",
        "required_providers",
        "required_versions",
        "backends",
        "resources",
        "data_sources",
        "modules",
        "variables",
        "outputs",
        "locals",
        "moved",
        "imports",
        "checks",
        "removed",
    ),
    "references": (
        "total",
        "provider_sources",
        "version_constraints",
        "module_sources",
        "local_module_refs",
        "remote_refs_not_fetched",
        "depends_on",
        "provider_aliases",
        "repo_escape_diagnostics",
    ),
    "redactions": (
        "tfvars_values",
        "secret_like_fields",
        "credentialed_urls",
        "import_ids",
        "backend_values",
    ),
    "diagnostics": ("parse_errors", "limit_overflows", "malformed_hcl"),
    "generic_config": (
        "config_documents",
        "config_paths",
        "config_references",
        "file_nodes",
    ),
}

TFVARS_KEYS = ("files", "variables", "literal_values_exposed")

SAFETY_KEYS = (
    "no_execution",
    "no_fetch",
    "no_terraform_cli",
    "no_provider_download",
    "no_module_download",
    "no_state_access",
    "tfvars_redacted",
    "raw_profile_only",
    "no_new_canonical_namespaces",
)


@pytest.mark.parametrize(
    ("root", "psql_args", "command", "identity", "omit_defaults"),
    (("/tmp/psycopg77-public", ["-h", "/tmp/postgres", "-d", "postgres"], "custom-psql", None, False),
     ("/tmp/fixture", ["-d", "postgres"], "psql", "repo1:fixture", False),
     ("/tmp/fixture", ["-d", "postgres"], "psql", None, True)),
)
def test_psycopg77_query_terraform_summary_uses_object_readback_adapter(
    root: str, psql_args: list[str], command: str, identity: str | None,
    omit_defaults: bool,
) -> None:
    payload = _summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.terraform_summary_from_storage_payload",
            wraps=terraform_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("terraform summary must use the adapter"),
        ),
    ):
        if omit_defaults:
            record = query_terraform_summary(psql_args, root_path=root)
        else:
            record = query_terraform_summary(
                psql_args, root_path=root,
                psql_command=command, repository_identity=identity,
            )

    execute_json_readback.assert_called_once_with(
        build_terraform_summary_query_sql(
            root, repository_identity=identity,
        ),
        psql_args=psql_args,
        psql_command=command,
        label="terraform summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(TerraformSummaryRecord)) == (
        EXPECTED_FIELDS
    )
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert terraform_summary_to_jsonable(record) == record.to_dict()


def test_psycopg77_unknown_root_preserves_complete_default_contract() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg77-unknown",
        repository_name=None,
        count=0,
    )

    record = terraform_summary_from_storage_payload(payload)

    assert record.to_dict() == payload
    assert sum(len(keys) for keys in COUNT_MAP_KEYS.values()) == 40
    for map_name, required_keys in COUNT_MAP_KEYS.items():
        assert tuple(record.to_dict()[map_name]) == required_keys
        assert set(record.to_dict()[map_name].values()) == {0}
    assert tuple(record.tfvars) == TFVARS_KEYS
    assert record.tfvars == {
        "files": 0,
        "variables": 0,
        "literal_values_exposed": False,
    }
    assert tuple(record.safety) == SAFETY_KEYS
    assert set(record.safety.values()) == {True}


def test_psycopg77_terraform_empty_repository_preserves_stored_counts() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg77-terraform-empty",
        repository_name="psycopg77-terraform-empty",
        count=0,
    )
    generic_config = payload["generic_config"]
    assert isinstance(generic_config, dict)
    generic_config.update(
        config_documents=3,
        config_paths=5,
        config_references=7,
        file_nodes=11,
    )

    record = terraform_summary_from_storage_payload(payload)

    assert record.repository_name == "psycopg77-terraform-empty"
    assert record.terraform_observations == 0
    assert record.terraform_files == 0
    assert record.generic_config == payload["generic_config"]


@pytest.mark.parametrize(
    ("mutate", "map_name"),
    (
        (lambda payload: payload.pop("terraform"), "terraform"),
        (
            lambda payload: payload["references"].pop("provider_sources"),
            "references",
        ),
        (
            lambda payload: payload["diagnostics"].update(
                parse_errors="not-a-count"
            ),
            "diagnostics",
        ),
        (
            lambda payload: payload["redactions"].update(
                invalid_extra_count="not-a-count"
            ),
            "redactions",
        ),
    ),
)
def test_psycopg77_required_count_map_failures_are_bounded(
    mutate: Callable[[dict[str, object]], None],
    map_name: str,
) -> None:
    payload = _summary_payload()
    mutate(payload)

    with pytest.raises(StorageSchemaError, match=rf": {map_name}$"):
        terraform_summary_from_storage_payload(payload)


@pytest.mark.parametrize(
    ("field_name", "remove", "invalid"),
    (
        ("files", True, None),
        ("variables", False, None),
        ("literal_values_exposed", True, None),
        ("literal_values_exposed", False, "false"),
    ),
)
def test_psycopg77_tfvars_failures_use_nested_field_labels(
    field_name: str, remove: bool, invalid: object,
) -> None:
    payload = _summary_payload()
    tfvars = payload["tfvars"]
    assert isinstance(tfvars, dict)
    if remove:
        tfvars.pop(field_name)
    else:
        tfvars[field_name] = invalid

    with pytest.raises(StorageSchemaError, match=rf": {field_name}$"):
        terraform_summary_from_storage_payload(payload)


@pytest.mark.parametrize("invalid", (None, 1, "true"))
def test_psycopg77_safety_requires_actual_booleans(invalid: object) -> None:
    payload = _summary_payload()
    safety = payload["safety"]
    assert isinstance(safety, dict)
    safety["no_execution"] = invalid

    with pytest.raises(StorageSchemaError, match=r": safety$"):
        terraform_summary_from_storage_payload(payload)


def test_psycopg77_count_coercion_remains_permissive() -> None:
    payload = _summary_payload()
    payload["terraform_observations"] = "42"
    payload["terraform_files"] = True
    terraform = payload["terraform"]
    assert isinstance(terraform, dict)
    terraform["resources"] = -3
    references = payload["references"]
    assert isinstance(references, dict)
    references["total"] = False
    tfvars = payload["tfvars"]
    assert isinstance(tfvars, dict)
    tfvars["files"] = "5"
    tfvars["variables"] = -7

    record = terraform_summary_from_storage_payload(payload)

    assert record.terraform_observations == 42
    assert record.terraform_files == 1
    assert record.terraform["resources"] == -3
    assert record.references["total"] == 0
    assert record.tfvars == {
        "files": 5,
        "variables": -7,
        "literal_values_exposed": False,
    }


@pytest.mark.parametrize("invalid", (None, "not-a-count"))
def test_psycopg77_malformed_scalar_counts_remain_bounded(
    invalid: object,
) -> None:
    payload = _summary_payload()
    payload["terraform_files"] = invalid

    with pytest.raises(StorageSchemaError, match=r": terraform_files$"):
        terraform_summary_from_storage_payload(payload)


def test_psycopg77_extra_keys_keep_existing_converter_behavior() -> None:
    payload = _summary_payload()
    terraform = payload["terraform"]
    assert isinstance(terraform, dict)
    terraform["extra_count"] = "9"
    tfvars = payload["tfvars"]
    assert isinstance(tfvars, dict)
    tfvars["extra_tfvars"] = {"not": "validated"}
    safety = payload["safety"]
    assert isinstance(safety, dict)
    safety["extra_safety"] = "not-validated"
    payload["extra_top_level"] = {"discarded": True}

    record = terraform_summary_from_storage_payload(payload)

    assert tuple(record.terraform) == COUNT_MAP_KEYS["terraform"]
    assert tuple(record.tfvars) == TFVARS_KEYS
    assert tuple(record.safety) == SAFETY_KEYS
    assert "extra_top_level" not in record.to_dict()


def test_psycopg77_adapter_shape_errors_propagate_without_fallback() -> None:
    shape_error = StorageSchemaError(
        "psycopg readback returned a malformed terraform summary"
    )

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=shape_error,
        ),
        patch("repomap_kg.storage.summaries.run_psql") as run_psql,
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_terraform_summary([], root_path="/tmp/psycopg77-public")

    assert raised.value is shape_error
    run_psql.assert_not_called()


def test_psycopg77_query_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_terraform_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def test_build_terraform_summary_query_sql_with_identity() -> None:
    sql = build_terraform_summary_query_sql(
        "/tmp/fixture",
        repository_identity="repo1:fixture",
    )
    assert "repositories.id = (SELECT id FROM repositories WHERE" in sql
    assert "repository_identity = 'repo1:fixture'" in sql
    assert "ORDER BY (repository_identity = 'repo1:fixture') DESC NULLS LAST, id LIMIT 1" in sql
    assert "'root_path', '/tmp/fixture'" in sql


def test_build_terraform_summary_query_sql_without_identity() -> None:
    sql_default = build_terraform_summary_query_sql("/tmp/fixture")
    sql_none = build_terraform_summary_query_sql("/tmp/fixture", repository_identity=None)
    assert sql_default == sql_none
    assert "repositories.root_path = '/tmp/fixture'" in sql_default
    assert "repository_identity" not in sql_default


def test_build_terraform_summary_query_sql_invalid_identity() -> None:
    with pytest.raises(StorageSchemaError):
        build_terraform_summary_query_sql("/tmp/fixture", repository_identity="invalid spaces")
    with pytest.raises(StorageSchemaError):
        build_terraform_summary_query_sql("/tmp/fixture", repository_identity="repo1:bad;semi")


def _summary_payload(
    *,
    root_path: str = "/tmp/psycopg77-public",
    repository_name: str | None = "psycopg77-public",
    count: int = 1,
) -> dict[str, object]:
    return {
        "root_path": root_path,
        "repository_name": repository_name,
        "terraform_observations": count,
        "terraform_files": count,
        **{
            map_name: {key: count for key in required_keys}
            for map_name, required_keys in COUNT_MAP_KEYS.items()
        },
        "tfvars": {
            "files": count,
            "variables": count,
            "literal_values_exposed": False,
        },
        "safety": {key: True for key in SAFETY_KEYS},
    }
