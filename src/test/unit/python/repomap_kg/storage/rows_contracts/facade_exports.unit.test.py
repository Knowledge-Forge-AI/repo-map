from __future__ import annotations



from repomap_test_support.storage_rows_contracts import (
CRITICAL_WRITE_ROW_FIELDS,
PURE_HELPER_EXPORT_NAMES,
FILE_INDEX_ROW_EXPORT_NAMES,
CANONICAL_ROW_EXPORT_NAMES,
CANONICAL_READBACK_ROW_EXPORT_NAMES,
SOURCE_ROW_EXPORT_NAMES,
SUMMARY_ROW_EXPORT_NAMES,
SUMMARY_ROW_STORAGE_EXPORT_NAMES,
SUMMARY_ROW_LANGUAGE_EXPORT_NAMES,
SUMMARY_ROW_DOMAIN_EXPORT_NAMES,
SUMMARY_ROW_MANIFEST_EXPORT_NAMES,
SUMMARY_ROW_NIX_EXPORT_NAMES,
)

from repomap_kg.storage import rows


def test_storage_rows_export_surface_and_facade_identity_contracts() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    expected_names = {
        *CRITICAL_WRITE_ROW_FIELDS,
        "file_rows_from_observations",
        "raw_observation_payload_hash",
        "identity_metadata_hash",
        "raw_observation_rows_from_observations",
        "canonical_rows_from_result",
        "canonical_edge_link_row",
        "canonical_node_record_from_storage_payload",
        "payload_string",
        "payload_count_map",
        "manifest_counter",
        "canonical_json_text",
        "canonical_json_value",
    }

    assert expected_names <= set(rows.__all__)
    assert len(rows.__all__) == len(set(rows.__all__))

    for name in expected_names:
        assert getattr(storage, name) is getattr(rows, name)
        assert getattr(storage_main, name) is getattr(rows, name)
        assert getattr(storage_rows_facade, name) is getattr(rows, name)

def test_storage_row_helpers_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.row_helpers as row_helpers
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert row_helpers.__all__ == PURE_HELPER_EXPORT_NAMES

    for name in PURE_HELPER_EXPORT_NAMES:
        helper = getattr(row_helpers, name)
        assert getattr(rows, name) is helper
        assert getattr(storage, name) is helper
        assert getattr(storage_main, name) is helper
        assert getattr(storage_rows_facade, name) is helper

def test_storage_file_index_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.file_rows as file_index_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert file_index_rows.__all__ == FILE_INDEX_ROW_EXPORT_NAMES

    for name in FILE_INDEX_ROW_EXPORT_NAMES:
        file_index_name = getattr(file_index_rows, name)
        assert getattr(rows, name) is file_index_name
        assert getattr(storage, name) is file_index_name
        assert getattr(storage_main, name) is file_index_name
        assert getattr(storage_rows_facade, name) is file_index_name

def test_storage_canonical_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.canonical_rows as canonical_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert canonical_rows.__all__ == CANONICAL_ROW_EXPORT_NAMES

    for name in CANONICAL_ROW_EXPORT_NAMES:
        canonical_name = getattr(canonical_rows, name)
        assert getattr(rows, name) is canonical_name
        assert getattr(storage, name) is canonical_name
        assert getattr(storage_main, name) is canonical_name
        assert getattr(storage_rows_facade, name) is canonical_name

def test_storage_canonical_readback_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.canonical_readback_rows as canonical_readback_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert canonical_readback_rows.__all__ == CANONICAL_READBACK_ROW_EXPORT_NAMES

    for name in CANONICAL_READBACK_ROW_EXPORT_NAMES:
        canonical_readback_name = getattr(canonical_readback_rows, name)
        assert getattr(rows, name) is canonical_readback_name
        assert getattr(storage, name) is canonical_readback_name
        assert getattr(storage_main, name) is canonical_readback_name
        assert getattr(storage_rows_facade, name) is canonical_readback_name

def test_storage_source_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.source_rows as source_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert source_rows.__all__ == SOURCE_ROW_EXPORT_NAMES

    for name in SOURCE_ROW_EXPORT_NAMES:
        source_name = getattr(source_rows, name)
        assert getattr(rows, name) is source_name
        assert getattr(storage, name) is source_name
        assert getattr(storage_main, name) is source_name
        assert getattr(storage_rows_facade, name) is source_name

