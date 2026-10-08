"""SQL builders for RepoMap storage summary readback."""

from __future__ import annotations

from repomap_kg.storage._sql_summaries_domains import (
    build_api_summary_query_sql,
    build_bulk_summary_query_sql,
    build_openapi_summary_query_sql,
    build_terraform_summary_query_sql,
)
from repomap_kg.storage._sql_summaries_email import build_email_summary_query_sql
from repomap_kg.storage.graph_readback_sql import build_repository_filter_sql
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.sql_summaries_nix import build_nix_summary_query_sql
from repomap_kg.storage.sql_summaries_python import build_python_summary_query_sql

__all__ = (
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


def build_ruby_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "ruby_nodes AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind LIKE 'ruby.%'"
        "), "
        "ruby_raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.kind LIKE 'ruby.%'"
        "), "
        "ruby_references AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "WHERE canonical_edges.graph_key_version = 1 "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.source_canonical_key LIKE 'ruby.%'"
        "), "
        "profile_rows AS ("
        "SELECT COALESCE(metadata_json->>'profile', 'unknown') AS profile, "
        "COUNT(*) AS profile_count "
        "FROM ruby_nodes "
        "WHERE kind = 'ruby.file' "
        "GROUP BY COALESCE(metadata_json->>'profile', 'unknown')"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'ruby_files', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.file') "
        "FROM ruby_nodes), "
        "'modules', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.module') "
        "FROM ruby_nodes), "
        "'classes', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.class') "
        "FROM ruby_nodes), "
        "'methods', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.method') "
        "FROM ruby_nodes), "
        "'singleton_methods', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'ruby.singleton_method') FROM ruby_nodes), "
        "'constants', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.constant') "
        "FROM ruby_nodes), "
        "'routes', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.route') "
        "FROM ruby_nodes), "
        "'test_cases', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.test_case') "
        "FROM ruby_nodes), "
        "'test_methods', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'ruby.test_method') FROM ruby_nodes), "
        "'references', (SELECT COUNT(*) FROM ruby_references), "
        "'gem_dependencies', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.gem_dependency'), "
        "'vagrant_configs', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.vagrant_config'), "
        "'rake_tasks', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.dsl' "
        "AND raw_observations.payload_json->'metadata'->>'profile' = 'rake' "
        "AND raw_observations.payload_json->'metadata'->>'dsl_name' = 'task'), "
        "'rake_namespaces', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.dsl' "
        "AND raw_observations.payload_json->'metadata'->>'profile' = 'rake' "
        "AND raw_observations.payload_json->'metadata'->>'dsl_name' = 'namespace'), "
        "'dynamic_diagnostics', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.parse_error' "
        "AND COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'parse_errors', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.parse_error' "
        "AND NOT COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'profile_counts', COALESCE(("
        "SELECT json_object_agg(profile, profile_count ORDER BY profile) "
        "FROM profile_rows"
        "), '{}'::json), "
        "'no_execution', true"
        ")::text;"
    )


def build_js_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "js_nodes AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind LIKE 'js.%'"
        "), "
        "js_raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.kind LIKE 'js.%'"
        "), "
        "js_references AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "WHERE canonical_edges.graph_key_version = 1 "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.source_canonical_key LIKE 'js.%'"
        "), "
        "profile_rows AS ("
        "SELECT COALESCE(metadata_json->>'profile', 'unknown') AS profile, "
        "COUNT(*) AS profile_count "
        "FROM js_nodes "
        "WHERE kind = 'js.file' "
        "GROUP BY COALESCE(metadata_json->>'profile', 'unknown')"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'js_files', (SELECT COUNT(*) FILTER (WHERE kind = 'js.file') "
        "FROM js_nodes), "
        "'modules', (SELECT COUNT(*) FILTER (WHERE kind = 'js.module') "
        "FROM js_nodes), "
        "'functions', (SELECT COUNT(*) FILTER (WHERE kind = 'js.function') "
        "FROM js_nodes), "
        "'classes', (SELECT COUNT(*) FILTER (WHERE kind = 'js.class') "
        "FROM js_nodes), "
        "'methods', (SELECT COUNT(*) FILTER (WHERE kind = 'js.method') "
        "FROM js_nodes), "
        "'variables', (SELECT COUNT(*) FILTER (WHERE kind = 'js.variable') "
        "FROM js_nodes), "
        "'components', (SELECT COUNT(*) FILTER (WHERE kind = 'js.component') "
        "FROM js_nodes), "
        "'routes', (SELECT COUNT(*) FILTER (WHERE kind = 'js.route') "
        "FROM js_nodes), "
        "'test_suites', (SELECT COUNT(*) FILTER (WHERE kind = 'js.test_suite') "
        "FROM js_nodes), "
        "'test_cases', (SELECT COUNT(*) FILTER (WHERE kind = 'js.test_case') "
        "FROM js_nodes), "
        "'references', (SELECT COUNT(*) FROM js_references), "
        "'imports', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.import'), "
        "'exports', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.export'), "
        "'hooks', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.hook'), "
        "'test_expectations', COALESCE(("
        "SELECT SUM(COALESCE(("
        "raw_observations.payload_json->'metadata'->>'expectation_count'"
        ")::int, 1)) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.test_expectation'"
        "), 0), "
        "'source_map_references', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.reference' "
        "AND raw_observations.payload_json->'metadata'->>'reference_kind' = "
        "'source_map'), "
        "'frontend_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'frontend_asset'), "
        "'saved_page_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'saved_page_asset'), "
        "'test_report_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'test_report_asset'), "
        "'dynamic_diagnostics', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.parse_error' "
        "AND COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'parse_errors', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.parse_error' "
        "AND NOT COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'profile_counts', COALESCE(("
        "SELECT json_object_agg(profile, profile_count ORDER BY profile) "
        "FROM profile_rows"
        "), '{}'::json), "
        "'no_execution', true"
        ")::text;"
    )


