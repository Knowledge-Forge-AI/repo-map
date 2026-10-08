"""Python and Terraform summaries, and shared row helpers, over one SQLite Local graph.

Each operation is the named SQLite counterpart of one maintained PostgreSQL
summary builder (``sql_summaries_python`` and ``_sql_summaries_domains``'s
Terraform builder): the same counters over
every retained run's raw observations and the current canonical nodes, decoded
through the same ``*_summary_from_storage_payload`` owner. Row selection is
case-sensitive SQL (``substr``/``IN``, never SQLite's ASCII-folding ``LIKE``);
JSON predicates use the PostgreSQL JSONB semantics in
``storage.sqlite_local.raw_payload``. No PostgreSQL SQL is reused or translated.
OpenAPI and JS-framework live in ``storage.sqlite_local.api_summary_queries``
and Nix in ``storage.sqlite_local.nix_summary_queries``.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Collection, Iterator
from typing import Any

from repomap_kg.storage.sqlite_local.queries import require_accepted_publication
from repomap_kg.storage.sqlite_local.raw_payload import (
    flag,
    is_in,
    like,
    load,
    meta,
    ne,
    not_like,
    text_at,
)
from repomap_kg.storage.summary_rows import (
    PythonSummaryRecord,
    TerraformSummaryRecord,
    python_summary_from_storage_payload,
    terraform_summary_from_storage_payload,
)

RawRow = tuple[str, str, Any]
_FRAMEWORKS = frozenset({"flask", "fastapi", "django"})
CONFIG_KINDS = ("config.document", "config.path")
_PY_FRAMEWORKS = {
    "flask_apps": "flask_app", "flask_blueprints": "flask_blueprint",
    "flask_routes": "flask_route", "fastapi_apps": "fastapi_app",
    "fastapi_routers": "fastapi_router", "fastapi_routes": "fastapi_route",
    "fastapi_dependencies": "fastapi_dependency", "django_projects": "django_project",
    "django_apps": "django_app", "django_urlpatterns": "django_urlpattern",
    "django_views": "django_view", "django_models": "django_model",
    "django_setting_references": "django_setting_reference",
}


def raw_rows(
    connection: sqlite3.Connection, *, prefix: str | None = None, kinds: Collection[str] = ()
) -> Iterator[RawRow]:
    """``(kind, path, decoded payload)`` for a case-sensitive kind prefix and/or kind set."""
    clauses: list[str] = []
    params: list[object] = []
    if prefix is not None:
        clauses.append("substr(kind, 1, ?) = ?")
        params += [len(prefix), prefix]
    if kinds:
        clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})")
        params += sorted(kinds)
    cursor = connection.execute(
        f"SELECT kind, path, payload_json FROM raw_observations WHERE {' OR '.join(clauses)}", params
    )
    try:
        for kind, path, text in cursor:
            yield kind, path, load(text)
    finally:
        cursor.close()


def raw_count(connection: sqlite3.Connection, *kinds: str) -> int:
    marks = ", ".join("?" for _ in kinds)
    return int(connection.execute(
        f"SELECT count(*) FROM raw_observations WHERE kind IN ({marks})", kinds
    ).fetchone()[0])


def canonical_counts(connection: sqlite3.Connection, kinds: Collection[str]) -> Counter[str]:
    marks = ", ".join("?" for _ in kinds)
    return Counter({
        str(kind): int(count)
        for kind, count in connection.execute(
            "SELECT kind, count(*) FROM canonical_nodes WHERE graph_key_version = 1 "
            f"AND kind IN ({marks}) GROUP BY kind",
            tuple(kinds),
        )
    })


def repository_name(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT repository_name FROM graph_binding").fetchone()
    return None if row is None else row[0]


def config_counts(canonical: Counter[str], connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "config_documents": canonical["config.document"],
        "config_paths": canonical["config.path"],
        "config_references": raw_count(connection, "config.reference"),
    }


def python_summary(connection: sqlite3.Connection, *, root_path: str) -> PythonSummaryRecord:
    require_accepted_publication(connection)
    kinds: Counter[str] = Counter()
    c: Counter[str] = Counter()
    dogfooding = False
    for kind, _path, p in raw_rows(connection, prefix="python."):
        kinds[kind] += 1
        if kind == "python.package_file" and (
            like(meta(p, "file_family"), "requirements%")
            or meta(p, "source_format") == "python-requirements"
        ):
            c["requirements"] += 1
        if kind == "python.reference":
            reference_kind = meta(p, "reference_kind")
            if is_in(meta(p, "source_format"), ("python-requirements", "pyproject.toml")) or is_in(
                reference_kind,
                ("include_file", "constraint_file", "direct_url", "vcs_url", "editable_local_path",
                 "local_path", "index_url", "extra_index_url", "find_links"),
            ):
                c["package_refs"] += 1
            if like(text_at(p, "target"), "file:%") or meta(p, "resolution") == "local":
                c["local_file_refs"] += 1
            if flag(meta(p, "not_fetched")) and (
                is_in(reference_kind, ("direct_url", "vcs_url", "dependency_url"))
                or flag(meta(p, "direct_url"))
            ):
                c["direct_urls_not_fetched"] += 1
            if flag(meta(p, "not_fetched")) and is_in(
                reference_kind, ("index_url", "extra_index_url", "find_links")
            ):
                c["index_urls_not_fetched"] += 1
            if is_in(meta(p, "framework"), _FRAMEWORKS):
                c["framework_refs"] += 1
        if kind == "python.redaction":
            reason = meta(p, "redaction_reason")
            for key, pattern in (("credentialed_urls", "%credential%"),
                                 ("private_indexes", "%index%"), ("secret_like_config", "%secret%")):
                c[key] += like(reason, pattern)
            if is_in(meta(p, "framework"), _FRAMEWORKS) or any(
                like(reason, f"%{name}%") for name in ("django", "flask", "fastapi")
            ):
                c["framework_settings"] += 1
        if kind == "python.parse_error":
            c["limit_overflows"] += like(meta(p, "error_kind"), "%limit%")
            if flag(meta(p, "dynamic")) or like(meta(p, "error_kind"), "dynamic-%"):
                c["dynamic_constructs"] += 1
        if kind in ("python.pyproject", "python.package_file", "python.test_file") and (
            like(meta(p, "project_name"), "repo-map%")
            or like(text_at(p, "name"), "repo-map%")
            or like(text_at(p, "path"), "%repomap_kg%")
        ):
            dogfooding = True
    canonical = canonical_counts(connection, (
        "python.module", "python.class", "python.function", "python.method", *CONFIG_KINDS))
    k = kinds
    return python_summary_from_storage_payload({
        "root_path": root_path,
        "repository_name": repository_name(connection),
        "python_observations": sum(kinds.values()),
        "package_files": {"requirements": c["requirements"], "pyproject": k["python.pyproject"]},
        "packaging": {
            "requirements": k["python.requirement"],
            "dependency_groups": k["python.dependency_group"],
            "build_systems": k["python.build_system"],
            "entry_points": k["python.entry_point"],
            "tool_configs": k["python.tool_config"],
        },
        "tests": {
            "test_files": k["python.test_file"],
            "unittest_cases": k["python.unittest_case"],
            "pytest_tests": k["python.pytest_test"],
            "test_functions": k["python.test_function"],
            "test_methods": k["python.test_method"],
            "fixtures": k["python.test_fixture"] + k["python.pytest_fixture"],
            "parametrize": k["python.test_parametrize"],
            "assertions": k["python.test_assertion"],
        },
        "frameworks": {key: k[f"python.{kind}"] for key, kind in _PY_FRAMEWORKS.items()},
        "references": {
            "total": k["python.reference"],
            **{key: c[key] for key in ("package_refs", "local_file_refs", "direct_urls_not_fetched",
                                       "index_urls_not_fetched", "framework_refs")},
        },
        "redactions": {key: c[key] for key in (
            "credentialed_urls", "private_indexes", "secret_like_config", "framework_settings")},
        "diagnostics": {
            "parse_errors": k["python.parse_error"],
            "limit_overflows": c["limit_overflows"],
            "dynamic_constructs": c["dynamic_constructs"],
        },
        "generic_python": {
            "modules": canonical["python.module"],
            "classes": canonical["python.class"],
            "functions": canonical["python.function"],
            "methods": canonical["python.method"],
            "imports": k["python.import"],
        },
        "generic_config": config_counts(canonical, connection),
        "dogfooding": {
            "repo_map_profile_observed": dogfooding,
            "bounded": True,
            "generated_report_committed": False,
        },
        "safety": dict.fromkeys((
            "no_execution", "no_imports", "no_test_execution", "no_framework_startup", "no_fetch",
            "no_package_install", "no_openapi_fetch", "raw_profile_only",
            "no_new_canonical_namespaces"), True),
    })


_TF_KINDS = {
    "blocks": "block", "providers": "provider", "required_providers": "required_provider",
    "required_versions": "required_version", "backends": "backend", "resources": "resource",
    "data_sources": "data_source", "modules": "module", "variables": "variable",
    "outputs": "output", "locals": "local", "moved": "moved", "imports": "import",
    "checks": "check", "removed": "removed",
}


def terraform_summary(connection: sqlite3.Connection, *, root_path: str) -> TerraformSummaryRecord:
    require_accepted_publication(connection)
    kinds: Counter[str] = Counter()
    c: Counter[str] = Counter()
    for kind, _path, p in raw_rows(connection, prefix="terraform."):
        kinds[kind] += 1
        if kind == "terraform.file":
            family, path = meta(p, "file_family"), text_at(p, "path")
            c["tf"] += family == "tf"
            c["tfvars_files"] += family == "tfvars"
            if (family == "tfvars" and not_like(path, "%/terraform.tfvars")
                    and ne(path, "terraform.tfvars") and not_like(path, "%.auto.tfvars")):
                c["tfvars"] += 1
            c["terraform.tfvars"] += path == "terraform.tfvars" or like(path, "%/terraform.tfvars")
            c["auto.tfvars"] += like(path, "%.auto.tfvars")
        elif kind == "terraform.reference":
            reference_kind = meta(p, "reference_kind")
            for key, value in (("provider_sources", "provider_source"),
                               ("version_constraints", "required_version"),
                               ("local_module_refs", "module_source_local"),
                               ("depends_on", "depends_on"), ("provider_aliases", "provider_alias")):
                c[key] += reference_kind == value
            c["module_sources"] += is_in(reference_kind, ("module_source", "module_source_local"))
            if flag(meta(p, "not_fetched")) and ne(reference_kind, "module_source_local"):
                c["remote_refs_not_fetched"] += 1
        elif kind == "terraform.required_provider":
            c["version_constraints"] += meta(p, "version_constraint") is not None
        elif kind == "terraform.parse_error":
            error_kind = meta(p, "error_kind")
            c["repo_escape_diagnostics"] += is_in(
                error_kind, ("terraform-local-path-outside-root", "terraform-repo-escape"))
            c["limit_overflows"] += like(error_kind, "%limit%")
            c["malformed_hcl"] += not_like(error_kind, "%limit%")
        elif kind == "terraform.variable":
            c["tfvars_variables"] += meta(p, "profile") == "terraform_tfvars"
        elif kind == "terraform.redaction":
            reason = meta(p, "redaction_reason")
            c["tfvars_values"] += reason == "tfvars-sensitive-by-default"
            c["secret_like_fields"] += is_in(reason, (
                "secret-prone-terraform-attribute", "secret-prone-terraform-local", "secret-prone-key"))
            c["credentialed_urls"] += is_in(reason, (
                "credentialed-terraform-url", "credentialed-terraform-module-source"))
            c["import_ids"] += reason == "terraform-import-id-sensitive-by-default"
            if reason == "secret-prone-terraform-attribute" and is_in(
                meta(p, "field_name"), ("access_key", "secret_key", "token", "password")
            ):
                c["backend_values"] += 1
    file_nodes = sum(
        meta(p, "language") == "terraform" for _kind, _path, p in raw_rows(connection, kinds=("file",))
    )
    canonical = canonical_counts(connection, CONFIG_KINDS)
    k = kinds
    return terraform_summary_from_storage_payload({
        "root_path": root_path,
        "repository_name": repository_name(connection),
        "terraform_observations": sum(kinds.values()),
        "terraform_files": k["terraform.file"],
        "file_families": {key: c[key] for key in ("tf", "tfvars", "terraform.tfvars", "auto.tfvars")},
        "terraform": {key: k[f"terraform.{kind}"] for key, kind in _TF_KINDS.items()},
        "references": {
            "total": k["terraform.reference"],
            **{key: c[key] for key in (
                "provider_sources", "version_constraints", "module_sources", "local_module_refs",
                "remote_refs_not_fetched", "depends_on", "provider_aliases",
                "repo_escape_diagnostics")},
        },
        "tfvars": {
            "files": c["tfvars_files"],
            "variables": c["tfvars_variables"],
            "literal_values_exposed": False,
        },
        "redactions": {key: c[key] for key in (
            "tfvars_values", "secret_like_fields", "credentialed_urls", "import_ids",
            "backend_values")},
        "diagnostics": {
            "parse_errors": k["terraform.parse_error"],
            "limit_overflows": c["limit_overflows"],
            "malformed_hcl": c["malformed_hcl"],
        },
        "generic_config": {**config_counts(canonical, connection), "file_nodes": file_nodes},
        "safety": dict.fromkeys((
            "no_execution", "no_fetch", "no_terraform_cli", "no_provider_download",
            "no_module_download", "no_state_access", "tfvars_redacted", "raw_profile_only",
            "no_new_canonical_namespaces"), True),
    })


__all__ = (
    "CONFIG_KINDS",
    "canonical_counts",
    "config_counts",
    "python_summary",
    "raw_count",
    "raw_rows",
    "repository_name",
    "terraform_summary",
)
