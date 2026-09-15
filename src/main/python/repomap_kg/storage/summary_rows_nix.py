"""Nix summary records and payload decoders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    payload_int,
    payload_json_object,
    payload_optional_text,
    payload_required_bool_map,
    payload_required_count_map,
    payload_text,
)
from repomap_kg.storage.summary_rows_core import (
    _count_from_mapping,
    _required_count_map_from_mapping,
)

__all__ = (
    "NixSummaryRecord",
    "nix_summary_from_storage_payload",
)


@dataclass(frozen=True)
class NixSummaryRecord:
    root_path: str
    repository_name: str | None
    nix_observations: int
    nix_files: int
    flake_files: int
    raw: dict[str, int]
    canonical: dict[str, int]
    edges: dict[str, int]
    programs: dict[str, int]
    paths: dict[str, int]
    flake_inputs: dict[str, Any]
    output_sections: dict[str, Any]
    dynamic_output_shapes: dict[str, Any]
    unsupported_flake_shapes: dict[str, Any]
    generic_config: dict[str, int]
    diagnostics: dict[str, int]
    limitations: dict[str, bool]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NIX_FLAKE_INPUT_SOURCE_TYPES = (
    "github",
    "git",
    "path",
    "tarball",
    "follows",
    "unknown",
    "dynamic",
)
NIX_OUTPUT_SECTION_NAMES = (
    "packages",
    "apps",
    "devShells",
    "checks",
    "nixosModules",
    "darwinModules",
    "homeManagerModules",
    "overlays",
    "formatter",
    "templates",
    "legacyPackages",
)
NIX_OUTPUT_SECTION_FAMILIES = (
    "output",
    "module",
    "overlay",
    "formatter",
    "template",
    "legacy_package",
)
NIX_OUTPUT_SECTION_SHAPES = (
    "direct_assignment",
    "nested_attrset",
    "inherit",
    "merged_attrset",
    "dynamic",
    "helper_framework",
    "unknown",
)
NIX_DYNAMIC_OUTPUT_PATTERNS = (
    "eachDefaultSystem",
    "genAttrs",
    "forAllSystems",
    "flake-utils",
    "flake-parts",
    "string_interpolation",
)
NIX_UNSUPPORTED_FLAKE_PATTERNS = (
    "imported_outputs",
    "merged_attrset",
    "inherit_outputs",
    "nested_attrset_without_direct_identity",
    "template_section",
    "legacy_packages_section",
    "unknown_dynamic",
)


def _nix_flake_inputs_from_payload(
    payload: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    value = payload_json_object(payload, "flake_inputs", label=label)
    return {
        "total": _count_from_mapping(value, "total", label=label),
        "with_url": _count_from_mapping(value, "with_url", label=label),
        "with_follows": _count_from_mapping(value, "with_follows", label=label),
        "redacted_sources": _count_from_mapping(
            value,
            "redacted_sources",
            label=label,
        ),
        "source_types": _required_count_map_from_mapping(
            value,
            "source_types",
            NIX_FLAKE_INPUT_SOURCE_TYPES,
            label=label,
        ),
    }


def _nix_nested_count_map_from_payload(
    payload: dict[str, Any],
    key: str,
    nested_required_keys: Mapping[str, tuple[str, ...]],
    *,
    label: str,
) -> dict[str, Any]:
    value = payload_json_object(payload, key, label=label)
    result: dict[str, Any] = {
        "total": _count_from_mapping(value, "total", label=label)
    }
    for nested_key, required_keys in nested_required_keys.items():
        result[nested_key] = _required_count_map_from_mapping(
            value,
            nested_key,
            required_keys,
            label=label,
        )
    return result


def nix_summary_from_storage_payload(payload: Any) -> NixSummaryRecord:
    label = "nix summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    return NixSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label=label,
        ),
        nix_observations=payload_int(payload, "nix_observations", label=label),
        nix_files=payload_int(payload, "nix_files", label=label),
        flake_files=payload_int(payload, "flake_files", label=label),
        raw=payload_required_count_map(
            payload,
            "raw",
            ("imports", "path_refs", "apps", "packages", "dev_shells", "checks"),
            label=label,
        ),
        canonical=payload_required_count_map(
            payload,
            "canonical",
            ("apps", "packages", "dev_shells", "checks", "output_sections"),
            label=label,
        ),
        edges=payload_required_count_map(
            payload,
            "edges",
            (
                "import_sources",
                "output_defines",
                "output_section_defines",
                "app_program_edges",
            ),
            label=label,
        ),
        programs=payload_required_count_map(
            payload,
            "programs",
            ("app_programs_total", "local", "dynamic", "external", "unknown"),
            label=label,
        ),
        paths=payload_required_count_map(
            payload,
            "paths",
            (
                "path_refs_total",
                "local",
                "dynamic",
                "unknown",
                "repo_escaping_or_rejected",
            ),
            label=label,
        ),
        flake_inputs=_nix_flake_inputs_from_payload(payload, label=label),
        output_sections=_nix_nested_count_map_from_payload(
            payload,
            "output_sections",
            {
                "by_section": NIX_OUTPUT_SECTION_NAMES,
                "by_family": NIX_OUTPUT_SECTION_FAMILIES,
                "by_shape": NIX_OUTPUT_SECTION_SHAPES,
            },
            label=label,
        ),
        dynamic_output_shapes=_nix_nested_count_map_from_payload(
            payload,
            "dynamic_output_shapes",
            {"by_pattern": NIX_DYNAMIC_OUTPUT_PATTERNS},
            label=label,
        ),
        unsupported_flake_shapes=_nix_nested_count_map_from_payload(
            payload,
            "unsupported_flake_shapes",
            {"by_pattern": NIX_UNSUPPORTED_FLAKE_PATTERNS},
            label=label,
        ),
        generic_config=payload_required_count_map(
            payload,
            "generic_config",
            (
                "config_documents",
                "config_paths",
                "config_references",
                "config_parse_errors",
                "config_redactions",
            ),
            label=label,
        ),
        diagnostics=payload_required_count_map(
            payload,
            "diagnostics",
            (
                "missing_output_identity",
                "dynamic_imports",
                "unknown_imports",
                "unknown_app_programs",
                "raw_only_path_refs",
                "flake_files_without_output_observations",
            ),
            label=label,
        ),
        limitations=payload_required_bool_map(
            payload,
            "limitations",
            (
                "flake_inputs_not_extracted",
                "overlays_not_extracted",
                "modules_not_classified",
                "packages_are_static_attr_counts_only",
                "no_nix_eval",
                "no_flake_lock_resolution",
                "path_values_omitted",
                "weak_output_sections_are_not_concrete_outputs",
            ),
            label=label,
        ),
        safety=payload_required_bool_map(
            payload,
            "safety",
            (
                "read_only",
                "no_execution",
                "no_nix_cli",
                "no_fetch",
                "no_flake_lock_resolution",
                "no_store_inspection",
                "no_path_values",
                "private_paths_redacted",
                "raw_profile_only",
            ),
            label=label,
        ),
    )