def build_js_framework_summary_query_sql(
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    quoted_root = sql_literal(root_path)
    framework_kinds = (
        "node.entrypoint",
        "node.export",
        "node.require",
        "express.app",
        "express.router",
        "express.route",
        "express.middleware",
        "express.error_handler",
        "nest.module",
        "nest.controller",
        "nest.provider",
        "nest.route",
        "nest.decorator",
        "next.route",
        "next.page",
        "next.api_route",
        "next.app_route",
        "next.component",
        "jest.suite",
        "jest.test",
        "jest.expectation",
        "jest.mock",
        "jquery.selector",
        "jquery.event",
        "jquery.ajax",
        "jquery.plugin_reference",
        "js.dom_selector",
        "js.dom_event",
        "js.ajax_reference",
        "js.framework_reference",
        "js.framework_profile",
        "js.runtime_profile",
        "js.package_context",
        "js.route_handler",
        "js.middleware",
        "js.controller",
        "js.provider",
        "js.module_binding",
        "js.test_config",
        "js.server_entrypoint",
        "js.client_entrypoint",
    )
    framework_kind_sql = ", ".join(sql_literal(kind) for kind in framework_kinds)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE {repo_filter}"
        "), "
        "raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id"
        "), "
        "framework_raw AS ("
        "SELECT * FROM raw WHERE kind IN ("
        f"{framework_kind_sql}"
        ")"
        "), "
        "canonical_js AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind IN ("
        "'js.route', 'js.test_suite', 'js.test_case', 'js.component'"
        ")"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'framework_observations', (SELECT COUNT(*) FROM framework_raw), "
        "'framework_profiles', json_build_object("
        "'node', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'node.%'), "
        "'express', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'express.%'), "
        "'nest', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'nest.%'), "
        "'next', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'next.%'), "
        "'jest', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'jest.%'), "
        "'jquery', (SELECT COUNT(*) FROM framework_raw WHERE kind LIKE 'jquery.%'), "
        "'generic_js', (SELECT COUNT(*) FROM framework_raw "
        "WHERE kind IN ("
        "'js.dom_selector', 'js.dom_event', 'js.ajax_reference', "
        "'js.framework_reference', 'js.framework_profile', 'js.runtime_profile', "
        "'js.package_context', 'js.route_handler', 'js.middleware', "
        "'js.controller', 'js.provider', 'js.module_binding', 'js.test_config', "
        "'js.server_entrypoint', 'js.client_entrypoint'"
        "))), "
        "'node', json_build_object("
        "'entrypoints', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'node.entrypoint'), "
        "'requires', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'node.require'), "
        "'exports', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'node.export'), "
        "'env_references', (SELECT COUNT(*) FROM framework_raw "
        "WHERE kind = 'js.framework_reference' "
        "AND payload_json->'metadata'->>'reference_kind' = 'environment')), "
        "'express', json_build_object("
        "'apps', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'express.app'), "
        "'routers', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'express.router'), "
        "'routes', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'express.route'), "
        "'middleware', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'express.middleware'), "
        "'error_handlers', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'express.error_handler'), "
        "'dynamic_routes', (SELECT COUNT(*) FROM framework_raw "
        "WHERE kind = 'express.route' "
        "AND COALESCE((payload_json->'metadata'->>'dynamic')::boolean, false))), "
        "'nest', json_build_object("
        "'modules', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'nest.module'), "
        "'controllers', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'nest.controller'), "
        "'providers', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'nest.provider'), "
        "'routes', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'nest.route'), "
        "'decorators', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'nest.decorator')), "
        "'next', json_build_object("
        "'pages', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'next.page'), "
        "'api_routes', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'next.api_route'), "
        "'app_routes', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'next.app_route'), "
        "'components', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'next.component'), "
        "'route_handlers', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'next.route')), "
        "'jest', json_build_object("
        "'suites', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jest.suite'), "
        "'tests', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jest.test'), "
        "'expectations', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jest.expectation'), "
        "'mocks', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jest.mock')), "
        "'jquery', json_build_object("
        "'selectors', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jquery.selector'), "
        "'events', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jquery.event'), "
        "'ajax_references', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jquery.ajax'), "
        "'plugin_references', (SELECT COUNT(*) FROM framework_raw WHERE kind = 'jquery.plugin_reference')), "
        "'generic_js', json_build_object("
        "'canonical_routes', (SELECT COUNT(*) FROM canonical_js WHERE kind = 'js.route'), "
        "'canonical_test_suites', (SELECT COUNT(*) FROM canonical_js WHERE kind = 'js.test_suite'), "
        "'canonical_test_cases', (SELECT COUNT(*) FROM canonical_js WHERE kind = 'js.test_case'), "
        "'canonical_components', (SELECT COUNT(*) FROM canonical_js WHERE kind = 'js.component')), "
        "'diagnostics', json_build_object("
        "'framework_observation_limit', (SELECT COUNT(*) FROM raw "
        "WHERE kind = 'js.parse_error' "
        "AND payload_json->'metadata'->>'error_kind' = 'framework-observation-limit'), "
        "'framework_selector_limit', (SELECT COUNT(*) FROM raw "
        "WHERE kind = 'js.parse_error' "
        "AND payload_json->'metadata'->>'error_kind' = 'framework-selector-limit')), "
        "'safety', json_build_object("
        "'no_execution', true, "
        "'no_fetch', true, "
        "'raw_profile_only', true, "
        "'no_new_canonical_namespaces', true)"
        ")::text;"
    )
