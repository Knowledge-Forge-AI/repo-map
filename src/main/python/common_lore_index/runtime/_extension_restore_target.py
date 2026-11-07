"""Observed target principals, Engine identity, server qualification and extension admission for D9-B."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from common_lore_index.runtime._backup_operations import inspect_owned_postgres_container
from common_lore_index.runtime._backup_provenance import BASELINE_EXTENSION_NAME
from common_lore_index.runtime._extension_restore_native import run_bounded_ext_command
from common_lore_index.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy,
    TrustedExtensionRule,
    TrustedOptionalCapabilityContract,
)
from common_lore_index.runtime._extension_restore_qualification import (
    SOURCE_CLIENT_KEYS,
    TARGET_CLIENT_KEYS,
    engine_image_content_id,
    qualify_server_provenance,
    registry_manifest_digest,
)
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    container_internal_enabled,
    decode_process_output,
    planned_psql_command,
)
from common_lore_index.runtime.backup_records import (
    LocalDbBackupError,
    RuntimeContainerMetadata,
)
from common_lore_index.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
)
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan


def _preflight_err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


BASELINE_RUNTIME_ROLES = frozenset(
    {READ_STATUS_ROLE, REFRESH_PUBLICATION_ROLE, COORDINATOR_CONTROL_ROLE}
)


_PRINCIPAL_FLAGS = (
    "rolsuper",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "rolbypassrls",
    "rolinherit",
)


_PRINCIPAL_COUNTS = ("owned_objects_count", "member_of_count", "members_count")


ROLES_SQL = (
    "SELECT coalesce((SELECT json_agg(json_build_object('rolname', r.rolname, 'rolcanlogin', r.rolcanlogin, 'rolsuper', r.rolsuper, "
    "'rolcreatedb', r.rolcreatedb, 'rolcreaterole', r.rolcreaterole, 'rolinherit', r.rolinherit, 'rolreplication', r.rolreplication, "
    "'rolbypassrls', r.rolbypassrls, 'owned_objects_count', (SELECT count(*)::int FROM pg_shdepend s WHERE s.refclassid = 'pg_authid'::regclass "
    "AND s.refobjid = r.oid AND s.deptype = 'o'), 'member_of_count', (SELECT count(*)::int FROM pg_auth_members m WHERE m.member = r.oid), "
    "'members_count', (SELECT count(*)::int FROM pg_auth_members m WHERE m.roleid = r.oid)) ORDER BY r.rolname) FROM pg_roles r), '[]'::json)"
)


_EXT_ARTIFACT_PROBE_SH = (
    'SHAREDIR="$(pg_config --sharedir)/extension"; PKGLIBDIR="$(pg_config --pkglibdir)"; CTRL="$SHAREDIR/$1.control"; SCRIPT="$SHAREDIR/$1--$2.sql"; '
    'test -f "$CTRL" && test -f "$SCRIPT"; C_SHA="$(sha256sum "$CTRL" | awk \'{print $1}\')"; S_SHA="$(sha256sum "$SCRIPT" | awk \'{print $1}\')"; '
    'MOD="$(sed -n "s/^[[:space:]]*module_pathname[[:space:]]*=[[:space:]]*\x27\\$libdir\\/\\([^\x27]*\\)\x27.*/\\1/p" "$CTRL" | head -n 1)"; '
    'if [ -z "$MOD" ]; then MOD="$(sed -n "s/.*\x27\\$libdir\\/\\([^\x27]*\\)\x27.*/\\1/p" "$SCRIPT" | head -n 1)"; fi; '
    'if [ -n "$MOD" ]; then test -f "$PKGLIBDIR/$MOD.so" && L_SHA="$(sha256sum "$PKGLIBDIR/$MOD.so" | awk \'{print $1}\')"; else L_SHA="none"; fi; '
    'printf "%s:%s:%s\\n" "$C_SHA" "$S_SHA" "$L_SHA"'
)


def query_maintenance_json(
    plan: LocalRuntimePlan, sql: str, command_runner: CommandRunner, *, field: str
) -> Any:
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
            sql,
        ),
        command_runner,
        field=field,
    )
    try:
        return json.loads(decode_process_output(raw).strip())
    except json.JSONDecodeError as exc:
        raise _preflight_err(
            "restore-target-preflight-failed",
            plan.maintenance_database,
            f"{field} returned invalid JSON",
        ) from exc


def observe_roles(
    plan: LocalRuntimePlan, command_runner: CommandRunner
) -> dict[str, Mapping[str, Any]]:
    rows = query_maintenance_json(
        plan, f"SELECT ({ROLES_SQL})::text;", command_runner, field="cluster principal observation"
    )
    return {
        str(r["rolname"]): r
        for r in (rows if isinstance(rows, list) else [])
        if isinstance(r, Mapping) and isinstance(r.get("rolname"), str)
    }


def check_custom_principals(
    roles_by_name: Mapping[str, Mapping[str, Any]],
    opt: TrustedOptionalCapabilityContract,
    *,
    lifecycle_user: str,
    field: str,
) -> None:
    """Require every cluster-wide privilege, both-direction membership and zero-ownership fact."""
    reader, writer = opt.enrichment_reader_role, opt.enrichment_writer_role
    reserved = {lifecycle_user} | BASELINE_RUNTIME_ROLES
    if not reader or not writer or reader == writer or reader in reserved or writer in reserved:
        raise _preflight_err(
            "restore-principal-privilege-invalid",
            field,
            "reader and writer roles must be distinct custom principals",
        )
    for role in (reader, writer):
        info = roles_by_name.get(role)
        if info is None:
            raise _preflight_err(
                "restore-custom-principal-missing",
                field,
                f"required custom principal {role!r} is missing on target",
            )
        if (
            info.get("rolcanlogin") is not True
            or any(info.get(k) is not False for k in _PRINCIPAL_FLAGS)
            or any(type(info.get(k)) is not int or info.get(k) != 0 for k in _PRINCIPAL_COUNTS)
        ):
            raise _preflight_err(
                "restore-principal-privilege-invalid",
                field,
                f"custom principal {role!r} violates least-privilege, login, membership or zero-ownership",
            )


def observe_engine_identity(
    plan: LocalRuntimePlan,
    command_runner: CommandRunner,
    policy: TrustedExtensionRestorePolicy,
    *,
    field: str,
) -> RuntimeContainerMetadata:
    """Inspect the owned container and require an admitted Engine content ID (never ``Config.Image``)."""
    container = inspect_owned_postgres_container(plan, command_runner)
    qual = policy.artifact_qualification
    image_id = engine_image_content_id(container.image_id)
    if (
        container_internal_enabled()
        or image_id is None
        or image_id not in qual.allowed_engine_image_ids
    ):
        raise _preflight_err(
            "restore-target-artifact-unqualified",
            field,
            "target Engine image content ID is missing or not admitted by policy",
        )
    if qual.allowed_registry_manifest_digests:
        raw = run_bounded_ext_command(
            plan,
            [
                plan.container_runtime,
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                image_id,
            ],
            command_runner,
            field="target registry manifest digests",
            error_code="restore-target-artifact-unqualified",
            max_output_bytes=65536,
        )
        try:
            observed = {
                registry_manifest_digest(d)
                for d in json.loads(decode_process_output(raw).strip() or "null") or ()
            }
        except (json.JSONDecodeError, TypeError) as exc:
            raise _preflight_err(
                "restore-target-artifact-unqualified",
                field,
                "target RepoDigests could not be observed",
            ) from exc
        if not observed & set(qual.allowed_registry_manifest_digests):
            raise _preflight_err(
                "restore-target-artifact-unqualified",
                field,
                "target image has no admitted registry manifest digest",
            )
    return container


def verify_extension_artifact(
    plan: LocalRuntimePlan,
    db_name: str,
    ext_name: str,
    ext_ver: str,
    rule: TrustedExtensionRule,
    command_runner: CommandRunner,
) -> None:
    script_args = ["sh", "-euc", _EXT_ARTIFACT_PROBE_SH, "sh", ext_name, ext_ver]
    cmd = (
        script_args
        if container_internal_enabled()
        else [plan.container_runtime, "exec", "-i", plan.identity.postgres_container, *script_args]
    )
    out = decode_process_output(
        run_bounded_ext_command(
            plan,
            cmd,
            command_runner,
            field=db_name,
            error_code="restore-extension-artifact-unavailable",
            max_output_bytes=4096,
            timeout_seconds=10.0,
        )
    ).strip()
    if out.count(":") != 2:
        raise _preflight_err(
            "restore-extension-artifact-unavailable",
            db_name,
            f"extension {ext_name}=={ext_ver} control/script/library artifacts could not be verified",
        )
    ctrl_sha, script_sha, lib_sha = (part.strip().lower() for part in out.split(":", 2))
    expected_lib = rule.library_sha256.lower() if rule.library_sha256 is not None else "none"
    if (
        ctrl_sha != rule.control_sha256.lower()
        or script_sha != rule.script_sha256.lower()
        or lib_sha != expected_lib
    ):
        raise _preflight_err(
            "restore-target-artifact-unqualified",
            db_name,
            f"extension {ext_name}=={ext_ver} artifact digest does not match trusted policy",
        )


def verify_server_qualification(
    source: object,
    target: Mapping[str, object],
    policy: TrustedExtensionRestorePolicy,
    *,
    field: str,
) -> None:
    if (
        not isinstance(source, Mapping)
        or qualify_server_provenance(
            source, policy.artifact_qualification, client_keys=SOURCE_CLIENT_KEYS
        )
        or qualify_server_provenance(
            target, policy.artifact_qualification, client_keys=TARGET_CLIENT_KEYS
        )
    ):
        raise _preflight_err(
            "restore-target-incompatible",
            field,
            "source or target server/client provenance does not satisfy exact trusted policy qualification",
        )
    src_num, dst_num = (
        int(str(source.get("server_version_num") or 0)),
        int(str(target.get("server_version_num") or 0)),
    )
    if (
        (src_num // 10000) != (dst_num // 10000)
        or source.get("os_arch_abi") != target.get("os_arch_abi")
        or source.get("compile_abi") != target.get("compile_abi")
    ):
        raise _preflight_err(
            "restore-target-incompatible",
            field,
            "target server major version, OS/arch ABI, or compile ABI does not match source backup",
        )


def admit_database_extensions(
    plan: LocalRuntimePlan,
    db_name: str,
    db_cat: Mapping[str, Any],
    policy: TrustedExtensionRestorePolicy,
    live: Mapping[str, Any],
    roles_by_name: Mapping[str, Mapping[str, Any]],
    command_runner: CommandRunner,
) -> tuple[tuple[dict[str, object], TrustedExtensionRule], ...]:
    db_role = str(db_cat.get("database_role") or "")
    raw_role = live.get("current_role")
    cur_role: Mapping[str, Any] = raw_role if isinstance(raw_role, Mapping) else {}
    avail = {
        (str(a["name"]), str(a["version"])): a
        for a in (live.get("available_extension_versions") or [])
        if isinstance(a, Mapping)
        and isinstance(a.get("name"), str)
        and isinstance(a.get("version"), str)
    }
    installed = db_cat.get("installed_extensions")
    if not isinstance(installed, list):
        raise _preflight_err("backup-manifest-invalid", db_name, "installed_extensions missing")
    ordered: list[tuple[dict[str, object], TrustedExtensionRule]] = []
    for item in installed:
        if not isinstance(item, Mapping):
            raise _preflight_err("backup-manifest-invalid", db_name, "invalid extension entry")
        ext_name = str(item.get("name") or "")
        if ext_name == BASELINE_EXTENSION_NAME:
            continue
        ext_ver, ext_schema, ext_owner = (
            str(item.get("version") or ""),
            str(item.get("schema") or ""),
            str(item.get("owner") or ""),
        )
        rule = policy.rule_for(ext_name, database_role=db_role)
        if rule is None:
            raise _preflight_err(
                "backup-extension-restore-unsupported",
                db_name,
                f"extension {ext_name!r} is not admitted by policy",
            )
        if (
            ext_owner != plan.user
            or ext_owner not in rule.allowed_owners
            or ext_owner not in roles_by_name
        ):
            raise _preflight_err(
                "restore-extension-owner-invalid",
                db_name,
                f"extension owner {ext_owner!r} does not match the approved lifecycle owner",
            )
        av_row = avail.get((ext_name, ext_ver))
        if av_row is None:
            raise _preflight_err(
                "restore-extension-version-unavailable",
                db_name,
                f"extension {ext_name}=={ext_ver} is unavailable on target",
            )
        verify_extension_artifact(plan, db_name, ext_name, ext_ver, rule, command_runner)
        fixed_schema = av_row.get("schema")
        if (
            isinstance(fixed_schema, str) and fixed_schema and fixed_schema != ext_schema
        ) or av_row.get("relocatable") != item.get("relocatable"):
            raise _preflight_err(
                "restore-extension-schema-incompatible",
                db_name,
                f"extension {ext_name}=={ext_ver} schema/relocatability mismatch",
            )
        if not {str(r) for r in (av_row.get("requires") or [])}.issubset(
            {str(p) for p in (item.get("prerequisite_extensions") or [])}
        ):
            raise _preflight_err(
                "restore-extension-dependency-mismatch",
                db_name,
                f"target extension {ext_name}=={ext_ver} requires unrecorded prerequisites",
            )
        if not (cur_role.get("rolsuper") is True or av_row.get("trusted") is True):
            raise _preflight_err(
                "restore-extension-privilege-insufficient",
                db_name,
                f"lifecycle role lacks privilege to install extension {ext_name}",
            )
        if (
            rule.optional_capability is not None
            and rule.optional_capability.require_principals_before_create
        ):
            check_custom_principals(
                roles_by_name, rule.optional_capability, lifecycle_user=plan.user, field=db_name
            )
        ordered.append((dict(item), rule))
    return tuple(ordered)
