"""OpenAPI and JS-framework summaries over one SQLite Local graph.

The named SQLite counterparts of ``_sql_summaries_domains``'s OpenAPI builder
and ``sql_summaries.build_js_framework_summary_query_sql``, under the same row
selection and JSONB-semantics rules as ``storage.sqlite_local.summary_queries``.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from repomap_kg.storage.sqlite_local.queries import require_accepted_publication
from repomap_kg.storage.sqlite_local.raw_payload import ascii_upper, flag, is_in, meta
from repomap_kg.storage.sqlite_local.summary_queries import (
    CONFIG_KINDS,
    canonical_counts,
    config_counts,
    raw_count,
    raw_rows,
    repository_name,
)
from repomap_kg.storage.summary_rows import (
    JSFrameworkSummaryRecord,
    OpenAPISummaryRecord,
    js_framework_summary_from_storage_payload,
    openapi_summary_from_storage_payload,
)

_OPENAPI_KINDS = {
    "info": "info", "servers": "server", "paths": "path", "operations": "operation",
    "parameters": "parameter", "request_bodies": "request_body", "responses": "response",
    "schemas": "schema", "components": "component", "security_schemes": "security_scheme",
    "tags": "tag", "examples": "example",
}
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE")
_OPENAPI_REDACTIONS = {
    "openapi_ref_summaries": "openapi-ref-summary-only",
    "text_summaries": "openapi-text-summary-only",
    "example_summaries": "openapi-example-summary-only",
    "secret_prone_fields": "secret-prone-openapi-field",
}
_OPENAPI_LIMITS = ("openapi-path-limit", "openapi-operation-limit", "openapi-schema-limit",
                   "openapi-parameter-limit", "openapi-response-limit", "openapi-reference-limit")
_MALFORMED = ("malformed-openapi-json", "malformed-openapi-yaml")


def openapi_summary(connection: sqlite3.Connection, *, root_path: str) -> OpenAPISummaryRecord:
    require_accepted_publication(connection)
    kinds: Counter[str] = Counter()
    c: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    for kind, _path, p in raw_rows(connection, prefix="openapi.", kinds=("config.parse_error",)):
        error_kind = meta(p, "error_kind")
        if kind in ("config.parse_error", "openapi.parse_error"):
            c["malformed_specs"] += is_in(error_kind, _MALFORMED)
        if kind == "config.parse_error":
            continue
        kinds[kind] += 1
        reason = meta(p, "redaction_reason")
        c["credentialed_urls"] += reason == "credentialed-url"
        if kind == "openapi.document":
            family = meta(p, "spec_family")
            c["openapi3"] += family == "openapi3"
            c["swagger2"] += family == "swagger2"
        elif kind == "openapi.operation":
            methods[ascii_upper(meta(p, "method") or "")] += 1
        elif kind == "openapi.reference":
            scope = meta(p, "reference_scope")
            c["internal_refs"] += scope == "internal"
            c["local_file_refs"] += scope == "local_file"
            if scope == "remote" and flag(meta(p, "not_fetched")):
                c["remote_refs_not_fetched"] += 1
            if scope == "external_docs" and flag(meta(p, "not_fetched")):
                c["external_docs_not_fetched"] += 1
            c["refs_not_fetched"] += flag(meta(p, "not_fetched"))
        elif kind == "openapi.redaction":
            for key, value in _OPENAPI_REDACTIONS.items():
                c[key] += reason == value
        elif kind == "openapi.parse_error":
            c["unsupported_specs"] += is_in(
                error_kind, ("unsupported-openapi-document", "unsupported-openapi-version"))
            c["limit_overflows"] += is_in(error_kind, _OPENAPI_LIMITS)
            c["local_ref_errors"] += error_kind == "openapi-local-ref-outside-root"
    canonical = canonical_counts(connection, CONFIG_KINDS)
    k = kinds
    return openapi_summary_from_storage_payload({
        "root_path": root_path,
        "repository_name": repository_name(connection),
        "openapi_observations": sum(kinds.values()),
        "openapi_documents": k["openapi.document"],
        "spec_families": {"openapi3": c["openapi3"], "swagger2": c["swagger2"]},
        "openapi": {key: k[f"openapi.{kind}"] for key, kind in _OPENAPI_KINDS.items()},
        "methods": {method: methods[method] for method in _METHODS},
        "references": {key: c[key] for key in (
            "internal_refs", "local_file_refs", "remote_refs_not_fetched",
            "external_docs_not_fetched", "refs_not_fetched")},
        "redactions": {"credentialed_urls": c["credentialed_urls"],
                       **{key: c[key] for key in _OPENAPI_REDACTIONS}},
        "diagnostics": {
            "parse_errors": k["openapi.parse_error"],
            **{key: c[key] for key in (
                "unsupported_specs", "limit_overflows", "local_ref_errors", "malformed_specs")},
        },
        "generic_config": {**config_counts(canonical, connection),
                           "config_parse_errors": raw_count(connection, "config.parse_error")},
        "safety": dict.fromkeys((
            "no_fetch", "no_api_calls", "no_tool_execution", "raw_profile_only",
            "no_new_canonical_namespaces"), True),
    })


_GENERIC_JS = (
    "js.dom_selector", "js.dom_event", "js.ajax_reference", "js.framework_reference",
    "js.framework_profile", "js.runtime_profile", "js.package_context", "js.route_handler",
    "js.middleware", "js.controller", "js.provider", "js.module_binding", "js.test_config",
    "js.server_entrypoint", "js.client_entrypoint",
)
_FRAMEWORK_SECTIONS: dict[str, dict[str, str]] = {
    "node": {"entrypoints": "entrypoint", "requires": "require", "exports": "export"},
    "express": {"apps": "app", "routers": "router", "routes": "route",
                "middleware": "middleware", "error_handlers": "error_handler"},
    "nest": {"modules": "module", "controllers": "controller", "providers": "provider",
             "routes": "route", "decorators": "decorator"},
    "next": {"pages": "page", "api_routes": "api_route", "app_routes": "app_route",
             "components": "component", "route_handlers": "route"},
    "jest": {"suites": "suite", "tests": "test", "expectations": "expectation", "mocks": "mock"},
    "jquery": {"selectors": "selector", "events": "event", "ajax_references": "ajax",
               "plugin_references": "plugin_reference"},
}
FRAMEWORK_KINDS = frozenset(
    {f"{family}.{kind}" for family, section in _FRAMEWORK_SECTIONS.items() for kind in section.values()}
    | set(_GENERIC_JS)
)
_JS_LIMITS = ("framework-observation-limit", "framework-selector-limit")


def js_framework_summary(
    connection: sqlite3.Connection, *, root_path: str
) -> JSFrameworkSummaryRecord:
    require_accepted_publication(connection)
    kinds: Counter[str] = Counter()
    c: Counter[str] = Counter()
    for kind, _path, p in raw_rows(connection, kinds=FRAMEWORK_KINDS | {"js.parse_error"}):
        if kind == "js.parse_error":
            error_kind = meta(p, "error_kind")
            for value in _JS_LIMITS:
                c[value] += error_kind == value
            continue
        kinds[kind] += 1
        if kind == "js.framework_reference":
            c["env_references"] += meta(p, "reference_kind") == "environment"
        elif kind == "express.route":
            c["dynamic_routes"] += flag(meta(p, "dynamic"))
    canonical = canonical_counts(
        connection, ("js.route", "js.test_suite", "js.test_case", "js.component"))
    sections: dict[str, Any] = {
        family: {key: kinds[f"{family}.{kind}"] for key, kind in section.items()}
        for family, section in _FRAMEWORK_SECTIONS.items()
    }
    sections["node"]["env_references"] = c["env_references"]
    sections["express"]["dynamic_routes"] = c["dynamic_routes"]
    profiles = {
        family: sum(count for kind, count in kinds.items() if kind.startswith(f"{family}."))
        for family in _FRAMEWORK_SECTIONS
    }
    return js_framework_summary_from_storage_payload({
        "root_path": root_path,
        "repository_name": repository_name(connection),
        "framework_observations": sum(kinds.values()),
        "framework_profiles": {**profiles, "generic_js": sum(kinds[kind] for kind in _GENERIC_JS)},
        **sections,
        "generic_js": {
            "canonical_routes": canonical["js.route"],
            "canonical_test_suites": canonical["js.test_suite"],
            "canonical_test_cases": canonical["js.test_case"],
            "canonical_components": canonical["js.component"],
        },
        "diagnostics": {
            "framework_observation_limit": c["framework-observation-limit"],
            "framework_selector_limit": c["framework-selector-limit"],
        },
        "safety": dict.fromkeys(
            ("no_execution", "no_fetch", "raw_profile_only", "no_new_canonical_namespaces"), True),
    })


__all__ = ("FRAMEWORK_KINDS", "js_framework_summary", "openapi_summary")