def test_storage_summary_rows_import_back_through_rows_and_facades() -> None:
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_EXPORT_NAMES:
        summary_name = getattr(summary_rows, name)
        assert getattr(rows, name) is summary_name
        assert getattr(storage, name) is summary_name
        assert getattr(storage_main, name) is summary_name
        assert getattr(storage_rows_facade, name) is summary_name

def test_storage_summary_rows_storage_imports_back_through_facades() -> None:
    import repomap_kg.storage.summary_rows_storage as summary_rows_storage
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows_storage.__all__ == SUMMARY_ROW_STORAGE_EXPORT_NAMES
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_STORAGE_EXPORT_NAMES:
        storage_summary_name = getattr(summary_rows_storage, name)
        assert getattr(summary_rows, name) is storage_summary_name
        assert getattr(rows, name) is storage_summary_name
        assert getattr(storage, name) is storage_summary_name
        assert getattr(storage_main, name) is storage_summary_name
        assert getattr(storage_rows_facade, name) is storage_summary_name

def test_storage_summary_rows_languages_imports_back_through_facades() -> None:
    import repomap_kg.storage.summary_rows_languages as summary_rows_languages
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows_languages.__all__ == SUMMARY_ROW_LANGUAGE_EXPORT_NAMES
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_LANGUAGE_EXPORT_NAMES:
        language_summary_name = getattr(summary_rows_languages, name)
        assert getattr(summary_rows, name) is language_summary_name
        assert getattr(rows, name) is language_summary_name
        assert getattr(storage, name) is language_summary_name
        assert getattr(storage_main, name) is language_summary_name
        assert getattr(storage_rows_facade, name) is language_summary_name

def test_storage_summary_rows_domains_imports_back_through_facades() -> None:
    import repomap_kg.storage.summary_rows_domains as summary_rows_domains
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows_domains.__all__ == SUMMARY_ROW_DOMAIN_EXPORT_NAMES
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_DOMAIN_EXPORT_NAMES:
        domain_summary_name = getattr(summary_rows_domains, name)
        assert getattr(summary_rows, name) is domain_summary_name
        assert getattr(rows, name) is domain_summary_name
        assert getattr(storage, name) is domain_summary_name
        assert getattr(storage_main, name) is domain_summary_name
        assert getattr(storage_rows_facade, name) is domain_summary_name

def test_storage_summary_rows_manifest_imports_back_through_facades() -> None:
    import repomap_kg.storage.summary_rows_manifest as summary_rows_manifest
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows_manifest.__all__ == SUMMARY_ROW_MANIFEST_EXPORT_NAMES
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_MANIFEST_EXPORT_NAMES:
        manifest_summary_name = getattr(summary_rows_manifest, name)
        assert getattr(summary_rows, name) is manifest_summary_name
        assert getattr(rows, name) is manifest_summary_name
        assert getattr(storage, name) is manifest_summary_name
        assert getattr(storage_main, name) is manifest_summary_name
        assert getattr(storage_rows_facade, name) is manifest_summary_name

def test_storage_summary_rows_nix_imports_back_through_facades() -> None:
    import repomap_kg.storage.summary_rows_nix as summary_rows_nix
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as storage_rows_facade
    assert summary_rows_nix.__all__ == SUMMARY_ROW_NIX_EXPORT_NAMES
    assert summary_rows.__all__ == SUMMARY_ROW_EXPORT_NAMES

    for name in SUMMARY_ROW_NIX_EXPORT_NAMES:
        nix_summary_name = getattr(summary_rows_nix, name)
        assert getattr(summary_rows, name) is nix_summary_name
        assert getattr(rows, name) is nix_summary_name
        assert getattr(storage, name) is nix_summary_name
        assert getattr(storage_main, name) is nix_summary_name
        assert getattr(storage_rows_facade, name) is nix_summary_name

    assert (
        summary_rows._nix_flake_inputs_from_payload
        is summary_rows_nix._nix_flake_inputs_from_payload
    )
    assert (
        summary_rows._nix_nested_count_map_from_payload
        is summary_rows_nix._nix_nested_count_map_from_payload
    )
    assert "_nix_flake_inputs_from_payload" not in summary_rows.__all__
    assert "_nix_nested_count_map_from_payload" not in summary_rows.__all__
    assert "_nix_flake_inputs_from_payload" not in rows.__all__
    assert "_nix_nested_count_map_from_payload" not in rows.__all__
