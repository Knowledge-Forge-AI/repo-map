"""Per-database extension installation and post-restore verification under held D9-B custody."""

from __future__ import annotations

from collections.abc import Sequence

from common_lore_index.runtime._backup_observation import observe_database_provenance
from common_lore_index.runtime._extension_restore_custody import (
    DatabaseCreationIntent,
    RestoreLifecycleAuthority,
)
from common_lore_index.runtime._extension_restore_grants import (
    ENRICHMENT_SCHEMA,
    reconcile_optional_grants,
    verify_optional_privileges,
)
from common_lore_index.runtime._extension_restore_native import run_bounded_ext_command
from common_lore_index.runtime._extension_restore_postcheck import (
    verify_optional_row_provenance,
    verify_zero_ownership,
)
from common_lore_index.runtime._extension_restore_preflight import (
    DatabaseRestorePreflight,
    ExtensionRestoreSetPreflight,
)
from common_lore_index.runtime._extension_restore_target import (
    check_custom_principals,
    observe_roles,
    verify_extension_artifact,
)
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
    planned_psql_stdin_command,
    quote_sql_identifier,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
)
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from common_lore_index.runtime.provisioning import require_graph_schema_ready


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def _lit(value: str) -> str:
    if any(c in value for c in "\x00\n\r"):
        raise ValueError("SQL literal cannot contain NUL or newline characters")
    return "'" + value.replace("'", "''") + "'"


def _psql_scalar(
    plan: LocalRuntimePlan, db: str, sql: str, runner: CommandRunner, label: str
) -> str:
    return decode_process_output(
        run_bounded_ext_command(
            plan, planned_psql_command(plan, db, "-X", "-tAc", sql), runner, field=label
        )
    ).strip()


def _psql_stdin(
    plan: LocalRuntimePlan, db: str, stmts: Sequence[str], runner: CommandRunner, label: str
) -> None:
    run_bounded_ext_command(
        plan,
        planned_psql_stdin_command(plan, db),
        runner,
        field=label,
        input_bytes="\n".join(stmts).encode("utf-8"),
    )


def require_custody(
    authority: RestoreLifecycleAuthority, intent: DatabaseCreationIntent, seam: str
) -> None:
    if not authority.verify(intent):
        raise _err(
            "restore-target-ownership-mismatch",
            intent.database,
            f"held target identity or lock changed before {seam}",
        )


def install_extensions(
    plan: LocalRuntimePlan,
    authority: RestoreLifecycleAuthority,
    intent: DatabaseCreationIntent,
    db_pre: DatabaseRestorePreflight,
    runner: CommandRunner,
) -> None:
    created_schemas: set[str] = set()
    for ext_item, rule in db_pre.ordered_extensions:
        name, ver, schema, owner = (
            str(ext_item["name"]),
            str(ext_item["version"]),
            str(ext_item["schema"]),
            str(ext_item["owner"]),
        )
        require_custody(authority, intent, f"installing {name}")
        verify_extension_artifact(plan, db_pre.database, name, ver, rule, runner)
        stmts = ["BEGIN;"]
        if schema not in ("public", "pg_catalog") and schema not in created_schemas:
            stmts.append(
                f"CREATE SCHEMA {quote_sql_identifier(schema)} AUTHORIZATION {quote_sql_identifier(owner)};"
            )
            created_schemas.add(schema)
        stmts.append(
            f"CREATE EXTENSION {quote_sql_identifier(name)} WITH SCHEMA {quote_sql_identifier(schema)} VERSION {_lit(ver)};"
        )
        if name not in db_pre.derived_toc_plan.extension_comments:
            stmts.append(f"COMMENT ON EXTENSION {quote_sql_identifier(name)} IS NULL;")
        _psql_stdin(plan, db_pre.database, [*stmts, "COMMIT;"], runner, f"extension install {name}")
        verify_sql = (
            "SELECT e.extversion || ':' || n.nspname || ':' || pg_get_userbyid(e.extowner) || ':' || coalesce(cardinality(e.extconfig), 0)::text "
            f"FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = {_lit(name)};"
        )
        if (
            _psql_scalar(
                plan, db_pre.database, verify_sql, runner, f"extension catalog verify {name}"
            )
            != f"{ver}:{schema}:{owner}:0"
        ):
            raise _err(
                "restore-extension-verification-failed",
                db_pre.database,
                f"installed extension {name!r} catalog state does not match the recorded facts",
            )
        _psql_scalar(
            plan,
            db_pre.database,
            rule.readiness_probe_sql,
            runner,
            f"extension readiness probe {name}",
        )


