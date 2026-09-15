from __future__ import annotations


from repomap_test_support.storage_rows_contracts import _nix_summary_payload


def test_nix_summary_from_storage_payload_nix_helpers_records_contracts() -> None:
    import repomap_kg.storage.summary_rows_nix as summary_rows_nix
    payload = _nix_summary_payload()

    flake_inputs = summary_rows_nix._nix_flake_inputs_from_payload(
        payload,
        label="nix summary",
    )
    assert flake_inputs["total"] == 4
    assert flake_inputs["source_types"]["github"] == 1
    assert flake_inputs["source_types"]["follows"] == 1

    output_sections = summary_rows_nix._nix_nested_count_map_from_payload(
        payload,
        "output_sections",
        {
            "by_section": summary_rows_nix.NIX_OUTPUT_SECTION_NAMES,
            "by_family": summary_rows_nix.NIX_OUTPUT_SECTION_FAMILIES,
            "by_shape": summary_rows_nix.NIX_OUTPUT_SECTION_SHAPES,
        },
        label="nix summary",
    )
    assert output_sections["total"] == 6
    assert output_sections["by_section"]["overlays"] == 1
    assert output_sections["by_shape"]["helper_framework"] == 1

    summary = summary_rows_nix.nix_summary_from_storage_payload(payload)
    assert summary.to_dict()["root_path"] == "/tmp/repo's root"
    assert summary.to_dict()["canonical"]["output_sections"] == 5
    assert summary.to_dict()["edges"]["output_section_defines"] == 3
    assert summary.to_dict()["edges"]["output_defines"] == 2
    assert summary.to_dict()["paths"] == {
        "path_refs_total": 2,
        "local": 1,
        "dynamic": 0,
        "unknown": 1,
        "repo_escaping_or_rejected": 0,
    }
    assert summary.to_dict()["limitations"] == {
        "flake_inputs_not_extracted": True,
        "overlays_not_extracted": True,
        "modules_not_classified": True,
        "packages_are_static_attr_counts_only": True,
        "no_nix_eval": True,
        "no_flake_lock_resolution": True,
        "path_values_omitted": True,
        "weak_output_sections_are_not_concrete_outputs": True,
    }
    assert summary.to_dict()["safety"] == {
        "read_only": True,
        "no_execution": True,
        "no_nix_cli": True,
        "no_fetch": True,
        "no_flake_lock_resolution": True,
        "no_store_inspection": True,
        "no_path_values": True,
        "private_paths_redacted": True,
        "raw_profile_only": True,
    }
    assert summary_rows_nix.NixSummaryRecord(**summary.to_dict()).to_dict() == (
        summary.to_dict()
    )
