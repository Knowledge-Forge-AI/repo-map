"""Live catalog, server, and archive TOC provenance for format-2 backups."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, TypeGuard

from common_lore_index.runtime.backup_commands import (
    CommandRunner, decode_process_output, planned_pg_restore_list_command, read_runtime_password,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime._backup_process import BoundedProcessError, ProcessRetirement, run_bounded_process
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan, redact_runtime_text

BACKUP_FORMAT_VERSION = 2
SUPPORTED_BACKUP_FORMAT_VERSIONS: tuple[int, ...] = (1, 2)
CORE_V1_RESTORE_PROTOCOL = "core_v1"
EXTENSION_V2_RESTORE_PROTOCOL = "extension_v2"
BASELINE_EXTENSION_NAME = "plpgsql"
BASELINE_EXTENSION_SCHEMA = "pg_catalog"

MAX_MANIFEST_UTF8_BYTES = 8 * 1024 * 1024
MAX_QUERY_OBSERVED_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_TOC_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_OBSERVATION_JSON_BYTES = 8 * 1024 * 1024
MAX_DATABASES_PER_MANIFEST = 256
MAX_EXTENSIONS_PER_DATABASE = 256
MAX_SCHEMAS_PER_DATABASE = 4096
MAX_DEPENDENCY_EDGES_PER_DATABASE = 8192
MAX_CONFIG_ENTRIES_PER_DATABASE = 1024

DEFAULT_OBSERVATION_TIMEOUT_SECONDS = 30.0
DEFAULT_TOC_TIMEOUT_SECONDS = 60.0
_STDLIB_SUBPROCESS_RUN = subprocess.run
CATALOG_OBSERVATION_MARKER = "/* repomap_d9_catalog_observation */"


def is_supported_format_version(version: object) -> TypeGuard[int]:
    return not isinstance(version, bool) and isinstance(version, int) and version in SUPPORTED_BACKUP_FORMAT_VERSIONS


def catalog_observation_sql(database_role: str = "graph") -> str:
    if database_role not in {"graph", "control"}:
        raise ValueError(f"invalid database_role: {database_role!r}")
    return (
        f"{CATALOG_OBSERVATION_MARKER}\n"
        f"SELECT CASE WHEN octet_length(obs.payload) > {MAX_QUERY_OBSERVED_OUTPUT_BYTES} "
        "THEN 'OVERFLOW:' || octet_length(obs.payload)::text ELSE obs.payload END FROM (SELECT jsonb_build_object(\n"
        "  'server_provenance', jsonb_build_object('server_version_num', current_setting('server_version_num')::int,\n"
        "    'server_version', current_setting('server_version'), 'version_string', version(),\n"
        "    'os_arch_abi', COALESCE(NULLIF(substring(version() FROM ' on ([^,]+)'), ''), 'unavailable'),\n"
        "    'compile_abi', (SELECT jsonb_build_object('max_data_alignment', i.max_data_alignment, 'database_block_size', i.database_block_size,\n"
        "      'float8_pass_by_value', i.float8_pass_by_value, 'data_page_checksum_version', i.data_page_checksum_version) FROM pg_control_init() i),\n"
        "    'catalog_version_no', (SELECT catalog_version_no::bigint FROM pg_control_system()),\n"
        "    'system_identifier', (SELECT system_identifier::text FROM pg_control_system()),\n"
        "    'shared_preload_libraries', COALESCE((SELECT jsonb_agg(sub.lib ORDER BY sub.lib) FROM (SELECT DISTINCT btrim(raw_lib) AS lib\n"
        "      FROM unnest(string_to_array(COALESCE(current_setting('shared_preload_libraries', true), ''), ',')) AS raw_lib\n"
        "      WHERE btrim(raw_lib) <> '') sub), '[]'::jsonb)),\n"
        f"  'database_catalog', (SELECT jsonb_build_object('database_role', '{database_role}',\n"
        "    'creation_semantics', jsonb_build_object('template', 'unknown', 'encoding', pg_encoding_to_char(d.encoding),\n"
        "      'datcollate', d.datcollate, 'datctype', d.datctype, 'datlocprovider', d.datlocprovider::text,\n"
        "      'daticulocale', COALESCE(to_jsonb(d)->>'daticulocale', to_jsonb(d)->>'datlocale'), 'datcollversion', to_jsonb(d)->>'datcollversion'),\n"
        "    'non_system_schemas', COALESCE((SELECT jsonb_agg(jsonb_build_object('name', s.nspname, 'owner', s.rolname) ORDER BY s.nspname)\n"
        "      FROM (SELECT n.nspname, r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner\n"
        "      WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')\n"
        "        AND n.nspname NOT LIKE 'pg\\_temp\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg\\_toast\\_temp\\_%' ESCAPE '\\'\n"
        f"      ORDER BY n.nspname LIMIT {MAX_SCHEMAS_PER_DATABASE + 1}) s), '[]'::jsonb),\n"
        "    'installed_extensions', COALESCE((SELECT jsonb_agg(jsonb_build_object(\n"
        "      'name', ext.extname, 'version', ext.extversion, 'schema', ext.nspname, 'owner', ext.rolname,\n"
        "      'relocatable', ext.extrelocatable, 'trusted', ext.trusted, 'is_baseline', ext.is_baseline,\n"
        "      'baseline_origin', ext.baseline_origin, 'ownership_classification', ext.ownership_classification,\n"
        "      'declaration_identity', ext.declaration_identity, 'experimental_context', ext.experimental_context,\n"
        "      'prerequisite_extensions', ext.prerequisite_extensions, 'extconfig_tables', ext.extconfig_tables,\n"
        "      'extcondition', ext.extcondition) ORDER BY ext.extname) FROM (\n"
        "      SELECT e.extname, e.extversion, n.nspname, r.rolname, e.extrelocatable,\n"
        "        (to_jsonb(aev)->>'trusted')::boolean AS trusted, (e.extname = 'plpgsql' AND n.nspname = 'pg_catalog') AS is_baseline,\n"
        "        'unavailable' AS baseline_origin, 'unclassified' AS ownership_classification,\n"
        "        'unavailable' AS declaration_identity, 'unavailable' AS experimental_context,\n"
        "        COALESCE((SELECT jsonb_agg(req_name ORDER BY req_name) FROM (\n"
        "          SELECT DISTINCT pe.extname::text AS req_name FROM pg_depend d_ext JOIN pg_extension pe ON pe.oid = d_ext.refobjid\n"
        "            WHERE d_ext.classid = 'pg_extension'::regclass AND d_ext.objid = e.oid\n"
        "              AND d_ext.refclassid = 'pg_extension'::regclass AND d_ext.refobjid <> e.oid\n"
        "          UNION SELECT DISTINCT req::text AS req_name FROM unnest(COALESCE(aev.requires, '{}'::name[])) AS req\n"
        "        ) reqs), '[]'::jsonb) AS prerequisite_extensions,\n"
        "        COALESCE((SELECT jsonb_agg(format('%I.%I', cn.nspname, c.relname) ORDER BY u.ord)\n"
        "          FROM unnest(COALESCE(e.extconfig, '{}'::oid[])) WITH ORDINALITY AS u(relid, ord)\n"
        "          JOIN pg_class c ON c.oid = u.relid JOIN pg_namespace cn ON cn.oid = c.relnamespace), '[]'::jsonb) AS extconfig_tables,\n"
        "        COALESCE(to_jsonb(e.extcondition), '[]'::jsonb) AS extcondition\n"
        "      FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace JOIN pg_roles r ON r.oid = e.extowner\n"
        "      LEFT JOIN pg_available_extension_versions aev ON aev.name = e.extname AND aev.version = e.extversion\n"
        f"      ORDER BY e.extname LIMIT {MAX_EXTENSIONS_PER_DATABASE + 1}) ext), '[]'::jsonb),\n"
        "    'extension_config_tables', COALESCE((SELECT jsonb_agg(jsonb_build_object('extension', cfg.extname, 'schema', cfg.nspname,\n"
        "      'table', cfg.relname, 'qualified_table', format('%I.%I', cfg.nspname, cfg.relname), 'relkind', cfg.relkind, 'condition', cfg.condition\n"
        "    ) ORDER BY cfg.extname, cfg.ord) FROM (SELECT e.extname, cn.nspname, c.relname, c.relkind::text AS relkind, u.ord,\n"
        "      e.extcondition[u.ord::int] AS condition FROM pg_extension e\n"
        "      CROSS JOIN LATERAL unnest(COALESCE(e.extconfig, '{}'::oid[])) WITH ORDINALITY AS u(relid, ord)\n"
        "      JOIN pg_class c ON c.oid = u.relid JOIN pg_namespace cn ON cn.oid = c.relnamespace\n"
        f"      ORDER BY e.extname, u.ord LIMIT {MAX_CONFIG_ENTRIES_PER_DATABASE + 1}) cfg), '[]'::jsonb),\n"
        "    'extension_dependency_summary', (WITH ext_members AS (\n"
        "        SELECT e.oid AS ext_oid, e.extname, dm.classid, dm.objid FROM pg_extension e\n"
        "        JOIN pg_depend dm ON dm.refclassid = 'pg_extension'::regclass AND dm.refobjid = e.oid AND dm.deptype = 'e' WHERE e.extname <> 'plpgsql'\n"
        "      ), raw_edges AS (\n"
        "        SELECT DISTINCT e.extname AS extension, COALESCE(NULLIF(id.type, ''), d.classid::regclass::text) AS object_class,\n"
        "          COALESCE(NULLIF(id.schema, ''), (SELECT n.nspname FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace WHERE d.classid = 'pg_constraint'::regclass AND con.oid = d.objid), (SELECT n.nspname FROM pg_attrdef ad JOIN pg_class c ON c.oid = ad.adrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE d.classid = 'pg_attrdef'::regclass AND ad.oid = d.objid), (SELECT n.nspname FROM pg_amop ao JOIN pg_opfamily opf ON opf.oid = ao.amopfamily JOIN pg_namespace n ON n.oid = opf.opfnamespace WHERE d.classid = 'pg_amop'::regclass AND ao.oid = d.objid), (SELECT n.nspname FROM pg_amproc ap JOIN pg_opfamily opf ON opf.oid = ap.amprocfamily JOIN pg_namespace n ON n.oid = opf.opfnamespace WHERE d.classid = 'pg_amproc'::regclass AND ap.oid = d.objid), '') AS object_schema,\n"
        "          CASE WHEN id.identity IS NOT NULL AND btrim(id.identity) <> '' THEN id.identity\n"
        "            ELSE 'unidentified:' || COALESCE(NULLIF(id.type, ''), d.classid::regclass::text) END AS object_identity,\n"
        "          (id.identity IS NOT NULL AND btrim(id.identity) <> '') AS identity_portable, d.deptype::text AS deptype\n"
        "        FROM pg_depend d JOIN pg_extension e ON e.extname <> 'plpgsql' AND (\n"
        "          (d.refclassid = 'pg_extension'::regclass AND d.refobjid = e.oid AND d.deptype <> 'e')\n"
        "          OR EXISTS (SELECT 1 FROM ext_members em WHERE em.ext_oid = e.oid AND em.classid = d.refclassid AND em.objid = d.refobjid)\n"
        "        ) CROSS JOIN LATERAL pg_identify_object(d.classid, d.objid, d.objsubid) AS id\n"
        "        WHERE d.classid <> 'pg_extension'::regclass AND NOT EXISTS (\n"
        "          SELECT 1 FROM ext_members self_em WHERE self_em.classid = d.classid AND self_em.objid = d.objid)\n"
        f"          AND d.deptype IN ('n', 'a', 'i') ORDER BY 1, 2, 3, 4, 5, 6 LIMIT {MAX_DEPENDENCY_EDGES_PER_DATABASE + 1}\n"
        "      ) SELECT jsonb_build_object('edge_count', (SELECT count(*)::int FROM raw_edges),\n"
        "        'edges', COALESCE((SELECT jsonb_agg(jsonb_build_object('extension', re.extension, 'object_class', re.object_class,\n"
        "          'object_schema', re.object_schema, 'object_identity', re.object_identity, 'identity_portable', re.identity_portable,\n"
        "          'deptype', re.deptype) ORDER BY re.extension, re.object_class, re.object_schema, re.object_identity, re.deptype)\n"
        "        FROM raw_edges re), '[]'::jsonb)))) FROM pg_database d WHERE d.datname = current_database()))::text AS payload) obs;"
    )


CATALOG_OBSERVATION_SQL = catalog_observation_sql("graph")


@dataclass(frozen=True)
class DatabaseObservation:
    database: str
    server_provenance: dict[str, Any]
    database_catalog: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class ArchiveTocObservation:
    database: str
    toc_sha256: str
    extensions: tuple[str, ...]
    schemas: tuple[str, ...]
    table_data: tuple[str, ...]
    sequence_set: tuple[str, ...] = ()
    entry_count: int = 0


def provenance_error(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def runtime_postgres_password(plan: LocalRuntimePlan) -> str:
    return read_runtime_password(plan.env_file)


def redact_secret_text(text: str, secret: str | None = None) -> str:
    redacted = redact_runtime_text(text)
    return redacted.replace(secret, "[REDACTED]") if secret else redacted


def run_bounded_popen(
    command: Sequence[str], *, max_output_bytes: int, timeout_seconds: float, error_code: str,
    field: str, secret: str | None = None, env: Mapping[str, str] | None = None, stdin_path: Path | None = None,
    stdin_bytes: bytes | None = None, retirement: ProcessRetirement | None = None,
) -> bytes:
    try:
        return run_bounded_process(
            command, max_output_bytes=max_output_bytes, timeout_seconds=timeout_seconds,
            env=env, stdin_path=stdin_path, stdin_bytes=stdin_bytes, retirement=retirement,
        )
    except BoundedProcessError as exc:
        raise provenance_error(error_code, field, redact_secret_text(str(exc), secret)) from exc


def parse_toc_entries(raw_toc_bytes: bytes, *, database: str) -> ArchiveTocObservation:
    if len(raw_toc_bytes) > MAX_TOC_OUTPUT_BYTES:
        raise provenance_error("backup-toc-inconsistent", database, f"TOC exceeded {MAX_TOC_OUTPUT_BYTES} bytes")
    toc_sha256 = hashlib.sha256(raw_toc_bytes).hexdigest()
    toc_extensions: set[str] = set()
    toc_schemas: set[str] = set()
    toc_table_data: set[str] = set()
    toc_sequence_set: set[str] = set()
    entry_count = 0
    try:
        toc_text = raw_toc_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise provenance_error("backup-toc-inconsistent", database, "TOC is not strict UTF-8") from exc
    for raw_line in toc_text.split("\n"):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith(";"):
            continue
        if ";" not in line:
            raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC line")
        dump_id_str, after_semi = line.split(";", 1)
        parts = after_semi.lstrip(" ").split(" ", 2)
        if (
            not dump_id_str.strip().isdigit() or not after_semi.startswith(" ") or len(parts) < 3
            or not parts[0].isdigit() or not parts[1].isdigit() or not parts[2] or parts[2].startswith(" ")
        ):
            raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC entry line")
        entry_count += 1
        rest = parts[2]
        if rest == "EXTENSION" or rest.startswith("EXTENSION "):
            if not rest.startswith("EXTENSION - "):
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC EXTENSION line")
            ext_tail = rest[len("EXTENSION - "):]
            ext_name = ext_tail[:-1] if ext_tail.endswith(" ") else ext_tail
            if not ext_name:
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC EXTENSION line")
            toc_extensions.add(ext_name)
        elif rest == "SCHEMA" or rest.startswith("SCHEMA "):
            if not rest.startswith("SCHEMA - "):
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC SCHEMA line")
            sch_tail = rest[len("SCHEMA - "):]
            sch_name, sep, owner = (sch_tail[:-1], " ", "_") if sch_tail.endswith(" ") else sch_tail.rpartition(" ")
            if not sep or not owner or not sch_name:
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC SCHEMA line")
            toc_schemas.add(sch_name)
        elif rest.startswith(("TABLE DATA", "SEQUENCE SET")):
            prefix = "TABLE DATA " if rest.startswith("TABLE DATA ") else ("SEQUENCE SET " if rest.startswith("SEQUENCE SET ") else "")
            if not prefix:
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC data line")
            data_tail = rest[len(prefix):]
            ns_and_rel, sep, owner = (data_tail[:-1], " ", "_") if data_tail.endswith(" ") else data_tail.rpartition(" ")
            if not sep or not owner or " " not in ns_and_rel:
                raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC data line")
            (toc_table_data if prefix == "TABLE DATA " else toc_sequence_set).add(ns_and_rel)
        elif len(rest.split()) < 3:
            raise provenance_error("backup-toc-inconsistent", database, "unparseable TOC entry line")
    return ArchiveTocObservation(
        database=database, toc_sha256=toc_sha256, extensions=tuple(sorted(toc_extensions)),
        schemas=tuple(sorted(toc_schemas)), table_data=tuple(sorted(toc_table_data)),
        sequence_set=tuple(sorted(toc_sequence_set)), entry_count=entry_count,
    )


def parse_and_verify_toc_provenance(
    raw_toc_bytes: bytes, *, database: str, database_catalog: Mapping[str, object]
) -> ArchiveTocObservation:
    toc_obs = parse_toc_entries(raw_toc_bytes, database=database)
    installed_raw = database_catalog.get("installed_extensions")
    if not isinstance(installed_raw, list):
        raise provenance_error("backup-toc-inconsistent", database, "installed_extensions missing in catalog")
    for ext_item in installed_raw:
        if not isinstance(ext_item, Mapping) or not isinstance(ext_item.get("name"), str) or any(c in str(ext_item["name"]) for c in "\r\n"):
            raise provenance_error("backup-toc-inconsistent", database, "invalid extension entry in catalog")
    catalog_non_baseline = sorted({str(item["name"]) for item in installed_raw if str(item["name"]) != BASELINE_EXTENSION_NAME})
    toc_non_baseline = sorted(ext for ext in toc_obs.extensions if ext != BASELINE_EXTENSION_NAME)
    if catalog_non_baseline != toc_non_baseline:
        raise provenance_error("backup-toc-inconsistent", database, f"TOC extensions {toc_non_baseline} != catalog {catalog_non_baseline}")

    schemas_raw = database_catalog.get("non_system_schemas")
    if not isinstance(schemas_raw, list):
        raise provenance_error("backup-toc-inconsistent", database, "non_system_schemas missing in catalog")
    for sch_item in schemas_raw:
        if (
            not isinstance(sch_item, Mapping) or not isinstance(sch_item.get("name"), str) or not isinstance(sch_item.get("owner"), str)
            or any(c in str(sch_item["name"]) for c in "\r\n") or any(c.isspace() for c in str(sch_item["owner"]))
        ):
            raise provenance_error("backup-toc-inconsistent", database, "ambiguous schema entry in catalog")
    catalog_custom_schemas = sorted({str(item["name"]) for item in schemas_raw if str(item["name"]) != "public"})
    toc_custom_schemas = sorted(sch for sch in toc_obs.schemas if sch != "public")
    if catalog_custom_schemas != toc_custom_schemas:
        raise provenance_error("backup-toc-inconsistent", database, f"TOC schemas {toc_custom_schemas} != catalog {catalog_custom_schemas}")

    cfg_raw = database_catalog.get("extension_config_tables")
    if not isinstance(cfg_raw, list):
        raise provenance_error("backup-toc-inconsistent", database, "extension_config_tables missing in catalog")
    toc_table_data, toc_sequence_set = set(toc_obs.table_data), set(toc_obs.sequence_set)
    seen_toc_keys: dict[str, tuple[str, str]] = {}
    for item in cfg_raw:
        if not isinstance(item, Mapping):
            raise provenance_error("backup-toc-inconsistent", database, "invalid extension_config_tables entry")
        schema, table, qual, relkind = item.get("schema"), item.get("table"), item.get("qualified_table"), item.get("relkind")
        if (
            not (isinstance(schema, str) and isinstance(table, str) and isinstance(qual, str) and relkind in {"r", "S", "p"})
            or any(c in schema or c in table for c in "\r\n") or schema != schema.strip() or table != table.strip()
        ):
            raise provenance_error("backup-toc-inconsistent", database, "incomplete extension_config_tables entry")
        toc_key = f"{schema} {table}"
        if seen_toc_keys.setdefault(toc_key, (schema, table)) != (schema, table):
            raise provenance_error("backup-toc-inconsistent", database, "ambiguous extension_config_tables TOC key")
        if relkind == "S" and toc_key not in toc_sequence_set:
            raise provenance_error("backup-toc-inconsistent", database, "TOC missing SEQUENCE SET for extconfig")
        if relkind != "S" and toc_key not in toc_table_data:
            raise provenance_error("backup-toc-inconsistent", database, "TOC missing TABLE DATA for extconfig")
    return toc_obs


def observe_archive_toc(
    plan: LocalRuntimePlan, database: str, dump_path: Path,
    command_runner: CommandRunner, database_catalog: Mapping[str, object],
) -> ArchiveTocObservation:
    secret, command = runtime_postgres_password(plan), planned_pg_restore_list_command(plan)
    env = dict(os.environ, PGPASSWORD=secret)
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        raw_toc = run_bounded_popen(
            command, max_output_bytes=MAX_TOC_OUTPUT_BYTES, timeout_seconds=DEFAULT_TOC_TIMEOUT_SECONDS,
            error_code="backup-toc-inconsistent", field=database, secret=secret, env=env, stdin_path=dump_path,
        )
        return parse_and_verify_toc_provenance(raw_toc, database=database, database_catalog=database_catalog)
    try:
        with dump_path.open("rb") as input_stream:
            completed = command_runner(
                list(command), check=False, input=None, stdin=input_stream, capture_output=True, text=False, env=env
            )
    except OSError as exc:
        raise provenance_error("backup-toc-inconsistent", database, "failed to open archive for TOC listing") from exc
    if completed.returncode != 0:
        msg = redact_secret_text(decode_process_output(completed.stderr).strip(), secret) or "pg_restore TOC listing failed"
        raise provenance_error("backup-toc-inconsistent", database, msg)
    stdout_bytes = completed.stdout if isinstance(completed.stdout, bytes) else decode_process_output(completed.stdout).encode("utf-8")
    return parse_and_verify_toc_provenance(stdout_bytes, database=database, database_catalog=database_catalog)
