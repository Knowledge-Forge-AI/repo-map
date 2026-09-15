from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


RETIRED_STORAGE_ALIAS_MODULES = (
    ("repomap_kg.storage_errors", "repomap_kg.storage.errors"),
    ("repomap_kg.storage_psql", "repomap_kg.storage.psql"),
    ("repomap_kg.storage_summaries", "repomap_kg.storage.summaries"),
    ("repomap_kg.storage_canonical", "repomap_kg.storage.canonical"),
    ("repomap_kg.storage_source_readback", "repomap_kg.storage.source_readback"),
    ("repomap_kg.storage_rows", "repomap_kg.storage.rows"),
    ("repomap_kg.storage_sql", "repomap_kg.storage.sql"),
)

SUMMARY_ROW_IMPLEMENTATION_MODULES = {
    "repomap_kg.storage.summary_rows_storage",
    "repomap_kg.storage.summary_rows_languages",
    "repomap_kg.storage.summary_rows_domains",
    "repomap_kg.storage.summary_rows_manifest",
    "repomap_kg.storage.summary_rows_nix",
}


def _source_imported_modules(module: ModuleType) -> set[str]:
    assert module.__file__ is not None
    source_path = Path(module.__file__)
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in module_ast.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_pkg3_storage_submodules_import() -> None:
    import repomap_kg.storage.main as storage_main
    import repomap_kg.storage.errors as storage_errors
    import repomap_kg.storage.rows as storage_rows
    import repomap_kg.storage.canonical_readback_rows as storage_canonical_readback_rows
    import repomap_kg.storage.canonical_rows as storage_canonical_rows
    import repomap_kg.storage.jsonable_rows as storage_jsonable_rows
    import repomap_kg.storage.file_rows as storage_file_rows
    import repomap_kg.storage.row_helpers as storage_row_helpers
    import repomap_kg.storage.source_rows as storage_source_rows
    import repomap_kg.storage.summary_rows_core as storage_summary_rows_core
    import repomap_kg.storage.summary_rows_storage as storage_summary_rows_storage
    import repomap_kg.storage.summary_rows_languages as storage_summary_rows_languages
    import repomap_kg.storage.summary_rows_domains as storage_summary_rows_domains
    import repomap_kg.storage.summary_rows_manifest as storage_summary_rows_manifest
    import repomap_kg.storage.summary_rows_nix as storage_summary_rows_nix
    import repomap_kg.storage.summary_rows as storage_summary_rows
    import repomap_kg.storage.table_rows as storage_table_rows
    import repomap_kg.storage.sql_core as storage_sql_core
    import repomap_kg.storage.sql_load as storage_sql_load
    import repomap_kg.storage.sql_canonical as storage_sql_canonical
    import repomap_kg.storage.sql_sources as storage_sql_sources
    import repomap_kg.storage.sql_summaries as storage_sql_summaries
    import repomap_kg.storage.sql_summaries_nix as storage_sql_summaries_nix
    import repomap_kg.storage.sql_summaries_python as storage_sql_summaries_python
    import repomap_kg.storage.sql as storage_sql
    import repomap_kg.storage.psql as storage_psql
    import repomap_kg.storage.readback_driver as storage_readback_driver
    import repomap_kg.storage.source_readback as storage_source_readback
    import repomap_kg.storage.canonical as storage_canonical
    import repomap_kg.storage.summaries as storage_summaries
    import repomap_kg.storage.staging as storage_staging
    import repomap_kg.storage.staging_ownership as storage_staging_ownership
    import repomap_kg.storage.staging_checksums as storage_staging_checksums
    import repomap_kg.storage.staging_copy as storage_staging_copy
    import repomap_kg.storage.staging_merge as storage_staging_merge
    import repomap_kg.storage.canonical_staging_merge as storage_canonical_staging_merge
    import repomap_kg.storage.publication_fencing as storage_publication_fencing
    import repomap_kg.storage.staging_cleanup as storage_staging_cleanup

    submodules = (
        storage_main, storage_errors, storage_rows, storage_canonical_readback_rows,
        storage_canonical_rows, storage_jsonable_rows, storage_file_rows,
        storage_row_helpers, storage_source_rows, storage_summary_rows_core,
        storage_summary_rows_storage, storage_summary_rows_languages,
        storage_summary_rows_domains, storage_summary_rows_manifest,
        storage_summary_rows_nix, storage_summary_rows, storage_table_rows,
        storage_sql_core, storage_sql_load, storage_sql_canonical,
        storage_sql_sources, storage_sql_summaries, storage_sql_summaries_nix,
        storage_sql_summaries_python, storage_sql, storage_psql,
        storage_readback_driver, storage_source_readback, storage_canonical,
        storage_summaries, storage_staging, storage_staging_ownership,
        storage_staging_checksums, storage_staging_copy, storage_staging_merge,
        storage_canonical_staging_merge, storage_publication_fencing,
        storage_staging_cleanup,
    )
    expected_names = {
        "repomap_kg.storage.main", "repomap_kg.storage.errors",
        "repomap_kg.storage.rows", "repomap_kg.storage.canonical_readback_rows",
        "repomap_kg.storage.canonical_rows", "repomap_kg.storage.jsonable_rows",
        "repomap_kg.storage.file_rows", "repomap_kg.storage.row_helpers",
        "repomap_kg.storage.source_rows", "repomap_kg.storage.summary_rows_core",
        "repomap_kg.storage.summary_rows_storage", "repomap_kg.storage.summary_rows_languages",
        "repomap_kg.storage.summary_rows_domains", "repomap_kg.storage.summary_rows_manifest",
        "repomap_kg.storage.summary_rows_nix", "repomap_kg.storage.summary_rows",
        "repomap_kg.storage.table_rows", "repomap_kg.storage.sql_core",
        "repomap_kg.storage.sql_load", "repomap_kg.storage.sql_canonical",
        "repomap_kg.storage.sql_sources", "repomap_kg.storage.sql_summaries",
        "repomap_kg.storage.sql_summaries_nix", "repomap_kg.storage.sql_summaries_python",
        "repomap_kg.storage.sql", "repomap_kg.storage.psql",
        "repomap_kg.storage.readback_driver", "repomap_kg.storage.source_readback",
        "repomap_kg.storage.canonical", "repomap_kg.storage.summaries",
        "repomap_kg.storage.staging", "repomap_kg.storage.staging_ownership",
        "repomap_kg.storage.staging_checksums", "repomap_kg.storage.staging_copy",
        "repomap_kg.storage.staging_merge", "repomap_kg.storage.canonical_staging_merge",
        "repomap_kg.storage.publication_fencing", "repomap_kg.storage.staging_cleanup",
    }
    assert {module.__name__ for module in submodules} == expected_names


