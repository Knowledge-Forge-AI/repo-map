from __future__ import annotations

import ast
from pathlib import Path


STORAGE_MAIN_FACADE_OWNERSHIP = (
    ("StorageSchemaError", "common_lore_index.storage.errors"),
    ("run_psql", "common_lore_index.storage.psql"),
    ("query_canonical_node_records", "common_lore_index.storage.canonical"),
    ("CanonicalStorageSummaryRecord", "common_lore_index.storage.rows"),
    ("format_canonical_storage_summary_table", "common_lore_index.storage.rows"),
    ("build_canonical_storage_summary_query_sql", "common_lore_index.storage.sql"),
    ("query_canonical_storage_summary", "common_lore_index.storage.canonical"),
)

STORAGE_SQL_FACADE_OWNERSHIP = (
    ("sql_literal", "common_lore_index.storage.sql_core"),
    ("file_upsert_sql", "common_lore_index.storage.sql_load"),
    ("build_canonical_node_query_sql", "common_lore_index.storage.sql_canonical"),
    ("build_source_summary_query_sql", "common_lore_index.storage.sql_sources"),
    ("build_python_summary_query_sql", "common_lore_index.storage.sql_summaries_python"),
    ("build_nix_summary_query_sql", "common_lore_index.storage.sql_summaries_nix"),
)

STORAGE_SUMMARY_ROWS_FACADE_OWNERSHIP = (
    ("CanonicalStorageSummaryRecord", "common_lore_index.storage.summary_rows_storage"),
    ("RubySummaryRecord", "common_lore_index.storage.summary_rows_languages"),
    ("OpenAPISummaryRecord", "common_lore_index.storage.summary_rows_domains"),
    ("BulkSummaryRecord", "common_lore_index.storage.summary_rows_manifest"),
    ("NixSummaryRecord", "common_lore_index.storage.summary_rows_nix"),
    ("nix_summary_from_storage_payload", "common_lore_index.storage.summary_rows_nix"),
)

STORAGE_ROWS_FACADE_OWNERSHIP = (
    ("payload_text", "common_lore_index.storage.row_helpers"),
    ("FileRow", "common_lore_index.storage.file_rows"),
    ("CanonicalNodeRow", "common_lore_index.storage.canonical_rows"),
    ("CanonicalNodeRecord", "common_lore_index.storage.canonical_readback_rows"),
    ("SourceSummaryRecord", "common_lore_index.storage.source_rows"),
    ("CanonicalStorageSummaryRecord", "common_lore_index.storage.summary_rows"),
    ("canonical_storage_summary_to_jsonable", "common_lore_index.storage.jsonable_rows"),
    ("format_canonical_storage_summary_table", "common_lore_index.storage.table_rows"),
)


def test_pkg3_storage_package_exports_compatibility_surface() -> None:
    import common_lore_index.storage as storage
    import common_lore_index.storage.main as main_module
    import common_lore_index.storage.errors as errors_module
    import common_lore_index.storage.rows as rows_module
    import common_lore_index.storage.psql as psql_module
    import common_lore_index.storage.sql as sql_module

    assert storage.StorageSchemaError is errors_module.StorageSchemaError
    assert storage.LoadSummary is rows_module.LoadSummary
    assert storage.run_psql is psql_module.run_psql
    assert storage.parse_psql_json is psql_module.parse_psql_json
    assert storage.sql_literal is sql_module.sql_literal
    assert storage.discover_migrations is main_module.discover_migrations
    assert not hasattr(storage, "load_file_observations")
    assert not hasattr(storage, "load_canonical_observations")
    assert not hasattr(main_module, "load_file_observations")
    assert not hasattr(main_module, "load_canonical_observations")


