from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    NixSummaryRecord,
    StorageSchemaError,
    build_nix_summary_query_sql,
    query_nix_summary,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "nix_observations",
    "nix_files",
    "flake_files",
    "raw",
    "canonical",
    "edges",
    "programs",
    "paths",
    "flake_inputs",
    "output_sections",
    "dynamic_output_shapes",
    "unsupported_flake_shapes",
    "generic_config",
    "diagnostics",
    "limitations",
    "safety",
)


def test_psycopg62_query_nix_summary_uses_object_readback_adapter() -> None:
    payload = _nix_summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("Nix summary must use the adapter"),
        ),
    ):
        record = query_nix_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/fixture",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_nix_summary_query_sql("/tmp/fixture"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="nix summary",
        expected_shape="object",
    )
    assert tuple(field.name for field in fields(NixSummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload


def test_psycopg62_query_nix_summary_preserves_unknown_root_defaults() -> None:
    payload = _nix_summary_payload(zeroed=True)

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_nix_summary(
            ["-d", "postgres"],
            root_path="/tmp/missing",
        )

    assert record.to_dict() == payload
    assert record.repository_name is None
    assert record.nix_observations == 0
    assert all(value == 0 for value in record.raw.values())
    assert all(value == 0 for value in record.flake_inputs["source_types"].values())
    assert record.limitations["no_nix_eval"] is True
    assert record.safety["private_paths_redacted"] is True


@pytest.mark.parametrize("invalid_payload", [[], "scalar"])
def test_psycopg62_query_nix_summary_propagates_adapter_shape_errors(
    invalid_payload,
) -> None:
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        side_effect=StorageSchemaError("psql returned a malformed nix summary"),
    ) as execute_json_readback:
        with pytest.raises(StorageSchemaError, match="malformed nix summary"):
            query_nix_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )

    assert invalid_payload in ([], "scalar")
    assert execute_json_readback.call_args.kwargs["expected_shape"] == "object"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.pop("raw"), "raw"),
        (lambda payload: payload["raw"].pop("imports"), "raw"),
        (lambda payload: payload["raw"].update(imports="not-a-count"), "raw"),
        (
            lambda payload: payload["limitations"].update(no_nix_eval=1),
            "limitations",
        ),
        (
            lambda payload: payload["safety"].update(no_execution="true"),
            "safety",
        ),
    ],
)
def test_psycopg62_query_nix_summary_preserves_nested_schema_errors(
    mutate,
    message: str,
) -> None:
    payload = _nix_summary_payload()
    mutate(payload)

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match=message):
            query_nix_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


def test_psycopg62_query_nix_summary_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_nix_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def _nix_summary_payload(*, zeroed: bool = False) -> dict[str, object]:
    count = 0 if zeroed else 1
    payload: dict[str, object] = {
        "root_path": "[root-path]",
        "repository_name": None if zeroed else "fixture",
        "nix_observations": count,
        "nix_files": count,
        "flake_files": count,
        "raw": _counts(
            "imports", "path_refs", "apps", "packages", "dev_shells", "checks",
            value=count,
        ),
        "canonical": _counts(
            "apps", "packages", "dev_shells", "checks", "output_sections",
            value=count,
        ),
        "edges": _counts(
            "import_sources",
            "output_defines",
            "output_section_defines",
            "app_program_edges",
            value=count,
        ),
        "programs": _counts(
            "app_programs_total", "local", "dynamic", "external", "unknown",
            value=count,
        ),
        "paths": _counts(
            "path_refs_total",
            "local",
            "dynamic",
            "unknown",
            "repo_escaping_or_rejected",
            value=count,
        ),
        "flake_inputs": {
            "total": count,
            "with_url": count,
            "with_follows": count,
            "redacted_sources": count,
            "source_types": _counts(
                "github", "git", "path", "tarball", "follows", "unknown", "dynamic",
                value=count,
            ),
        },
        "output_sections": {
            "total": count,
            "by_section": _counts(
                "packages", "apps", "devShells", "checks", "nixosModules",
                "darwinModules", "homeManagerModules", "overlays", "formatter",
                "templates", "legacyPackages", value=count,
            ),
            "by_family": _counts(
                "output", "module", "overlay", "formatter", "template",
                "legacy_package", value=count,
            ),
            "by_shape": _counts(
                "direct_assignment", "nested_attrset", "inherit", "merged_attrset",
                "dynamic", "helper_framework", "unknown", value=count,
            ),
        },
        "dynamic_output_shapes": {
            "total": count,
            "by_pattern": _counts(
                "eachDefaultSystem", "genAttrs", "forAllSystems", "flake-utils",
                "flake-parts", "string_interpolation", value=count,
            ),
        },
        "unsupported_flake_shapes": {
            "total": count,
            "by_pattern": _counts(
                "imported_outputs", "merged_attrset", "inherit_outputs",
                "nested_attrset_without_direct_identity", "template_section",
                "legacy_packages_section", "unknown_dynamic", value=count,
            ),
        },
        "generic_config": _counts(
            "config_documents", "config_paths", "config_references",
            "config_parse_errors", "config_redactions", value=count,
        ),
        "diagnostics": _counts(
            "missing_output_identity", "dynamic_imports", "unknown_imports",
            "unknown_app_programs", "raw_only_path_refs",
            "flake_files_without_output_observations", value=count,
        ),
        "limitations": {
            "flake_inputs_not_extracted": False,
            "overlays_not_extracted": True,
            "modules_not_classified": True,
            "packages_are_static_attr_counts_only": True,
            "no_nix_eval": True,
            "no_flake_lock_resolution": True,
            "path_values_omitted": True,
            "weak_output_sections_are_not_concrete_outputs": True,
        },
        "safety": {
            "read_only": True,
            "no_execution": True,
            "no_nix_cli": True,
            "no_fetch": True,
            "no_flake_lock_resolution": True,
            "no_store_inspection": True,
            "no_path_values": True,
            "private_paths_redacted": True,
            "raw_profile_only": True,
        },
    }
    return deepcopy(payload)


def _counts(*keys: str, value: int) -> dict[str, int]:
    return {key: value for key in keys}