def test_rootalias_retired_storage_aliases_use_package_modules() -> None:
    import repomap_kg as module
    import repomap_kg.storage.errors as storage_errors
    import repomap_kg.storage.psql as storage_psql
    import repomap_kg.storage.summaries as storage_summaries
    import repomap_kg.storage.canonical as storage_canonical
    import repomap_kg.storage.source_readback as storage_source_readback
    import repomap_kg.storage.rows as storage_rows
    import repomap_kg.storage.sql as storage_sql

    package_modules = {
        "repomap_kg.storage.errors": storage_errors,
        "repomap_kg.storage.psql": storage_psql,
        "repomap_kg.storage.summaries": storage_summaries,
        "repomap_kg.storage.canonical": storage_canonical,
        "repomap_kg.storage.source_readback": storage_source_readback,
        "repomap_kg.storage.rows": storage_rows,
        "repomap_kg.storage.sql": storage_sql,
    }

    assert module.__file__ is not None
    package_root = Path(module.__file__).parent

    for alias_module, package_module in RETIRED_STORAGE_ALIAS_MODULES:
        assert package_modules[package_module].__name__ == package_module
        alias_filename = f"{alias_module.rsplit('.', 1)[-1]}.py"
        assert not (package_root / alias_filename).exists()



def test_storage_jsonable_rows_imports_summary_records_from_implementation_modules() -> None:
    import repomap_kg.storage.jsonable_rows as jsonable_rows
    imported_modules = _source_imported_modules(jsonable_rows)

    assert "repomap_kg.storage.summary_rows" not in imported_modules
    assert SUMMARY_ROW_IMPLEMENTATION_MODULES <= imported_modules


