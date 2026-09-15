from __future__ import annotations

import ast
from pathlib import Path


STORAGE_MAIN_FACADE_OWNERSHIP = (
    ("StorageSchemaError", "repomap_kg.storage.errors"),
    ("run_psql", "repomap_kg.storage.psql"),
    ("query_canonical_node_records", "repomap_kg.storage.canonical"),
    ("CanonicalStorageSummaryRecord", "repomap_kg.storage.rows"),
    ("format_canonical_storage_summary_table", "repomap_kg.storage.rows"),
    ("build_canonical_storage_summary_query_sql", "repomap_kg.storage.sql"),
    ("query_canonical_storage_summary", "repomap_kg.storage.canonical"),
)

STORAGE_SQL_FACADE_OWNERSHIP = (
    ("sql_literal", "repomap_kg.storage.sql_core"),
    ("file_upsert_sql", "repomap_kg.storage.sql_load"),
    ("build_canonical_node_query_sql", "repomap_kg.storage.sql_canonical"),
    ("build_source_summary_query_sql", "repomap_kg.storage.sql_sources"),
    ("build_python_summary_query_sql", "repomap_kg.storage.sql_summaries_python"),
    ("build_nix_summary_query_sql", "repomap_kg.storage.sql_summaries_nix"),
)

STORAGE_SUMMARY_ROWS_FACADE_OWNERSHIP = (
    ("CanonicalStorageSummaryRecord", "repomap_kg.storage.summary_rows_storage"),
    ("RubySummaryRecord", "repomap_kg.storage.summary_rows_languages"),
    ("OpenAPISummaryRecord", "repomap_kg.storage.summary_rows_domains"),
    ("BulkSummaryRecord", "repomap_kg.storage.summary_rows_manifest"),
    ("NixSummaryRecord", "repomap_kg.storage.summary_rows_nix"),
    ("nix_summary_from_storage_payload", "repomap_kg.storage.summary_rows_nix"),
)

STORAGE_ROWS_FACADE_OWNERSHIP = (
    ("payload_text", "repomap_kg.storage.row_helpers"),
    ("FileRow", "repomap_kg.storage.file_rows"),
    ("CanonicalNodeRow", "repomap_kg.storage.canonical_rows"),
    ("CanonicalNodeRecord", "repomap_kg.storage.canonical_readback_rows"),
    ("SourceSummaryRecord", "repomap_kg.storage.source_rows"),
    ("CanonicalStorageSummaryRecord", "repomap_kg.storage.summary_rows"),
    ("canonical_storage_summary_to_jsonable", "repomap_kg.storage.jsonable_rows"),
    ("format_canonical_storage_summary_table", "repomap_kg.storage.table_rows"),
)


def test_pkg3_storage_package_exports_compatibility_surface() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as main_module
    import repomap_kg.storage.errors as errors_module
    import repomap_kg.storage.rows as rows_module
    import repomap_kg.storage.psql as psql_module
    import repomap_kg.storage.sql as sql_module

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
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as main_module
    import repomap_kg.storage.errors as errors_pkg
    import repomap_kg.storage.psql as psql_pkg
    import repomap_kg.storage.canonical as canonical_pkg
    import repomap_kg.storage.rows as rows_pkg
    import repomap_kg.storage.sql as sql_pkg

    owner_modules = {
        "repomap_kg.storage.errors": errors_pkg,
        "repomap_kg.storage.psql": psql_pkg,
        "repomap_kg.storage.canonical": canonical_pkg,
        "repomap_kg.storage.rows": rows_pkg,
        "repomap_kg.storage.sql": sql_pkg,
    }

    for name, owner_module_name in STORAGE_MAIN_FACADE_OWNERSHIP:
        owner_module = owner_modules[owner_module_name]
        owner = getattr(owner_module, name)
        assert getattr(main_module, name) is owner
        assert getattr(storage, name) is owner


