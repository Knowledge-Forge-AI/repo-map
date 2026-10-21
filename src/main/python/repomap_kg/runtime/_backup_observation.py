"""Observation parsers, fingerprinters, and runners for format-2 backups."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from typing import Any

from repomap_kg.runtime._backup_provenance import (
    BASELINE_EXTENSION_NAME, BASELINE_EXTENSION_SCHEMA, DEFAULT_OBSERVATION_TIMEOUT_SECONDS,
    DatabaseObservation, MAX_CONFIG_ENTRIES_PER_DATABASE, MAX_DEPENDENCY_EDGES_PER_DATABASE,
    MAX_EXTENSIONS_PER_DATABASE, MAX_OBSERVATION_JSON_BYTES, MAX_QUERY_OBSERVED_OUTPUT_BYTES,
    MAX_SCHEMAS_PER_DATABASE, _STDLIB_SUBPROCESS_RUN, catalog_observation_sql, provenance_error,
    redact_secret_text, run_bounded_popen, runtime_postgres_password,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner, container_internal_enabled, decode_process_output, planned_psql_command,
)
from repomap_kg.runtime.local import LocalRuntimePlan
from repomap_kg.runtime.release import PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, PACKAGED_PSQL

_VALID_OWNERSHIP_CLASSIFICATIONS = frozenset({"required", "permitted-foreign", "unclassified"})
_VALID_EXPERIMENTAL_CONTEXTS = frozenset({"unavailable", "none", "adr0077-disposable-pgvector"})
_VALID_BASELINE_ORIGINS = frozenset({"unavailable", "template_baseline", "non_baseline"})
_VALID_RELKINDS = frozenset({"r", "S", "p"})
_VALID_DEPTYPES = frozenset({"n", "a", "i"})
_REQUIRED_EXT_KEYS = frozenset({
    "name", "version", "schema", "owner", "relocatable", "trusted", "is_baseline", "baseline_origin",
    "ownership_classification", "declaration_identity", "experimental_context", "prerequisite_extensions",
    "extconfig_tables", "extcondition",
})


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, val in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key: {key!r}")
        obj[key] = val
    return obj


def _reject_nonfinite(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {token!r}")


def _observe_single_client_version(
    binary: str | None, field_name: str, *, plan: LocalRuntimePlan | None = None, command_runner: CommandRunner | None = None
) -> str:
    if binary is None:
        return "unused"
    cmd = (
        (plan.container_runtime, "exec", plan.identity.postgres_container, binary, "--version")
        if plan is not None and not container_internal_enabled() else (binary, "--version")
    )
    try:
        if command_runner is None or command_runner is _STDLIB_SUBPROCESS_RUN:
            raw = run_bounded_popen(cmd, max_output_bytes=4096, timeout_seconds=5.0, error_code="backup-observation-incomplete", field=field_name)
        else:
            res = command_runner(list(cmd), check=False, input=None, stdin=None, capture_output=True, text=False)
            if getattr(res, "returncode", 1) != 0:
                return "unavailable"
            out = getattr(res, "stdout", b"")
            raw = out if isinstance(out, bytes) else decode_process_output(out).encode("utf-8")
        first_line = decode_process_output(raw).splitlines()[0].strip() if raw else ""
        return first_line if first_line else "unavailable"
    except Exception:
        return "unavailable"


def observe_client_identities(
    *, pg_dump_bin: str | None = PACKAGED_PG_DUMP, pg_restore_bin: str | None = PACKAGED_PG_RESTORE,
    psql_bin: str | None = PACKAGED_PSQL, plan: LocalRuntimePlan | None = None, command_runner: CommandRunner | None = None,
) -> dict[str, str]:
    return {
        "pg_dump_version": _observe_single_client_version(pg_dump_bin, "pg_dump", plan=plan, command_runner=command_runner),
        "pg_restore_version": _observe_single_client_version(pg_restore_bin, "pg_restore", plan=plan, command_runner=command_runner),
        "psql_version": _observe_single_client_version(psql_bin, "psql", plan=plan, command_runner=command_runner),
    }


def canonical_provenance_fingerprint(server_provenance: Mapping[str, object], database_catalog: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"database_catalog": database_catalog, "server_provenance": server_provenance}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(payload) > MAX_OBSERVATION_JSON_BYTES:
        raise provenance_error("backup-observation-incomplete", "database_catalogs", f"canonical observation JSON exceeded {MAX_OBSERVATION_JSON_BYTES} bytes")
    return hashlib.sha256(payload).hexdigest()


def _req_str(value: object, *, field: str, database: str) -> str:
    if not isinstance(value, str) or value == "":
        raise provenance_error("backup-observation-incomplete", database, f"catalog observation field {field!r} must be a non-empty string")
    return value


def _normalize_server_provenance(
    raw: object, *, database: str, observed_clients: Mapping[str, str] | None = None
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise provenance_error("backup-observation-incomplete", database, "server_provenance must be an object")
    for req_key in ("server_version_num", "catalog_version_no", "server_version", "version_string", "os_arch_abi", "compile_abi", "shared_preload_libraries"):
        if req_key not in raw:
            raise provenance_error("backup-observation-incomplete", database, f"server_provenance missing {req_key!r}")
    version_num, cat_ver = raw.get("server_version_num"), raw.get("catalog_version_no")
    if isinstance(version_num, bool) or not isinstance(version_num, int) or version_num <= 0:
        raise provenance_error("backup-observation-incomplete", database, "invalid server_version_num")
    if isinstance(cat_ver, bool) or not isinstance(cat_ver, int) or cat_ver <= 0:
        raise provenance_error("backup-observation-incomplete", database, "invalid catalog_version_no")
    version_text = _req_str(raw.get("server_version"), field="server_version", database=database)
    version_string = _req_str(raw.get("version_string"), field="version_string", database=database)
    os_arch = _req_str(raw.get("os_arch_abi"), field="os_arch_abi", database=database)
    comp_raw = raw.get("compile_abi")
    if comp_raw == "unavailable":
        compile_abi: object = "unavailable"
    elif isinstance(comp_raw, Mapping):
        ma, dbs = comp_raw.get("max_data_alignment"), comp_raw.get("database_block_size")
        fpv, csum = comp_raw.get("float8_pass_by_value"), comp_raw.get("data_page_checksum_version")
        if (
            isinstance(ma, bool) or not isinstance(ma, int) or ma <= 0 or not isinstance(fpv, bool)
            or isinstance(csum, bool) or not isinstance(csum, int) or csum < 0
            or (dbs is not None and (isinstance(dbs, bool) or not isinstance(dbs, int) or dbs <= 0))
        ):
            raise provenance_error("backup-observation-incomplete", database, "invalid compile_abi metadata")
        abi_dict: dict[str, object] = {"data_page_checksum_version": csum, "float8_pass_by_value": fpv, "max_data_alignment": ma}
        if dbs is not None:
            abi_dict["database_block_size"] = dbs
        compile_abi = abi_dict
    else:
        raise provenance_error("backup-observation-incomplete", database, "invalid compile_abi")
    clients_raw = observed_clients if observed_clients is not None else raw.get("client_identities")
    if isinstance(clients_raw, Mapping):
        client_identities = {
            k: _req_str(clients_raw.get(k), field=f"client_identities.{k}", database=database)
            for k in ("pg_dump_version", "pg_restore_version", "psql_version")
        }
    else:
        raise provenance_error("backup-observation-incomplete", database, "invalid client_identities")
    preload_raw = raw.get("shared_preload_libraries")
    if not isinstance(preload_raw, list):
        raise provenance_error("backup-observation-incomplete", database, "shared_preload_libraries must be a list")
    preload_items = [_req_str(item, field="shared_preload_libraries[]", database=database) for item in preload_raw]
    if len(preload_items) != len(set(preload_items)):
        raise provenance_error("backup-observation-incomplete", database, "duplicate shared_preload_libraries entry")
    return {
        "catalog_version_no": cat_ver, "client_identities": client_identities,
        "compile_abi": compile_abi, "os_arch_abi": os_arch, "server_version": version_text,
        "server_version_num": version_num, "shared_preload_libraries": sorted(preload_items),
        "version_string": version_string,
    }


def _resolve_and_order_extensions(extensions: list[dict[str, Any]], *, database: str) -> list[dict[str, Any]]:
    by_name = {str(ext["name"]): ext for ext in extensions}
    if len(by_name) != len(extensions):
        raise provenance_error("backup-observation-incomplete", database, "duplicate installed_extensions entry")
    closure_cache: dict[str, list[str]] = {}
    visiting: set[str] = set()

    def _closure(name: str) -> list[str]:
        if name in closure_cache:
            return closure_cache[name]
        if name in visiting:
            raise provenance_error("backup-observation-incomplete", database, f"extension dependency cycle at {name!r}")
        visiting.add(name)
        acc: set[str] = set()
        for req in by_name[name]["prerequisite_extensions"]:
            if req == name or req not in by_name:
                raise provenance_error("backup-observation-incomplete", database, f"invalid prerequisite {req!r} for {name!r}")
            acc.add(req)
            acc.update(_closure(req))
        visiting.remove(name)
        closure_cache[name] = sorted(acc)
        return closure_cache[name]

    for name in sorted(by_name):
        by_name[name]["prerequisite_extensions"] = _closure(name)
    remaining, ordered = set(by_name), []
    while remaining:
        ready = sorted(n for n in remaining if all(p not in remaining for p in by_name[n]["prerequisite_extensions"]))
        if not ready:
            raise provenance_error("backup-observation-incomplete", database, "extension prerequisite cycle")
        remaining.remove(ready[0])
        ordered.append(by_name[ready[0]])
    return ordered


def _normalize_database_catalog(
    raw: object, *, database: str, expected_role: str | None = None, extension_policy: Mapping[str, Mapping[str, str]] | None = None
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise provenance_error("backup-observation-incomplete", database, "database_catalog must be an object")
    db_role = raw.get("database_role") if "database_role" in raw else None
    if db_role not in {"graph", "control"} or (expected_role is not None and db_role != expected_role):
        raise provenance_error("backup-observation-incomplete", database, "invalid database_role")
    cs_raw = raw.get("creation_semantics")
    if not isinstance(cs_raw, Mapping) or "daticulocale" not in cs_raw or "datcollversion" not in cs_raw:
        raise provenance_error("backup-observation-incomplete", database, "creation_semantics must be a complete object")
    icu_raw, collver_raw = cs_raw.get("daticulocale"), cs_raw.get("datcollversion")
    if (icu_raw is not None and not isinstance(icu_raw, str)) or (collver_raw is not None and not isinstance(collver_raw, str)):
        raise provenance_error("backup-observation-incomplete", database, "invalid locale metadata")
    creation_semantics: dict[str, object] = {
        "datcollate": _req_str(cs_raw.get("datcollate"), field="datcollate", database=database),
        "datcollversion": collver_raw, "datctype": _req_str(cs_raw.get("datctype"), field="datctype", database=database),
        "daticulocale": icu_raw, "datlocprovider": _req_str(cs_raw.get("datlocprovider"), field="datlocprovider", database=database),
        "encoding": _req_str(cs_raw.get("encoding"), field="encoding", database=database),
        "template": _req_str(cs_raw.get("template"), field="template", database=database),
    }

    schemas_raw = raw.get("non_system_schemas")
    if not isinstance(schemas_raw, list) or len(schemas_raw) > MAX_SCHEMAS_PER_DATABASE:
        raise provenance_error("backup-observation-incomplete", database, "non_system_schemas invalid or exceeds ceiling")
    schemas, seen_schemas = [], set()
    for item in schemas_raw:
        if not isinstance(item, Mapping):
            raise provenance_error("backup-observation-incomplete", database, "schema entry must be an object")
        s_name = _req_str(item.get("name"), field="schema.name", database=database)
        if s_name in seen_schemas:
            raise provenance_error("backup-observation-incomplete", database, f"duplicate schema {s_name!r}")
        seen_schemas.add(s_name)
        schemas.append({"name": s_name, "owner": _req_str(item.get("owner"), field="schema.owner", database=database)})
    schemas.sort(key=lambda entry: (entry["name"], entry["owner"]))

    exts_raw = raw.get("installed_extensions")
    if not isinstance(exts_raw, list) or len(exts_raw) > MAX_EXTENSIONS_PER_DATABASE:
        raise provenance_error("backup-observation-incomplete", database, "installed_extensions invalid or exceeds ceiling")
    extensions, total_cfg, expected_cfg_by_ext = [], 0, {}
    for item in exts_raw:
        if not isinstance(item, Mapping) or not _REQUIRED_EXT_KEYS.issubset(item.keys()):
            raise provenance_error("backup-observation-incomplete", database, "extension entry missing required fields")
        name = _req_str(item.get("name"), field="extension.name", database=database)
        schema = _req_str(item.get("schema"), field="extension.schema", database=database)
        owner = _req_str(item.get("owner"), field="extension.owner", database=database)
        version = _req_str(item.get("version"), field="extension.version", database=database)
        reloc, trusted, is_base = item.get("relocatable"), item.get("trusted"), item.get("is_baseline")
        pol = extension_policy.get(name, {}) if extension_policy else {}
        own_class = pol.get("ownership_classification", item.get("ownership_classification"))
        base_origin = pol.get("baseline_origin", item.get("baseline_origin"))
        decl_id = pol.get("declaration_identity", item.get("declaration_identity"))
        exp_ctx = pol.get("experimental_context", item.get("experimental_context"))
        prereqs_raw, ext_cfg, ext_cond = item.get("prerequisite_extensions"), item.get("extconfig_tables"), item.get("extcondition")
        if (
            not isinstance(reloc, bool) or (trusted is not None and not isinstance(trusted, bool)) or not isinstance(is_base, bool)
            or is_base != (name == BASELINE_EXTENSION_NAME and schema == BASELINE_EXTENSION_SCHEMA)
            or not isinstance(base_origin, str) or base_origin not in _VALID_BASELINE_ORIGINS
            or not isinstance(own_class, str) or own_class not in _VALID_OWNERSHIP_CLASSIFICATIONS
            or not isinstance(decl_id, str) or decl_id == "" or not isinstance(exp_ctx, str) or exp_ctx not in _VALID_EXPERIMENTAL_CONTEXTS
            or (own_class in {"required", "permitted-foreign"} and (decl_id in {"unavailable", "undeclared"} or exp_ctx != "none"))
            or (exp_ctx not in {"unavailable", "none"} and own_class != "unclassified")
            or not isinstance(prereqs_raw, list) or not isinstance(ext_cfg, list) or not isinstance(ext_cond, list)
        ):
            raise provenance_error("backup-observation-incomplete", database, f"invalid metadata for extension {name!r}")
        prereqs = [_req_str(p, field="prerequisite_extensions[]", database=database) for p in prereqs_raw]
        if len(prereqs) != len(set(prereqs)):
            raise provenance_error("backup-observation-incomplete", database, f"duplicate prerequisites for {name!r}")
        cfg_list = [_req_str(t, field="extconfig_tables[]", database=database) for t in ext_cfg]
        if not all(isinstance(c, str) for c in ext_cond) or len(ext_cond) != len(cfg_list):
            raise provenance_error("backup-observation-incomplete", database, f"invalid extcondition for {name!r}")
        cond_list = [str(c) for c in ext_cond]
        total_cfg += len(cfg_list)
        if total_cfg > MAX_CONFIG_ENTRIES_PER_DATABASE:
            raise provenance_error("backup-observation-incomplete", database, "extension config entries exceed ceiling")
        expected_cfg_by_ext[name] = [(tbl, cond_list[idx]) for idx, tbl in enumerate(cfg_list)]
        extensions.append({
            "baseline_origin": base_origin, "declaration_identity": decl_id, "experimental_context": exp_ctx,
            "extcondition": cond_list, "extconfig_tables": cfg_list, "is_baseline": is_base, "name": name,
            "owner": owner, "ownership_classification": own_class, "prerequisite_extensions": prereqs,
            "relocatable": reloc, "schema": schema, "trusted": trusted, "version": version,
        })
    ordered_extensions = _resolve_and_order_extensions(extensions, database=database)
    ext_names = {str(e["name"]) for e in ordered_extensions}

    cfg_raw = raw.get("extension_config_tables")
    if not isinstance(cfg_raw, list) or len(cfg_raw) > MAX_CONFIG_ENTRIES_PER_DATABASE:
        raise provenance_error("backup-observation-incomplete", database, "extension_config_tables invalid or exceeds ceiling")
    config_tables: list[dict[str, object]] = []
    seen_cfg: set[tuple[str, ...]] = set()
    actual_cfg_by_ext: dict[str, list[tuple[str, str]]] = {n: [] for n in ext_names}
    for item in cfg_raw:
        if not isinstance(item, Mapping):
            raise provenance_error("backup-observation-incomplete", database, "config table entry must be an object")
        ext_name = _req_str(item.get("extension"), field="cfg.extension", database=database)
        schema_name = _req_str(item.get("schema"), field="cfg.schema", database=database)
        table_name = _req_str(item.get("table"), field="cfg.table", database=database)
        qualified = _req_str(item.get("qualified_table"), field="cfg.qualified_table", database=database)
        relkind, cond_val = item.get("relkind"), item.get("condition")
        cfg_key = (ext_name, schema_name, table_name)
        if (
            ext_name not in ext_names or "." not in qualified or not isinstance(relkind, str) or relkind not in _VALID_RELKINDS
            or "condition" not in item or not isinstance(cond_val, str) or cfg_key in seen_cfg or (ext_name, qualified) in seen_cfg
        ):
            raise provenance_error("backup-observation-incomplete", database, "invalid extension_config_tables entry")
        seen_cfg.update((cfg_key, (ext_name, qualified)))
        actual_cfg_by_ext[ext_name].append((qualified, cond_val))
        config_tables.append({
            "condition": cond_val, "extension": ext_name, "qualified_table": qualified,
            "relkind": relkind, "schema": schema_name, "table": table_name,
        })
    if expected_cfg_by_ext != actual_cfg_by_ext:
        raise provenance_error("backup-observation-incomplete", database, "extconfig_tables mismatch with extension_config_tables")

    dep_raw = raw.get("extension_dependency_summary")
    if not isinstance(dep_raw, Mapping) or "edge_count" not in dep_raw:
        raise provenance_error("backup-observation-incomplete", database, "extension_dependency_summary invalid")
    edges_raw, edge_count_raw = dep_raw.get("edges"), dep_raw.get("edge_count")
    if (
        not isinstance(edges_raw, list) or isinstance(edge_count_raw, bool) or not isinstance(edge_count_raw, int)
        or edge_count_raw != len(edges_raw) or len(edges_raw) > MAX_DEPENDENCY_EDGES_PER_DATABASE
    ):
        raise provenance_error("backup-observation-incomplete", database, "extension_dependency_summary.edges invalid")
    edges: list[dict[str, object]] = []
    by_class_counts: dict[str, int] = {}
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    for item in edges_raw:
        if not isinstance(item, Mapping):
            raise provenance_error("backup-observation-incomplete", database, "dependency edge must be an object")
        ext_n = _req_str(item.get("extension"), field="edges.extension", database=database)
        obj_class = _req_str(item.get("object_class"), field="edges.object_class", database=database)
        obj_ident = _req_str(item.get("object_identity"), field="edges.object_identity", database=database)
        deptype = _req_str(item.get("deptype"), field="edges.deptype", database=database)
        obj_schema, portable_raw = item.get("object_schema"), item.get("identity_portable")
        if (
            ext_n not in ext_names or ext_n == BASELINE_EXTENSION_NAME or deptype not in _VALID_DEPTYPES
            or "object_schema" not in item or not isinstance(obj_schema, str)
            or "identity_portable" not in item or not isinstance(portable_raw, bool)
            or portable_raw != (not obj_ident.startswith("unidentified:"))
        ):
            raise provenance_error("backup-observation-incomplete", database, "invalid dependency edge metadata")
        edge_key = (ext_n, obj_class, obj_schema, obj_ident, deptype)
        if edge_key in seen_edges:
            raise provenance_error("backup-observation-incomplete", database, "duplicate dependency edge")
        seen_edges.add(edge_key)
        edges.append({
            "deptype": deptype, "extension": ext_n, "identity_portable": portable_raw,
            "object_class": obj_class, "object_identity": obj_ident, "object_schema": obj_schema,
        })
        by_class_counts[obj_class] = by_class_counts.get(obj_class, 0) + 1
    edges.sort(key=lambda e: (str(e["extension"]), str(e["object_class"]), str(e["object_schema"]), str(e["object_identity"]), str(e["deptype"])))
    return {
        "creation_semantics": creation_semantics, "database_role": db_role, "extension_config_tables": config_tables,
        "extension_dependency_summary": {
            "by_class": {k: by_class_counts[k] for k in sorted(by_class_counts)}, "edge_count": len(edges), "edges": edges
        },
        "installed_extensions": ordered_extensions, "non_system_schemas": schemas,
    }


def parse_and_validate_catalog_observation(
    raw_bytes: bytes, *, database: str, expected_role: str | None = None,
    extension_policy: Mapping[str, Mapping[str, str]] | None = None, observed_clients: Mapping[str, str] | None = None,
) -> DatabaseObservation:
    if raw_bytes.lstrip().startswith(b"OVERFLOW:") or len(raw_bytes) > min(MAX_QUERY_OBSERVED_OUTPUT_BYTES, MAX_OBSERVATION_JSON_BYTES):
        raise provenance_error("backup-observation-incomplete", database, f"catalog observation output exceeded {MAX_QUERY_OBSERVED_OUTPUT_BYTES} bytes")
    try:
        payload = json.loads(raw_bytes.decode("utf-8").strip(), object_pairs_hook=_unique_json_pairs, parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise provenance_error("backup-observation-incomplete", database, "catalog observation output is not valid strict UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise provenance_error("backup-observation-incomplete", database, "observation root must be an object")
    server_prov = _normalize_server_provenance(payload.get("server_provenance"), database=database, observed_clients=observed_clients)
    db_catalog = _normalize_database_catalog(payload.get("database_catalog"), database=database, expected_role=expected_role, extension_policy=extension_policy)
    return DatabaseObservation(database, server_prov, db_catalog, canonical_provenance_fingerprint(server_prov, db_catalog))


def verify_provenance_fingerprints(before: DatabaseObservation, after: DatabaseObservation) -> DatabaseObservation:
    if before.fingerprint != after.fingerprint:
        raise provenance_error("backup-observation-drift", before.database, "catalog or server provenance drifted during pg_dump")
    return after


def observe_database_provenance(plan: LocalRuntimePlan, database: str, command_runner: CommandRunner) -> DatabaseObservation:
    secret = runtime_postgres_password(plan)
    if database in plan.graph_databases:
        role = "graph"
    elif database in plan.owned_databases:
        role = "control"
    else:
        raise provenance_error("database-not-owned", database, "database is not owned by this RepoMap runtime")
    command = planned_psql_command(plan, database, "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", "-c", catalog_observation_sql(role))
    env = dict(os.environ, PGPASSWORD=secret)
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        raw_bytes = run_bounded_popen(
            command, max_output_bytes=MAX_QUERY_OBSERVED_OUTPUT_BYTES, timeout_seconds=DEFAULT_OBSERVATION_TIMEOUT_SECONDS,
            error_code="backup-observation-incomplete", field=database, secret=secret, env=env,
        )
    else:
        completed = command_runner(list(command), check=False, input=None, stdin=None, capture_output=True, text=False, env=env)
        if completed.returncode != 0:
            msg = redact_secret_text(decode_process_output(completed.stderr).strip(), secret) or "catalog observation command failed"
            raise provenance_error("backup-observation-incomplete", database, msg)
        raw_bytes = completed.stdout if isinstance(completed.stdout, bytes) else decode_process_output(completed.stdout).encode("utf-8")
    clients = observe_client_identities(plan=plan, command_runner=command_runner) if b'"client_identities"' not in raw_bytes else None
    return parse_and_validate_catalog_observation(raw_bytes, database=database, expected_role=role, observed_clients=clients)