def test_storage_table_rows_imports_summary_records_from_implementation_modules() -> None:
    import repomap_kg.storage.table_rows as table_rows
    imported_modules = _source_imported_modules(table_rows)

    assert "repomap_kg.storage.summary_rows" not in imported_modules
    assert SUMMARY_ROW_IMPLEMENTATION_MODULES <= imported_modules


def test_storage_sql_core_helpers_remain_available_through_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql_core as sql_core
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.sql as storage_sql

    helper_names = (
        "positive_limit",
        "require_supported_graph_key_version",
        "canonical_file_path_prefix",
        "sql_like_prefix_literal",
        "sql_literal",
        "sql_bool",
        "sql_int_or_null",
    )

    assert sql_core.__all__ == helper_names
    for helper_name in helper_names:
        helper = getattr(sql_core, helper_name)
        assert getattr(sql_module, helper_name) is helper
        assert getattr(storage_sql, helper_name) is helper
        assert getattr(storage, helper_name) is helper


def test_storage_active_sql_load_builders_remain_available_through_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql_load as sql_load
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.sql as storage_sql

    load_names = (
        "build_canonical_ingest_sql",
        "repository_run_prefix_sql",
        "run_completion_statements",
        "canonical_ingest_statements",
        "file_load_summary_select_sql",
        "canonical_load_summary_select_sql",
        "file_upsert_sql",
        "raw_observation_upsert_sql",
        "canonical_node_upsert_sql",
        "canonical_edge_upsert_sql",
        "canonical_evidence_upsert_sql",
        "canonical_node_evidence_upsert_sql",
        "canonical_edge_evidence_upsert_sql",
    )

    assert sql_load.__all__ == load_names
    for load_name in load_names:
        builder = getattr(sql_load, load_name)
        assert getattr(sql_module, load_name) is builder
        assert getattr(storage_sql, load_name) is builder
        if load_name in sql_module.__all__:
            assert getattr(storage, load_name) is builder
        else:
            assert not hasattr(storage, load_name)


def test_storage_legacy_write_sql_is_absent_from_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql as storage_sql
    import repomap_kg.storage.sql_load as storage_sql_load

    modules = (storage, storage_sql, storage_sql_load)
    retired = (
        "build_file_ingest_sql",
        "build_file_canonical_ingest_sql",
        "legacy_file_ingest_statements",
        "file_node_upsert_sql",
        "file_evidence_upsert_sql",
        "relationship_source_node_upsert_sql",
        "relationship_target_node_upsert_sql",
        "relationship_evidence_upsert_sql",
        "relationship_edge_upsert_sql",
    )

    for module in modules:
        assert not set(retired) & set(module.__dict__)


def test_local38_file_node_compatibility_names_are_removed() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.main as storage_main

    removed_names = (
        "FileNodeRecord",
        "file_node_record_from_storage_payload",
        "file_node_records_to_jsonable",
        "format_file_node_table",
        "query_file_node_records",
        "build_file_node_query_sql",
    )

    for module in (storage, storage_main):
        for removed_name in removed_names:
            assert not hasattr(module, removed_name)


