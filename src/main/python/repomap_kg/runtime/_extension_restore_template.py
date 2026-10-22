"""Target template1 logical baseline and creation-semantics compatibility for D9-B extension_v2.

The baseline is a bounded canonical digest over every PostgreSQL 16 database-local
catalog, compared with a clean reference the caller established on a separate
cluster of the same admitted Engine image. It is a drift detector over enumerated
catalogs under the trusted-administrator precondition, not a hostile-superuser guarantee.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime._extension_restore_qualification import (
    TARGET_TEMPLATE,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
    quote_sql_identifier,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan

# Database-local catalogs hashed row-by-row, with physical/statistics columns that
# VACUUM/ANALYZE legitimately change excluded.
BASELINE_CATALOGS: dict[str, tuple[str, ...]] = {
    "pg_aggregate": (),
    "pg_am": (),
    "pg_amop": (),
    "pg_amproc": (),
    "pg_attrdef": (),
    "pg_attribute": (),
    "pg_cast": (),
    "pg_class": (
        "relpages",
        "reltuples",
        "relallvisible",
        "relfrozenxid",
        "relminmxid",
        "relfilenode",
    ),
    "pg_collation": (),
    "pg_constraint": (),
    "pg_conversion": (),
    "pg_default_acl": (),
    "pg_depend": (),
    "pg_description": (),
    "pg_enum": (),
    "pg_event_trigger": (),
    "pg_extension": (),
    "pg_foreign_data_wrapper": (),
    "pg_foreign_server": (),
    "pg_foreign_table": (),
    "pg_index": (),
    "pg_inherits": (),
    "pg_init_privs": (),
    "pg_language": (),
    "pg_largeobject_metadata": (),
    "pg_namespace": (),
    "pg_opclass": (),
    "pg_operator": (),
    "pg_opfamily": (),
    "pg_partitioned_table": (),
    "pg_policy": (),
    "pg_proc": (),
    "pg_publication": (),
    "pg_publication_namespace": (),
    "pg_publication_rel": (),
    "pg_range": (),
    "pg_rewrite": (),
    "pg_seclabel": (),
    "pg_sequence": (),
    "pg_statistic_ext": (),
    "pg_subscription_rel": (),
    "pg_transform": (),
    "pg_trigger": (),
    "pg_ts_config": (),
    "pg_ts_config_map": (),
    "pg_ts_dict": (),
    "pg_ts_parser": (),
    "pg_ts_template": (),
    "pg_type": (),
}
# Not hashed directly: statistics are volatile; large-object data and user-mapping
# options are restricted and are covered through pg_largeobject_metadata and pg_user_mappings.
BASELINE_INDIRECT_CATALOGS = frozenset(
    {"pg_largeobject", "pg_statistic", "pg_statistic_ext_data", "pg_user_mapping"}
)
_ACL_COLUMNS = {
    "pg_namespace": "nspacl",
    "pg_class": "relacl",
    "pg_attribute": "attacl",
    "pg_proc": "proacl",
    "pg_type": "typacl",
    "pg_language": "lanacl",
    "pg_largeobject_metadata": "lomacl",
    "pg_foreign_data_wrapper": "fdwacl",
    "pg_foreign_server": "srvacl",
    "pg_default_acl": "defaclacl",
    "pg_init_privs": "initprivs",
}
_INFORMATION_SCHEMA_DATA = ("sql_features", "sql_implementation_info", "sql_parts", "sql_sizing")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
TEMPLATE_ATTRIBUTES_SQL = (
    "SELECT coalesce((SELECT json_build_object('datname', d.datname, 'encoding', pg_encoding_to_char(d.encoding), "
    "'datcollate', d.datcollate, 'datctype', d.datctype, 'datlocprovider', d.datlocprovider::text, "
    "'daticulocale', COALESCE(to_jsonb(d)->>'daticulocale', to_jsonb(d)->>'datlocale'), 'datcollversion', to_jsonb(d)->>'datcollversion', "
    f"'datistemplate', d.datistemplate, 'datallowconn', d.datallowconn) FROM pg_database d WHERE d.datname = '{TARGET_TEMPLATE}'), 'null'::json)::text;"
)


def _acl_json(column: str) -> str:
    return (
        f"CASE WHEN t.{column} IS NULL THEN 'default' ELSE coalesce((SELECT jsonb_agg(jsonb_build_array(a.grantor, a.grantee, "
        f"a.privilege_type, a.is_grantable) ORDER BY a.grantor, a.grantee, a.privilege_type, a.is_grantable) FROM aclexplode(t.{column}) a), "
        "'[]'::jsonb)::text END"
    )


def template_baseline_sql() -> str:
    """Return the read-only canonical baseline query; its output is one small JSON object."""
    parts = []
    for catalog, volatile in sorted(BASELINE_CATALOGS.items()):
        acl = _ACL_COLUMNS.get(catalog)
        dropped = "".join(f" - '{key}'" for key in (*volatile, *((acl,) if acl else ())))
        expr = f"(to_jsonb(t){dropped})::text" + (f" || '|' || {_acl_json(acl)}" if acl else "")
        parts.append(f"SELECT '{catalog}' AS c, {expr} AS l FROM pg_catalog.{catalog} t")
    parts.extend(
        f"SELECT 'information_schema.{v}', to_jsonb(t)::text FROM information_schema.{v} t"
        for v in _INFORMATION_SCHEMA_DATA
    )
    parts.append(
        "SELECT 'pg_user_mappings', jsonb_build_array(t.srvid, t.umuser)::text FROM pg_catalog.pg_user_mappings t"
    )
    return (
        "/* repomap_d9b_template_baseline */ WITH b(c, l) AS ("
        + " UNION ALL ".join(parts)
        + ") SELECT json_build_object("
        "'rows', (SELECT count(*) FROM b), 'sha256', (SELECT encode(sha256(convert_to(coalesce(string_agg(c || ':' || l, E'\\n' "
        "ORDER BY c COLLATE \"C\", l COLLATE \"C\"), ''), 'UTF8')), 'hex') FROM b), 'catalogs', (SELECT json_agg(relname::text "
        "ORDER BY relname::text COLLATE \"C\") FROM pg_catalog.pg_class WHERE relnamespace = 'pg_catalog'::regnamespace "
        "AND relkind = 'r' AND NOT relisshared))::text;"
    )


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def parse_template_baseline(raw: str, *, field: str) -> str:
    """Validate catalog-set completeness and return the baseline SHA-256."""
    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise _err(
            "restore-template-baseline-unqualified",
            field,
            "template baseline observation returned invalid JSON",
        ) from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("sha256"), str)
        or not _SHA256_HEX_RE.match(payload["sha256"])
    ):
        raise _err(
            "restore-template-baseline-unqualified",
            field,
            "template baseline observation is malformed",
        )
    catalogs = payload.get("catalogs")
    if (
        not isinstance(catalogs, list)
        or set(catalogs) != set(BASELINE_CATALOGS) | BASELINE_INDIRECT_CATALOGS
    ):
        raise _err(
            "restore-template-baseline-unqualified",
            field,
            "database-local catalog set differs from the enumerated baseline",
        )
    return str(payload["sha256"])


def observe_template_baseline_digest(
    plan: LocalRuntimePlan, database: str, command_runner: CommandRunner
) -> str:
    """Observe a database's logical baseline digest through one read-only bounded query."""
    raw = run_bounded_ext_command(
        plan,
        planned_psql_command(
            plan,
            database,
            "-X",
            "-A",
            "-t",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            template_baseline_sql(),
        ),
        command_runner,
        field=f"{database} logical baseline",
        error_code="restore-template-baseline-unqualified",
    )
    return parse_template_baseline(decode_process_output(raw), field=database)


