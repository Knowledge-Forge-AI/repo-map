"""Whole-set target preflight before any CREATE DATABASE for D9-B extension_v2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.runtime._backup_observation import _normalize_server_provenance
from common_lore_index.runtime._backup_provenance import (
    _STDLIB_SUBPROCESS_RUN,
    DEFAULT_TOC_TIMEOUT_SECONDS,
    MAX_TOC_OUTPUT_BYTES,
)
from common_lore_index.runtime._backup_support import require_backup_restore_supported
from common_lore_index.runtime._extension_restore_custody import (
    refuse_outstanding_restore_state,
    retain_unknown_commands,
)
from common_lore_index.runtime._extension_restore_exec import bound_exec_custody
from common_lore_index.runtime._extension_restore_native import (
    observe_custodied_client_identities,
    run_bounded_ext_command,
)
from common_lore_index.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy,
    TrustedExtensionRule,
    resolve_extension_restore_policy,
)
from common_lore_index.runtime._extension_restore_qualification import (
    TARGET_TEMPLATE,
    engine_image_content_id,
)
from common_lore_index.runtime._extension_restore_target import (
    BASELINE_RUNTIME_ROLES,
    ROLES_SQL,
    admit_database_extensions,
    observe_engine_identity,
    query_maintenance_json,
    verify_server_qualification,
)
from common_lore_index.runtime._extension_restore_template import (
    build_create_database_sql,
    observe_template_attributes,
    observe_template_baseline_digest,
)
from common_lore_index.runtime._extension_restore_toc import (
    DerivedTocPlan,
    build_derived_toc_plan,
)
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    planned_pg_restore_list_command,
)
from common_lore_index.runtime.backup_inspection import _run_pg_restore_list_bytes
from common_lore_index.runtime.backup_manifests import (
    select_dump_file_for_database,
    verify_dump_file_checksum,
)
from common_lore_index.runtime.backup_records import (
    LocalDbBackupError,
    RuntimeContainerMetadata,
)
from common_lore_index.runtime.database_role_contract import (
    read_role_secrets,
)
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan

TARGET_PREFLIGHT_SQL = f"""
/* repomap_d9b_target_preflight */
SELECT json_build_object(
  'server_provenance', json_build_object(
    'server_version_num', current_setting('server_version_num')::int,
    'catalog_version_no', (SELECT catalog_version_no::bigint FROM pg_control_system()),
    'system_identifier', (SELECT system_identifier::text FROM pg_control_system()),
    'server_version', current_setting('server_version'), 'version_string', version(),
    'os_arch_abi', COALESCE(NULLIF(substring(version() FROM ' on ([^,]+)'), ''), 'unavailable'),
    'compile_abi', (SELECT json_build_object('max_data_alignment', max_data_alignment, 'database_block_size', database_block_size,
      'float8_pass_by_value', float8_pass_by_value, 'data_page_checksum_version', data_page_checksum_version) FROM pg_control_init()),
    'shared_preload_libraries', coalesce((SELECT json_agg(btrim(x) ORDER BY btrim(x))
      FROM unnest(string_to_array(current_setting('shared_preload_libraries'), ',')) AS x WHERE btrim(x) <> ''), '[]'::json)
  ),
  'current_role', (SELECT json_build_object('name', rolname, 'rolsuper', rolsuper, 'rolcreatedb', rolcreatedb) FROM pg_roles WHERE rolname = current_user),
  'existing_databases', coalesce((SELECT json_agg(datname ORDER BY datname) FROM pg_database), '[]'::json),
  'roles', ({ROLES_SQL}),
  'available_extension_versions', coalesce((SELECT json_agg(json_build_object(
    'name', aev.name, 'version', aev.version, 'superuser', aev.superuser, 'trusted', aev.trusted, 'relocatable', aev.relocatable,
    'schema', aev.schema, 'requires', coalesce(to_json(aev.requires), '[]'::json)
  ) ORDER BY aev.name, aev.version) FROM pg_available_extension_versions aev), '[]'::json)
)::text;
""".strip()


@dataclass(frozen=True)
class DatabaseRestorePreflight:
    """Validated target preflight plan for one database in an extension_v2 restore."""

    database: str
    database_role: str
    dump_path: Path
    dump_sha256: str
    create_database_sql: str
    derived_toc_plan: DerivedTocPlan
    ordered_extensions: tuple[tuple[dict[str, object], TrustedExtensionRule], ...]
    database_catalog: Mapping[str, object]


@dataclass(frozen=True)
class ExtensionRestoreSetPreflight:
    """Validated whole-set target preflight before any CREATE DATABASE."""

    policy: TrustedExtensionRestorePolicy
    container: RuntimeContainerMetadata
    databases: Mapping[str, DatabaseRestorePreflight]
    target_system_identifier: str
    engine_image_id: str
    template_baseline_sha256: str


def _preflight_err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def _list_archive_toc(plan: LocalRuntimePlan, dump_path: Path, command_runner: CommandRunner) -> bytes:
    """List one archive TOC with the existing TOC limits.

    The stdlib path runs the container ``pg_restore -l`` under the invocation's
    container-side custody; a caller-supplied runner keeps the shared listing path.
    """
    command = planned_pg_restore_list_command(plan)
    if command_runner is not _STDLIB_SUBPROCESS_RUN:
        return _run_pg_restore_list_bytes(plan, dump_path, command, command_runner)
    return run_bounded_ext_command(
        plan,
        command,
        command_runner,
        field=dump_path.name,
        error_code="backup-toc-inconsistent",
        max_output_bytes=MAX_TOC_OUTPUT_BYTES,
        timeout_seconds=DEFAULT_TOC_TIMEOUT_SECONDS,
        stdin_path=dump_path,
    )


def preflight_extension_v2_restore_set(
    plan: LocalRuntimePlan,
    manifest: Mapping[str, Any],
    *,
    databases: Sequence[str],
    dumps: Mapping[str, Path],
    container: RuntimeContainerMetadata,
    command_runner: CommandRunner,
    policy: TrustedExtensionRestorePolicy | None,
    require_quiescence: bool,
    coordinated: bool,
) -> ExtensionRestoreSetPreflight:
    del container  # the Engine identity is re-observed here rather than trusted from the caller
    resolved = resolve_extension_restore_policy(policy)
    field_label = "coordinated restore" if coordinated else databases[0]
    refuse_outstanding_restore_state(plan, field_label)
    if coordinated:
        require_backup_restore_supported(
            manifest,
            database=None,
            require_quiescence=require_quiescence,
            target="coordinated restore",
            extension_restore_policy=resolved,
        )
    for db_name in databases:
        require_backup_restore_supported(
            manifest,
            database=db_name,
            require_quiescence=require_quiescence,
            target=db_name,
            extension_restore_policy=resolved,
        )
    if not resolved.allow_extension_v2:
        raise _preflight_err(
            "backup-extension-restore-unsupported",
            field_label,
            "extension_v2 restore requires an admitted trusted policy",
        )
    try:
        read_role_secrets(plan.env_file)
    except Exception as exc:
        raise _preflight_err(
            "restore-role-secrets-unavailable",
            str(plan.env_file),
            "baseline database role secrets are missing",
        ) from exc

    observed_container = observe_engine_identity(plan, command_runner, resolved, field=field_label)
    # Every later preflight container command runs by this immutable container ID; an
    # unsettled one is kept in a durable record that refuses later attempts.
    with bound_exec_custody(observed_container.container_id) as custody:
        try:
            result = _preflight_observed_target(
                plan,
                manifest,
                resolved,
                observed_container,
                databases=databases,
                dumps=dumps,
                command_runner=command_runner,
                field_label=field_label,
                coordinated=coordinated,
            )
        except BaseException as primary:
            retained = retain_unknown_commands(plan, custody, primary, field_label)
            if retained is None or retained is primary:
                raise
            raise retained from primary
        unsettled = retain_unknown_commands(plan, custody, None, field_label)
        if unsettled is not None:
            raise unsettled
        return result


def _preflight_observed_target(
    plan: LocalRuntimePlan,
    manifest: Mapping[str, Any],
    resolved: TrustedExtensionRestorePolicy,
    observed_container: RuntimeContainerMetadata,
    *,
    databases: Sequence[str],
    dumps: Mapping[str, Path],
    command_runner: CommandRunner,
    field_label: str,
    coordinated: bool,
) -> ExtensionRestoreSetPreflight:
    image_id = str(observed_container.image_id)
    art = manifest.get("artifact_provenance")
    src_image = (
        engine_image_content_id(art.get("container_image_id")) if isinstance(art, Mapping) else None
    )
    if (
        src_image is None
        or src_image not in resolved.artifact_qualification.allowed_engine_image_ids
    ):
        raise _preflight_err(
            "restore-target-artifact-unqualified",
            field_label,
            "source backup Engine image content ID is missing or not admitted by policy",
        )
    expected_baseline = resolved.artifact_qualification.template_baseline_for(image_id)
    if expected_baseline is None:
        raise _preflight_err(
            "restore-template-baseline-unqualified",
            field_label,
            "no clean template1 reference is bound to the target Engine image",
        )

    live = query_maintenance_json(
        plan, TARGET_PREFLIGHT_SQL, command_runner, field="target cluster preflight"
    )
    if not isinstance(live, dict):
        raise _preflight_err(
            "restore-target-preflight-failed",
            plan.maintenance_database,
            "target cluster preflight root must be an object",
        )
    clients = observe_custodied_client_identities(plan, command_runner)
    target_server = _normalize_server_provenance(
        live.get("server_provenance"), database=plan.maintenance_database, observed_clients=clients
    )
    verify_server_qualification(
        manifest.get("server_provenance"), target_server, resolved, field=field_label
    )
    cur_role = live.get("current_role")
    if not isinstance(cur_role, Mapping) or not (
        cur_role.get("rolsuper") is True or cur_role.get("rolcreatedb") is True
    ):
        raise _preflight_err(
            "restore-lifecycle-privilege-insufficient",
            plan.user,
            "lifecycle role lacks database creation privilege",
        )
    present = [
        db for db in databases if db in {str(d) for d in (live.get("existing_databases") or [])}
    ]
    if present:
        if coordinated:
            raise _preflight_err(
                "coordinated-restore-target-exists",
                "coordinated restore",
                "restore requires every configured target database to be absent",
            )
        raise _preflight_err(
            "database-already-exists",
            present[0],
            "target database already exists; replacement or restore-over-existing is not implemented and would require a future backup-first phase",
        )
    roles_by_name = {
        str(r["rolname"]): r
        for r in (live.get("roles") or [])
        if isinstance(r, Mapping) and isinstance(r.get("rolname"), str)
    }
    for base_role in BASELINE_RUNTIME_ROLES & set(roles_by_name):
        if (
            type(roles_by_name[base_role].get("owned_objects_count")) is not int
            or roles_by_name[base_role]["owned_objects_count"] != 0
        ):
            raise _preflight_err(
                "restore-principal-privilege-invalid",
                base_role,
                f"baseline runtime role {base_role!r} already owns objects",
            )

    template_row = observe_template_attributes(plan, command_runner)
    if observe_template_baseline_digest(plan, TARGET_TEMPLATE, command_runner) != expected_baseline:
        raise _preflight_err(
            "restore-template-baseline-mismatch",
            field_label,
            "target template1 differs from the clean reference bound to its Engine image",
        )

    catalogs = manifest.get("database_catalogs")
    bindings = art.get("archive_bindings") if isinstance(art, Mapping) else None
    toc_sha_by_db = {
        str(b.get("database")): str(b.get("toc_sha256"))
        for b in (bindings if isinstance(bindings, list) else [])
        if isinstance(b, Mapping) and isinstance(b.get("toc_sha256"), str)
    }
    if not isinstance(catalogs, Mapping):
        raise _preflight_err(
            "backup-manifest-invalid", "database_catalogs", "missing database_catalogs"
        )
    db_preflights: dict[str, DatabaseRestorePreflight] = {}
    for db_name in databases:
        dump_file = select_dump_file_for_database(manifest, db_name)
        verify_dump_file_checksum(dumps[db_name], dump_file)
        db_cat = catalogs.get(db_name)
        cs_raw = db_cat.get("creation_semantics") if isinstance(db_cat, Mapping) else None
        expected_toc_sha = toc_sha_by_db.get(db_name)
        if (
            not isinstance(db_cat, Mapping)
            or not isinstance(cs_raw, Mapping)
            or not isinstance(expected_toc_sha, str)
            or len(expected_toc_sha) != 64
        ):
            raise _preflight_err(
                "backup-manifest-invalid",
                db_name,
                "missing database catalog, creation_semantics or archive_bindings.toc_sha256",
            )
        create_sql = build_create_database_sql(db_name, cs_raw, template_row=template_row)
        raw_toc = _list_archive_toc(plan, dumps[db_name], command_runner)
        toc_plan = build_derived_toc_plan(
            raw_toc, database=db_name, database_catalog=db_cat, expected_toc_sha256=expected_toc_sha
        )
        db_preflights[db_name] = DatabaseRestorePreflight(
            database=db_name,
            database_role=str(db_cat.get("database_role") or ""),
            dump_path=dumps[db_name],
            dump_sha256=str(dump_file["sha256"]),
            create_database_sql=create_sql,
            derived_toc_plan=toc_plan,
            database_catalog=db_cat,
            ordered_extensions=admit_database_extensions(
                plan, db_name, db_cat, resolved, live, roles_by_name, command_runner
            ),
        )
    system_identifier = target_server.get("system_identifier")
    if not isinstance(system_identifier, str) or not system_identifier:
        raise _preflight_err(
            "restore-target-preflight-failed",
            plan.maintenance_database,
            "target system identifier was not observed",
        )
    return ExtensionRestoreSetPreflight(
        policy=resolved,
        container=observed_container,
        databases=db_preflights,
        target_system_identifier=system_identifier,
        engine_image_id=image_id,
        template_baseline_sha256=expected_baseline,
    )
