"""Observation fixture construction examples for storage row tests."""

from __future__ import annotations

from repomap_kg.observations.raw import RawObservation


def _file_observation(path: str, *, source_id: str | None = None) -> RawObservation:
    return RawObservation(
        kind="file",
        source_id=source_id or path,
        path=path,
        confidence="manual",
        extractor="fixture-discovery",
        extractor_version="1",
        metadata={
            "language": "python",
            "role": "source",
            "content_hash": None,
            "generated": False,
            "executable": False,
            "line_count": 0,
            "description": "",
            "tags": [],
            "settings": {},
        },
    )


def _shell_observation(
    source_id: str,
    path: str,
    target: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    command: str = "echo",
) -> RawObservation:
    return RawObservation(
        kind="shell.command",
        source_id=source_id,
        path=path,
        start_line=start_line,
        end_line=end_line,
        name=f"{command} fixture",
        target=target,
        confidence="heuristic",
        extractor="fixture-shell",
        extractor_version="1",
        metadata={"command": command, "argv": [command]},
    )


def _nix_summary_payload() -> dict[str, object]:
    return {
        "root_path": "/tmp/repo's root",
        "repository_name": "repo-map",
        "nix_observations": "21",
        "nix_files": "3",
        "flake_files": "1",
        "raw": {
            "imports": "1",
            "path_refs": "2",
            "apps": "3",
            "packages": "4",
            "dev_shells": "5",
            "checks": "6",
        },
        "canonical": {
            "apps": "1",
            "packages": "2",
            "dev_shells": "3",
            "checks": "4",
            "output_sections": "5",
        },
        "edges": {
            "import_sources": "1",
            "output_defines": "2",
            "output_section_defines": "3",
            "app_program_edges": "4",
        },
        "programs": {
            "app_programs_total": "5",
            "local": "1",
            "dynamic": "2",
            "external": "1",
            "unknown": "1",
        },
        "paths": {
            "path_refs_total": "2",
            "local": "1",
            "dynamic": "0",
            "unknown": "1",
            "repo_escaping_or_rejected": "0",
        },
        "flake_inputs": {
            "total": "4",
            "with_url": "2",
            "with_follows": "1",
            "redacted_sources": "1",
            "source_types": {
                "github": "1",
                "git": "1",
                "path": "0",
                "tarball": "0",
                "follows": "1",
                "unknown": "1",
                "dynamic": "0",
            },
        },
        "output_sections": {
            "total": "6",
            "by_section": {
                "packages": "1",
                "apps": "1",
                "devShells": "1",
                "checks": "1",
                "nixosModules": "1",
                "darwinModules": "0",
                "homeManagerModules": "0",
                "overlays": "1",
                "formatter": "0",
                "templates": "0",
                "legacyPackages": "0",
            },
            "by_family": {
                "output": "4",
                "module": "1",
                "overlay": "1",
                "formatter": "0",
                "template": "0",
                "legacy_package": "0",
            },
            "by_shape": {
                "direct_assignment": "2",
                "nested_attrset": "1",
                "inherit": "0",
                "merged_attrset": "1",
                "dynamic": "1",
                "helper_framework": "1",
                "unknown": "0",
            },
        },
        "dynamic_output_shapes": {
            "total": "2",
            "by_pattern": {
                "eachDefaultSystem": "1",
                "genAttrs": "0",
                "forAllSystems": "0",
                "flake-utils": "1",
                "flake-parts": "0",
                "string_interpolation": "0",
            },
        },
        "unsupported_flake_shapes": {
            "total": "3",
            "by_pattern": {
                "imported_outputs": "1",
                "merged_attrset": "1",
                "inherit_outputs": "0",
                "nested_attrset_without_direct_identity": "0",
                "template_section": "0",
                "legacy_packages_section": "0",
                "unknown_dynamic": "1",
            },
        },
        "generic_config": {
            "config_documents": "1",
            "config_paths": "2",
            "config_references": "3",
            "config_parse_errors": "4",
            "config_redactions": "5",
        },
        "diagnostics": {
            "missing_output_identity": "1",
            "dynamic_imports": "2",
            "unknown_imports": "3",
            "unknown_app_programs": "4",
            "raw_only_path_refs": "5",
            "flake_files_without_output_observations": "6",
        },
        "limitations": {
            "flake_inputs_not_extracted": True,
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


file_observation = _file_observation
shell_observation = _shell_observation
nix_summary_payload = _nix_summary_payload

__all__ = [
    "_file_observation",
    "_nix_summary_payload",
    "_shell_observation",
    "file_observation",
    "nix_summary_payload",
    "shell_observation",
]