def observe_template_attributes(
    plan: LocalRuntimePlan, command_runner: CommandRunner
) -> dict[str, object]:
    raw = run_bounded_ext_command(
        plan,
        planned_psql_command(
            plan,
            plan.maintenance_database,
            "-X",
            "-A",
            "-t",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            TEMPLATE_ATTRIBUTES_SQL,
        ),
        command_runner,
        field="template1 attributes",
        error_code="restore-template-baseline-unqualified",
    )
    try:
        row = json.loads(decode_process_output(raw).strip())
    except json.JSONDecodeError as exc:
        raise _err(
            "restore-template-baseline-unqualified",
            TARGET_TEMPLATE,
            "template attributes returned invalid JSON",
        ) from exc
    if (
        not isinstance(row, dict)
        or row.get("datname") != TARGET_TEMPLATE
        or row.get("datistemplate") is not True
        or row.get("datallowconn") is not True
    ):
        raise _err(
            "restore-template-baseline-unqualified",
            TARGET_TEMPLATE,
            "template1 is absent, not a template, or not observable",
        )
    return row


def _sql_literal(value: object, *, database: str, field: str) -> str:
    if not isinstance(value, str) or not value or any(c in value for c in "\x00\n\r"):
        raise _err(
            "restore-creation-semantics-incompatible",
            database,
            f"invalid creation_semantics.{field}",
        )
    return "'" + value.replace("'", "''") + "'"


def build_create_database_sql(
    database: str, creation_semantics: Mapping[str, object], *, template_row: Mapping[str, object]
) -> str:
    """Build CREATE DATABASE from template1 after proving source locale facts equal template1's."""
    keys = ("encoding", "datcollate", "datctype", "datlocprovider")
    provider = creation_semantics.get("datlocprovider")
    if provider not in ("c", "i") or any(
        not isinstance(creation_semantics.get(k), str) or not creation_semantics.get(k)
        for k in keys
    ):
        raise _err(
            "restore-creation-semantics-incompatible",
            database,
            "source creation_semantics missing or unsupported locale/encoding facts",
        )
    compared = (*keys, "daticulocale") if provider == "i" else keys
    if any(creation_semantics.get(k) != template_row.get(k) for k in compared):
        raise _err(
            "restore-creation-semantics-incompatible",
            database,
            "source locale/encoding facts differ from the qualified template1 baseline",
        )
    src_ver, tpl_ver = creation_semantics.get("datcollversion"), template_row.get("datcollversion")
    if (src_ver is None) != (tpl_ver is None) or src_ver != tpl_ver:
        raise _err(
            "restore-creation-semantics-incompatible",
            database,
            "source collation version does not match the target template1",
        )
    db_ident = quote_sql_identifier(database)
    enc = _sql_literal(creation_semantics["encoding"], database=database, field="encoding")
    col = _sql_literal(creation_semantics["datcollate"], database=database, field="datcollate")
    ctype = _sql_literal(creation_semantics["datctype"], database=database, field="datctype")
    if provider == "i":
        icu = _sql_literal(
            creation_semantics.get("daticulocale"), database=database, field="daticulocale"
        )
        return f"CREATE DATABASE {db_ident} WITH TEMPLATE {TARGET_TEMPLATE} ENCODING {enc} LOCALE_PROVIDER icu LC_COLLATE {col} LC_CTYPE {ctype} ICU_LOCALE {icu};"
    return f"CREATE DATABASE {db_ident} WITH TEMPLATE {TARGET_TEMPLATE} ENCODING {enc} LOCALE_PROVIDER libc LC_COLLATE {col} LC_CTYPE {ctype};"