def test_storage_facade_ownership_rows_sql_and_summary_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.rows as rows_module
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.rows as storage_rows
    import repomap_kg.storage.sql as storage_sql
    import repomap_kg.storage.summary_rows as summary_rows

    import repomap_kg.storage.row_helpers as row_helpers_mod
    import repomap_kg.storage.file_rows as file_rows_mod
    import repomap_kg.storage.canonical_rows as canonical_rows_mod
    import repomap_kg.storage.canonical_readback_rows as canonical_readback_rows_mod
    import repomap_kg.storage.source_rows as source_rows_mod
    import repomap_kg.storage.jsonable_rows as jsonable_rows_mod
    import repomap_kg.storage.table_rows as table_rows_mod

    rows_owners = {
        "repomap_kg.storage.row_helpers": row_helpers_mod,
        "repomap_kg.storage.file_rows": file_rows_mod,
        "repomap_kg.storage.canonical_rows": canonical_rows_mod,
        "repomap_kg.storage.canonical_readback_rows": canonical_readback_rows_mod,
        "repomap_kg.storage.source_rows": source_rows_mod,
        "repomap_kg.storage.summary_rows": summary_rows,
        "repomap_kg.storage.jsonable_rows": jsonable_rows_mod,
        "repomap_kg.storage.table_rows": table_rows_mod,
    }

    for name, owner_module_name in STORAGE_ROWS_FACADE_OWNERSHIP:
        owner = getattr(rows_owners[owner_module_name], name)
        assert getattr(rows_module, name) is owner
        assert getattr(storage_rows, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner

    import repomap_kg.storage.sql_core as sql_core_mod
    import repomap_kg.storage.sql_load as sql_load_mod
    import repomap_kg.storage.sql_canonical as sql_canonical_mod
    import repomap_kg.storage.sql_sources as sql_sources_mod
    import repomap_kg.storage.sql_summaries_python as sql_summaries_python_mod
    import repomap_kg.storage.sql_summaries_nix as sql_summaries_nix_mod

    sql_owners = {
        "repomap_kg.storage.sql_core": sql_core_mod,
        "repomap_kg.storage.sql_load": sql_load_mod,
        "repomap_kg.storage.sql_canonical": sql_canonical_mod,
        "repomap_kg.storage.sql_sources": sql_sources_mod,
        "repomap_kg.storage.sql_summaries_python": sql_summaries_python_mod,
        "repomap_kg.storage.sql_summaries_nix": sql_summaries_nix_mod,
    }

    for name, owner_module_name in STORAGE_SQL_FACADE_OWNERSHIP:
        owner = getattr(sql_owners[owner_module_name], name)
        assert getattr(sql_module, name) is owner
        assert getattr(storage_sql, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner

    import repomap_kg.storage.summary_rows_storage as summary_rows_storage_mod
    import repomap_kg.storage.summary_rows_languages as summary_rows_languages_mod
    import repomap_kg.storage.summary_rows_domains as summary_rows_domains_mod
    import repomap_kg.storage.summary_rows_manifest as summary_rows_manifest_mod
    import repomap_kg.storage.summary_rows_nix as summary_rows_nix_mod

    summary_rows_owners = {
        "repomap_kg.storage.summary_rows_storage": summary_rows_storage_mod,
        "repomap_kg.storage.summary_rows_languages": summary_rows_languages_mod,
        "repomap_kg.storage.summary_rows_domains": summary_rows_domains_mod,
        "repomap_kg.storage.summary_rows_manifest": summary_rows_manifest_mod,
        "repomap_kg.storage.summary_rows_nix": summary_rows_nix_mod,
    }

    for name, owner_module_name in STORAGE_SUMMARY_ROWS_FACADE_OWNERSHIP:
        owner = getattr(summary_rows_owners[owner_module_name], name)
        assert getattr(summary_rows, name) is owner
        assert getattr(rows_module, name) is owner
        assert getattr(storage_rows, name) is owner
        assert getattr(storage_main, name) is owner
        assert getattr(storage, name) is owner


def test_storage_package_static_export_visibility() -> None:
    import repomap_kg.storage as storage_pkg
    import repomap_kg.storage.main as main_module
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
            if node.module == "repomap_kg.storage.main":
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
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as main_module
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
    import repomap_kg.storage as storage

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