def test_storage_sql_canonical_builders_remain_available_through_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql_canonical as sql_canonical
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.sql as storage_sql

    canonical_names = (
        "build_canonical_node_query_sql",
        "build_canonical_edge_query_sql",
        "build_canonical_neighborhood_query_sql",
        "build_explain_canonical_edge_query_sql",
        "build_canonical_storage_summary_query_sql",
    )

    assert sql_canonical.__all__ == canonical_names
    for canonical_name in canonical_names:
        builder = getattr(sql_canonical, canonical_name)
        assert getattr(sql_module, canonical_name) is builder
        assert getattr(storage_sql, canonical_name) is builder
        assert getattr(storage, canonical_name) is builder


def test_storage_sql_sources_builders_remain_available_through_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql_sources as sql_sources
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.sql as storage_sql

    source_names = (
        "build_ingested_source_query_sql",
        "build_source_summary_query_sql",
        "build_source_run_query_sql",
        "build_source_feed_item_query_sql",
        "build_source_reference_query_sql",
        "build_source_feed_item_explanation_query_sql",
        "source_observations_cte",
    )

    assert sql_sources.__all__ == source_names
    for source_name in source_names:
        builder = getattr(sql_sources, source_name)
        assert getattr(sql_module, source_name) is builder
        assert getattr(storage_sql, source_name) is builder
        assert getattr(storage, source_name) is builder


def test_storage_sql_summaries_builders_remain_available_through_facades() -> None:
    import repomap_kg.storage as storage
    import repomap_kg.storage.sql_summaries as sql_summaries
    import repomap_kg.storage.sql as sql_module
    import repomap_kg.storage.sql as storage_sql

    summary_names = (
        "build_ruby_summary_query_sql",
        "build_js_summary_query_sql",
        "build_js_framework_summary_query_sql",
        "build_python_summary_query_sql",
        "build_openapi_summary_query_sql",
        "build_terraform_summary_query_sql",
        "build_email_summary_query_sql",
        "build_bulk_summary_query_sql",
        "build_api_summary_query_sql",
        "build_nix_summary_query_sql",
    )

    assert sql_summaries.__all__ == summary_names
    for summary_name in summary_names:
        builder = getattr(sql_summaries, summary_name)
        assert getattr(sql_module, summary_name) is builder
        assert getattr(storage_sql, summary_name) is builder
        assert getattr(storage, summary_name) is builder


def test_pkg3_storage_migration_discovery_keeps_resource_root() -> None:
    import repomap_kg.storage as storage

    migrations = storage.discover_migrations()

    assert migrations
    assert "/src/main/resources/rdbms/" in migrations[0].path.as_posix()


def test_pkg3_storage_root_subprocess_patch_target_still_drives_run_psql() -> None:
    import repomap_kg.storage as storage

    with patch("repomap_kg.storage.subprocess.run") as run:
        storage.run_psql(["psql", "-c", "select 1"])

    run.assert_called_once()


def test_pyproject_toml_registers_all_resource_sql_directories() -> None:
    import tomllib

    repo_root = Path(__file__).resolve().parents[6]
    pyproject_path = repo_root / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml must exist at repo root"

    with pyproject_path.open("rb") as stream:
        pyproject = tomllib.load(stream)

    data_files = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("data-files", {})
    )
    registered_patterns = set()
    for patterns in data_files.values():
        registered_patterns.update(patterns)

    resources_root = repo_root / "src" / "main" / "resources"
    sql_files = list(resources_root.rglob("*.sql"))
    assert len(sql_files) > 0, "expected at least one SQL resource file"

    sql_directories = {file.parent for file in sql_files}
    for sql_dir in sql_directories:
        relative_dir = sql_dir.relative_to(repo_root)
        glob_pattern = f"{relative_dir}/*.sql"
        assert glob_pattern in registered_patterns, (
            f"Resource SQL directory {relative_dir} has no matching glob "
            f"{glob_pattern!r} registered in pyproject.toml [tool.setuptools.data-files]"
        )
