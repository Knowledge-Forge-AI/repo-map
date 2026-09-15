from __future__ import annotations
import json



EXPECTED_FIELDS = tuple(
    "root_path repository_name terraform_observations terraform_files "
    "file_families terraform references tfvars redactions diagnostics "
    "generic_config safety".split()
)


COUNT_MAP_KEYS = {
    "file_families": ("tf", "tfvars", "terraform.tfvars", "auto.tfvars"),
    "terraform": tuple(
        "blocks providers required_providers required_versions backends resources "
        "data_sources modules variables outputs locals moved imports checks removed".split()
    ),
    "references": tuple(
        "total provider_sources version_constraints module_sources local_module_refs "
        "remote_refs_not_fetched depends_on provider_aliases "
        "repo_escape_diagnostics".split()
    ),
    "redactions": tuple(
        "tfvars_values secret_like_fields credentialed_urls import_ids "
        "backend_values".split()
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


SAFETY_KEYS = tuple(
    "no_execution no_fetch no_terraform_cli no_provider_download "
    "no_module_download no_state_access tfvars_redacted raw_profile_only "
    "no_new_canonical_namespaces".split()
)


WRAPPER_FIELDS = set(
    "server version read_only graph summary_kind summary safety".split()
)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _integer(value: object) -> int:
    assert isinstance(value, int)
    return value


def _assert_meaningful_hcl_contract(payload: dict[str, object]) -> None:
    assert payload["root_path"] == "/tmp/psycopg77-terraform-public"
    assert payload["repository_name"] == "psycopg77-public"
    assert _integer(payload["terraform_observations"]) > 0
    assert payload["terraform_files"] == 5
    assert payload["file_families"] == {
        "tf": 2,
        "tfvars": 1,
        "terraform.tfvars": 1,
        "auto.tfvars": 1,
    }
    assert all(_mapping(payload["terraform"]).values())
    assert _mapping(payload["references"])["provider_sources"] == 1
    assert _mapping(payload["references"])["module_sources"] == 2
    assert _mapping(payload["references"])["remote_refs_not_fetched"] == 2
    assert all(_mapping(payload["redactions"]).values())
    assert payload["diagnostics"] == {
        "parse_errors": 3,
        "limit_overflows": 1,
        "malformed_hcl": 2,
    }
    assert _mapping(payload["tfvars"]) == {
        "files": 3,
        "variables": 1,
        "literal_values_exposed": False,
    }
    assert _integer(_mapping(payload["generic_config"])["config_documents"]) > 0
    assert _integer(_mapping(payload["generic_config"])["config_paths"]) > 0
    assert _mapping(payload["generic_config"])["file_nodes"] == 1
    assert all(_mapping(payload["safety"]).values())


def _assert_meaningful_tfjson_contract(payload: dict[str, object]) -> None:
    assert payload["repository_name"] == "psycopg77-tfjson"
    assert payload["terraform_files"] == 2
    assert payload["file_families"] == {
        "tf": 1,
        "tfvars": 1,
        "terraform.tfvars": 0,
        "auto.tfvars": 0,
    }
    assert _mapping(payload["terraform"])["resources"] == 1
    assert _mapping(payload["terraform"])["modules"] == 1
    assert _mapping(payload["references"])["total"] == 6
    assert _integer(_mapping(payload["generic_config"])["config_documents"]) > 0


def _assert_unknown_root(payload: dict[str, object]) -> None:
    assert payload["repository_name"] is None
    assert payload["terraform_observations"] == payload["terraform_files"] == 0
    assert all(
        value == 0
        for name in COUNT_MAP_KEYS
        for value in _mapping(payload[name]).values()
    )
    assert _mapping(payload["tfvars"]) == {
        "files": 0,
        "variables": 0,
        "literal_values_exposed": False,
    }
    assert all(_mapping(payload["safety"]).values())


def _assert_terraform_empty(payload: dict[str, object]) -> None:
    assert payload["repository_name"] == "psycopg77-empty"
    assert payload["terraform_observations"] == payload["terraform_files"] == 0
    assert all(
        value == 0
        for name in COUNT_MAP_KEYS
        if name != "generic_config"
        for value in _mapping(payload[name]).values()
    )
    assert _integer(_mapping(payload["generic_config"])["config_documents"]) > 0
    assert _integer(_mapping(payload["generic_config"])["config_paths"]) > 0
    assert _mapping(payload["generic_config"])["file_nodes"] == 1
    assert _mapping(payload["tfvars"])["literal_values_exposed"] is False
    assert all(_mapping(payload["safety"]).values())


def _assert_nested_key_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert sum(len(_mapping(payload[name])) for name in COUNT_MAP_KEYS) == 40
    for name, required_keys in COUNT_MAP_KEYS.items():
        assert tuple(_mapping(payload[name])) == required_keys
    assert tuple(_mapping(payload["tfvars"])) == TFVARS_KEYS
    assert tuple(_mapping(payload["safety"])) == SAFETY_KEYS


def _successful_json(result: tuple[int, str, str]) -> dict[str, object]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _private_markers(private_root: str) -> tuple[str, ...]:
    return (
        private_root,
        "synthetic-private",
        "synthetic/main.tf",
        "private-resource-name",
        "private-module-name",
        "private/provider-source",
        "https://user:password@private.invalid/module",
        "private-version-constraint",
        "private-backend-value",
        "private-state-path",
        "private-import-id",
        "private-tfvars-literal",
        "private-expression",
        "private-parser-diagnostic",
        "private-source-snippet",
        "private-raw-hcl",
        "private-raw-json",
        "private-credential",
        "private-secret",
        "private-token",
    )