def test_storage_facade_ownership_package_root_mirrors_main() -> None:
    import common_lore_index.storage as storage
    import common_lore_index.storage.main as main_module
    import common_lore_index.storage.errors as errors_pkg
    import common_lore_index.storage.psql as psql_pkg
    import common_lore_index.storage.canonical as canonical_pkg
    import common_lore_index.storage.rows as rows_pkg
    import common_lore_index.storage.sql as sql_pkg

    owner_modules = {
        "common_lore_index.storage.errors": errors_pkg,
        "common_lore_index.storage.psql": psql_pkg,
        "common_lore_index.storage.canonical": canonical_pkg,
        "common_lore_index.storage.rows": rows_pkg,
        "common_lore_index.storage.sql": sql_pkg,
    }

    for name, owner_module_name in STORAGE_MAIN_FACADE_OWNERSHIP:
        owner_module = owner_modules[owner_module_name]
        owner = getattr(owner_module, name)
        assert getattr(main_module, name) is owner
        assert getattr(storage, name) is owner


def test_storage_facade_ownership_rows_sql_and_summary_facades() -> None:
    import common_lore_index.storage as storage
    import common_lore_index.storage.main as storage_main
    import common_lore_index.storage.rows as rows_module
    import common_lore_index.storage.sql as sql_module
    import common_lore_index.storage.rows as storage_rows
    import common_lore_index.storage.sql as storage_sql
    import common_lore_index.storage.summary_rows as summary_rows

    import common_lore_index.storage.row_helpers as row_helpers_mod
    import common_lore_index.storage.file_rows as file_rows_mod
    import common_lore_index.storage.canonical_rows as canonical_rows_mod
    import common_lore_index.storage.canonical_readback_rows as canonical_readback_rows_mod
    import common_lore_index.storage.source_rows as source_rows_mod
    import common_lore_index.storage.jsonable_rows as jsonable_rows_mod
    import common_lore_index.storage.table_rows as table_rows_mod

    rows_owners = {
        "common_lore_index.storage.row_helpers": row_helpers_mod,
        "common_lore_index.storage.file_rows": file_rows_mod,
        "common_lore_index.storage.canonical_rows": canonical_rows_mod,
        "common_lore_index.storage.canonical_readback_rows": canonical_readback_rows_mod,
        "common_lore_index.storage.source_rows": source_rows_mod,
        "common_lore_index.storage.summary_rows": summary_rows,
        "common_lore_index.storage.jsonable_rows": jsonable_rows_mod,
        "common_lore_index.storage.table_rows": table_rows_mod,
    }

    for name, owner_module_name in STORAGE_ROWS_FACADE_OWNERSHIP:
        owner = getattr(rows_owners[owner_module_name], name)
        assert getattr(rows_module, name) is owner
        assert getattr(storage_rows, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner

    import common_lore_index.storage.sql_core as sql_core_mod
    import common_lore_index.storage.sql_load as sql_load_mod
    import common_lore_index.storage.sql_canonical as sql_canonical_mod
    import common_lore_index.storage.sql_sources as sql_sources_mod
    import common_lore_index.storage.sql_summaries_python as sql_summaries_python_mod
    import common_lore_index.storage.sql_summaries_nix as sql_summaries_nix_mod

    sql_owners = {
        "common_lore_index.storage.sql_core": sql_core_mod,
        "common_lore_index.storage.sql_load": sql_load_mod,
        "common_lore_index.storage.sql_canonical": sql_canonical_mod,
        "common_lore_index.storage.sql_sources": sql_sources_mod,
        "common_lore_index.storage.sql_summaries_python": sql_summaries_python_mod,
        "common_lore_index.storage.sql_summaries_nix": sql_summaries_nix_mod,
    }

    for name, owner_module_name in STORAGE_SQL_FACADE_OWNERSHIP:
        owner = getattr(sql_owners[owner_module_name], name)
        assert getattr(sql_module, name) is owner
        assert getattr(storage_sql, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner

    import common_lore_index.storage.summary_rows_storage as summary_rows_storage_mod
    import common_lore_index.storage.summary_rows_languages as summary_rows_languages_mod
    import common_lore_index.storage.summary_rows_domains as summary_rows_domains_mod
    import common_lore_index.storage.summary_rows_manifest as summary_rows_manifest_mod
    import common_lore_index.storage.summary_rows_nix as summary_rows_nix_mod

    summary_rows_owners = {
        "common_lore_index.storage.summary_rows_storage": summary_rows_storage_mod,
        "common_lore_index.storage.summary_rows_languages": summary_rows_languages_mod,
        "common_lore_index.storage.summary_rows_domains": summary_rows_domains_mod,
        "common_lore_index.storage.summary_rows_manifest": summary_rows_manifest_mod,
        "common_lore_index.storage.summary_rows_nix": summary_rows_nix_mod,
    }

    for name, owner_module_name in STORAGE_SUMMARY_ROWS_FACADE_OWNERSHIP:
        owner = getattr(summary_rows_owners[owner_module_name], name)
        assert getattr(summary_rows, name) is owner
        assert getattr(rows_module, name) is owner
        assert getattr(storage_rows, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner


def test_storage_package_static_export_visibility() -> None:
    import common_lore_index.storage as storage_pkg
    import common_lore_index.storage.main as main_module
    assert storage_pkg.__file__ is not None
    source_path = Path(storage_pkg.__file__)
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text)

    assert "globals().update" not in source_text

    reexports: dict[str, str] = {}
    import_module_alias: str | None = None
    has_dunder_names_assign = False

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "common_lore_index.storage.main":
                for alias in node.names:
                    assert alias.asname is not None, f"Expected explicit alias for {alias.name}"
                    assert alias.name == alias.asname, f"Expected same-name alias for {alias.name}"
                    reexports[alias.name] = alias.asname
            elif node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        assert alias.asname is not None, "Expected explicit alias for import_module"
                        import_module_alias = alias.asname
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_MODULE_DUNDER_NAMES":
                    has_dunder_names_assign = True

    main_non_dunder = {
        name
        for name in dir(main_module)
        if not (name.startswith("__") and name.endswith("__"))
    }
    assert set(reexports.keys()) == main_non_dunder
    assert "subprocess" in reexports
    assert "hashlib" in reexports
    assert "re" in reexports
    assert "sysconfig" in reexports
    assert import_module_alias == "import_module"
    assert has_dunder_names_assign


def test_storage_package_complete_positive_namespace_identity() -> None:
    import common_lore_index.storage as storage
    import common_lore_index.storage.main as main_module
    from importlib import import_module

    main_non_dunder = [
        name
        for name in dir(main_module)
        if not (name.startswith("__") and name.endswith("__"))
    ]
    assert len(main_non_dunder) >= 240

    for name in main_non_dunder:
        assert hasattr(storage, name), f"Missing positive export: {name}"
        assert getattr(storage, name) is getattr(main_module, name), f"Identity mismatch for: {name}"

    assert hasattr(storage, "import_module")
    assert storage.import_module is import_module
    assert hasattr(storage, "_impl")
    assert storage._impl is main_module
    assert hasattr(storage, "_MODULE_DUNDER_NAMES")
    assert storage._MODULE_DUNDER_NAMES == {
        "__builtins__",
        "__cached__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
    }


def test_storage_package_negative_export_and_namespace_regression() -> None:
    import common_lore_index.storage as storage

    absent_sql_load_names = (
        "run_completion_statements",
        "_canonical_load_summary_select_sql_counts",
        "RunPublicationReceipt",
        "json",
    )
    for name in absent_sql_load_names:
        assert not hasattr(storage, name), f"Expected {name} to be absent from storage"

    absent_legacy_names = (
        "load_file_observations",
        "load_canonical_observations",
        "build_file_ingest_sql",
        "build_file_canonical_ingest_sql",
        "legacy_file_ingest_statements",
        "file_node_upsert_sql",
        "file_evidence_upsert_sql",
        "relationship_source_node_upsert_sql",
        "relationship_target_node_upsert_sql",
        "relationship_evidence_upsert_sql",
        "relationship_edge_upsert_sql",
        "FileNodeRecord",
        "file_node_record_from_storage_payload",
        "file_node_records_to_jsonable",
        "format_file_node_table",
        "query_file_node_records",
        "build_file_node_query_sql",
    )
    for name in absent_legacy_names:
        assert not hasattr(storage, name), f"Expected legacy name {name} to be absent from storage"

    assert not hasattr(storage, "__all__")
