"""Shared fixture builders and real-seed boundary mutations for backup provenance integration tests."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from typing import Any

from repomap_test_support.local_db_backup import connect_real_postgres


def sql_state_snapshot(postgres: Any, database: str, *, is_control: bool) -> dict[str, object]:
    ledger_table = "repomap_control_schema_migrations" if is_control else "repomap_schema_migrations"
    with closing(connect_real_postgres(postgres, database)) as conn:
        tables = [
            (str(r[0]), str(r[1]))
            for r in conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name"
            ).fetchall()
        ]
        ledger_rows = [
            (int(r[0]), str(r[1]), str(r[2]), str(r[3]))
            for r in conn.execute(
                f"SELECT ordinal, changeset_id, migration_path, checksum "
                f"FROM public.{ledger_table} ORDER BY ordinal"
            ).fetchall()
        ]
        if is_control:
            job_row = conn.execute("SELECT count(*) FROM public.jobs").fetchone()
            return {"tables": tables, "ledger_rows": ledger_rows, "job_count": int(job_row[0]) if job_row else 0}
        repo_rows = [
            (str(r[0]), str(r[1]), str(r[2]))
            for r in conn.execute(
                "SELECT name, root_path, repository_identity FROM public.repositories ORDER BY id"
            ).fetchall()
        ]
        return {"tables": tables, "ledger_rows": ledger_rows, "repo_rows": repo_rows}


def ext_record(name: str = "cube", *, prereqs: list[str] | None = None, **overrides: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "1.5", "schema": "public", "owner": "repomap",
        "relocatable": True, "trusted": True, "is_baseline": False, "baseline_origin": "non_baseline",
        "ownership_classification": "unclassified", "declaration_identity": "unavailable",
        "experimental_context": "unavailable", "prerequisite_extensions": prereqs or [],
        "extconfig_tables": [], "extcondition": [], **overrides,
    }


def malformed_toc_bytes_cases(real_toc_bytes: bytes) -> list[tuple[bytes, str]]:
    prefix = real_toc_bytes if real_toc_bytes.endswith(b"\n") else real_toc_bytes + b"\n"
    return [
        (b"\xff\xfe", "TOC is not strict UTF-8"),
        (prefix + b"no semicolon line\n", "unparseable TOC line"),
        (prefix + b"abc; 1 2 TABLE x\n", "unparseable TOC entry line"),
        (prefix + b"99991; 1 2 EXTENSION bad\n", "unparseable TOC EXTENSION line"),
        (prefix + b"99992; 1 2 EXTENSION -  \n", "unparseable TOC EXTENSION line"),
        (prefix + b"99993; 1 2 SCHEMA bad\n", "unparseable TOC SCHEMA line"),
        (prefix + b"99994; 1 2 SCHEMA - nospace\n", "unparseable TOC SCHEMA line"),
        (prefix + b"99995; 1 2 TABLE DATA\n", "unparseable TOC data line"),
        (prefix + b"99996; 1 2 TABLE DATA nospace owner\n", "unparseable TOC data line"),
        (prefix + b"99997; 1 2 SHORT x\n", "unparseable TOC entry line"),
    ]


def malformed_toc_catalog_cases(real_cat: Mapping[str, Any]) -> list[tuple[dict[str, Any], str]]:
    base = dict(real_cat)
    exts, schemas = list(base["installed_extensions"]), list(base["non_system_schemas"])
    return [
        ({**base, "installed_extensions": "bad"}, "installed_extensions missing in catalog"),
        ({**base, "installed_extensions": [{"name": "a\nb"}]}, "invalid extension entry in catalog"),
        ({**base, "installed_extensions": [*exts, ext_record("cube")]}, "TOC extensions"),
        ({**base, "non_system_schemas": "bad"}, "non_system_schemas missing in catalog"),
        ({**base, "non_system_schemas": [{"name": "s", "owner": "bad owner"}]}, "ambiguous schema entry"),
        ({**base, "non_system_schemas": [*schemas, {"name": "ghost_schema", "owner": "repomap"}]}, "TOC schemas"),
        ({**base, "extension_config_tables": "bad"}, "extension_config_tables missing in catalog"),
        ({**base, "extension_config_tables": ["not-a-dict"]}, "invalid extension_config_tables entry"),
        (
            {
                **base,
                "extension_config_tables": [
                    {"schema": "public", "table": "t", "qualified_table": "public.t", "relkind": "bad"}
                ],
            },
            "incomplete extension_config_tables entry",
        ),
        (
            {
                **base,
                "extension_config_tables": [
                    {"schema": "a b", "table": "c", "qualified_table": "a b.c", "relkind": "r"},
                    {"schema": "a", "table": "b c", "qualified_table": "a.b c", "relkind": "r"},
                ],
            },
            "ambiguous extension_config_tables TOC key",
        ),
        (
            {
                **base,
                "extension_config_tables": [
                    {"schema": "public", "table": "seq1", "qualified_table": "public.seq1", "relkind": "S"}
                ],
            },
            "TOC missing SEQUENCE SET for extconfig",
        ),
        (
            {
                **base,
                "extension_config_tables": [
                    {"schema": "public", "table": "tbl1", "qualified_table": "public.tbl1", "relkind": "r"}
                ],
            },
            "TOC missing TABLE DATA for extconfig",
        ),
    ]


def malformed_server_provenance_cases(real_srv: Mapping[str, Any]) -> list[Any]:
    srv = dict(real_srv)
    abi = dict(srv["compile_abi"]) if isinstance(srv.get("compile_abi"), Mapping) else {"max_data_alignment": 8}
    return [
        "not-a-dict",
        {k: v for k, v in srv.items() if k != "server_version_num"},
        {**srv, "server_version_num": 0},
        {**srv, "catalog_version_no": 0},
        {**srv, "server_version": ""},
        {**srv, "compile_abi": 123},
        {**srv, "compile_abi": {**abi, "max_data_alignment": 0}},
        {**srv, "client_identities": "bad"},
        {**srv, "shared_preload_libraries": "bad"},
        {**srv, "shared_preload_libraries": ["x", "x"]},
        {**srv, "system_identifier": ""},
    ]


def malformed_database_catalog_cases(real_cat: Mapping[str, Any]) -> list[Any]:
    cat = dict(real_cat)
    cs = dict(cat["creation_semantics"])
    exts = list(cat["installed_extensions"])
    cat_cube = {**cat, "installed_extensions": [*exts, ext_record("cube")]}
    edge = {
        "extension": "cube", "object_class": "table", "object_schema": "public",
        "object_identity": "public.t", "identity_portable": True, "deptype": "n",
    }
    cfg = {
        "extension": "cube", "schema": "public", "table": "t",
        "qualified_table": "public.t", "relkind": "r", "condition": "",
    }
    return [
        "not-a-dict",
        {**cat, "database_role": "bad"},
        {**cat, "creation_semantics": {}},
        {**cat, "creation_semantics": {**cs, "daticulocale": 123}},
        {**cat, "non_system_schemas": "bad"},
        {**cat, "non_system_schemas": ["bad"]},
        {**cat, "non_system_schemas": [{"name": "s", "owner": "o"}, {"name": "s", "owner": "o"}]},
        {**cat, "installed_extensions": "bad"},
        {**cat, "installed_extensions": [{"name": "x"}]},
        {**cat, "installed_extensions": [*exts, ext_record("cube", relocatable="no")]},
        {**cat, "installed_extensions": [*exts, ext_record("cube", prereqs=["a", "a"])]},
        {**cat, "installed_extensions": [*exts, ext_record("cube", extconfig_tables=["public.t"], extcondition=[])]},
        {**cat, "installed_extensions": [*exts, ext_record("a"), ext_record("a")]},
        {**cat, "installed_extensions": [*exts, ext_record("a", prereqs=["b"]), ext_record("b", prereqs=["a"])]},
        {**cat, "installed_extensions": [*exts, ext_record("a", prereqs=["missing"])]},
        {**cat, "extension_config_tables": "bad"},
        {**cat, "extension_config_tables": ["bad"]},
        {**cat_cube, "extension_config_tables": [{**cfg, "relkind": "bad"}]},
        {**cat_cube, "extension_config_tables": [cfg]},
        {**cat, "extension_dependency_summary": "bad"},
        {**cat, "extension_dependency_summary": {"edge_count": 2, "edges": []}},
        {**cat, "extension_dependency_summary": {"edge_count": 1, "edges": ["bad"]}},
        {**cat_cube, "extension_dependency_summary": {"edge_count": 1, "edges": [{**edge, "deptype": "bad"}]}},
        {**cat_cube, "extension_dependency_summary": {"edge_count": 2, "edges": [edge, edge]}},
    ]


def malformed_format2_manifest_cases(
    real_manifest: Mapping[str, Any], graph_db: str
) -> list[tuple[dict[str, Any], str, str]]:
    m = dict(real_manifest)
    art = dict(m["artifact_provenance"])
    b0 = dict(art["archive_bindings"][0])
    cat, srv = dict(m["database_catalogs"][graph_db]), dict(m["server_provenance"])
    sha = str(b0["sha256"])
    c_scope = "exact-configured-graph-control-databases"
    inv = "backup-manifest-invalid"
    cases: list[tuple[dict[str, Any], str, str]] = [
        ({**m, "backup_format_version": 99}, "backup-format-unsupported", "backup manifest format is unsupported"),
        ({k: v for k, v in m.items() if k not in ("database", "databases")}, inv, "backup manifest is malformed"),
        ({**m, "restore_protocol": "bad"}, inv, "valid restore_protocol"),
        ({**m, "restore_supported": "yes"}, inv, "boolean restore_supported"),
        ({**m, "restore_blockers": [""]}, inv, "string list restore_blockers"),
        ({**m, "quiescence": {}}, inv, "valid quiescence provenance"),
        ({**m, "artifact_provenance": None}, inv, "requires artifact_provenance"),
        ({**m, "artifact_provenance": {**art, "archive_bindings": "bad"}}, inv, "must be a list"),
        ({**m, "database_catalogs": {"other": cat}}, inv, "are inconsistent"),
        (
            {**m, "scope": c_scope, "databases": [graph_db, f"{graph_db}_control"]},
            "coordinated-backup-topology-mismatch", "provenance bindings do not match databases",
        ),
        (
            {**m, "scope": c_scope, "dump_files": []},
            "coordinated-backup-dump-set-invalid", "dump_files must match databases",
        ),
        (
            {**m, "scope": c_scope, "dump_files": [{"name": "wrong.pgcustom", "sha256": sha, "size_bytes": 10}]},
            "coordinated-backup-dump-set-invalid", "coordinated dump_files names do not match databases",
        ),
        (
            {**m, "artifact_provenance": {**art, "archive_bindings": [{**b0, "size_bytes": 0}]}},
            inv, "invalid archive_binding entry",
        ),
    ]
    for bad_srv in malformed_server_provenance_cases(srv):
        cases.append(({**m, "server_provenance": bad_srv}, inv, "invalid server_provenance"))
    for bad_cat in malformed_database_catalog_cases(cat):
        cases.append(({**m, "database_catalogs": {graph_db: bad_cat}}, inv, f"invalid database_catalogs[{graph_db!r}]"))
    return cases