def verify_restored_database(
    plan: LocalRuntimePlan,
    authority: RestoreLifecycleAuthority,
    intent: DatabaseCreationIntent,
    set_pre: ExtensionRestoreSetPreflight,
    db_pre: DatabaseRestorePreflight,
    runner: CommandRunner,
) -> None:
    db = db_pre.database
    raw_schemas = db_pre.database_catalog.get("non_system_schemas")
    expected_schemas = {
        str(s.get("name"))
        for s in (raw_schemas if isinstance(raw_schemas, list) else [])
        if isinstance(s, dict)
    }
    checked_roles = {READ_STATUS_ROLE, REFRESH_PUBLICATION_ROLE, COORDINATOR_CONTROL_ROLE}
    optional = [
        rule.optional_capability
        for _item, rule in db_pre.ordered_extensions
        if rule.optional_capability is not None
    ]
    for opt in optional:
        check_custom_principals(
            observe_roles(plan, runner), opt, lifecycle_user=plan.user, field=db
        )
        has_enrichment = (
            ENRICHMENT_SCHEMA in opt.application_schemas and ENRICHMENT_SCHEMA in expected_schemas
        )
        require_custody(authority, intent, f"optional grant reconciliation {opt.capability_id}")
        reconcile_optional_grants(plan, db, opt, runner, has_enrichment=has_enrichment)
        verify_optional_privileges(plan, db, opt, runner, has_enrichment=has_enrichment)
        checked_roles.update(
            r for r in (opt.enrichment_reader_role, opt.enrichment_writer_role) if r
        )
        if has_enrichment:
            verify_optional_row_provenance(plan, db, runner)
    if db_pre.database_role == "graph":
        require_graph_schema_ready(plan, db, runner)
    post_cat = observe_database_provenance(
        plan, db, runner, extension_restore_policy=set_pre.policy
    ).database_catalog
    if post_cat.get("installed_extensions") != db_pre.database_catalog.get("installed_extensions"):
        raise _err(
            "restore-postcheck-extension-mismatch",
            db,
            "restored extension catalog metadata does not match backup manifest",
        )
    if post_cat.get("extension_dependency_summary") != db_pre.database_catalog.get(
        "extension_dependency_summary"
    ):
        raise _err(
            "restore-postcheck-dependency-mismatch",
            db,
            "restored extension dependent objects do not match backup manifest",
        )
    for _item, rule in db_pre.ordered_extensions:
        c_sql = f"SELECT CASE WHEN obj_description(oid, 'pg_extension') IS NOT NULL THEN '1' ELSE '0' END FROM pg_extension WHERE extname = {_lit(rule.name)};"
        expected = "1" if rule.name in db_pre.derived_toc_plan.extension_comments else "0"
        if (
            _psql_scalar(plan, db, c_sql, runner, f"post-restore comment check {rule.name}")
            != expected
        ):
            raise _err(
                "restore-postcheck-extension-mismatch",
                db,
                f"restored extension {rule.name!r} comment state does not match the archive",
            )
        _psql_scalar(
            plan, db, rule.readiness_probe_sql, runner, f"post-restore readiness probe {rule.name}"
        )
    verify_zero_ownership(plan, db, sorted(checked_roles), runner)
