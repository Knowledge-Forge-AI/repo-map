"""Shared manifest/catalog support blockers for core_v1 and D9-B extension_v2 restore."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.runtime._backup_provenance import (
    BACKUP_FORMAT_VERSION,
    BASELINE_EXTENSION_NAME,
    BASELINE_EXTENSION_SCHEMA,
    CORE_V1_RESTORE_PROTOCOL,
    EXTENSION_V2_RESTORE_PROTOCOL,
    MAX_DATABASES_PER_MANIFEST,
    is_supported_format_version,
    provenance_error,
)
from repomap_kg.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy,
    TrustedExtensionRule,
    resolve_extension_restore_policy,
)
from repomap_kg.runtime._extension_restore_qualification import (
    qualify_server_provenance,
    source_creation_semantics_complete,
)

_ALLOWED_DATABASE_ROLES = frozenset({"graph", "control"})


def _dependency_blockers(
    dep: object, admitted: Mapping[str, TrustedExtensionRule], *, allow_v2: bool
) -> set[str]:
    if not isinstance(dep, Mapping) or "edge_count" not in dep or "edges" not in dep:
        return {"extension-catalog-incomplete"}
    edge_count, edges = dep.get("edge_count"), dep.get("edges")
    if (
        isinstance(edge_count, bool)
        or not isinstance(edge_count, int)
        or edge_count < 0
        or not isinstance(edges, list)
        or edge_count != len(edges)
    ):
        return {"extension-catalog-incomplete"}
    if not edges:
        return set()
    if not allow_v2:
        return {"extension-dependency-unsupported", "extension-restore-protocol-unimplemented"}
    blockers: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            blockers.add("extension-catalog-incomplete")
            continue
        rule = admitted.get(str(edge.get("extension") or ""))
        obj_schema, obj_class = (
            str(edge.get("object_schema") or ""),
            str(edge.get("object_class") or ""),
        )
        allowed_sch = (
            (set(rule.allowed_dependent_schemas) | {rule.required_schema})
            if (rule and rule.allowed_dependent_schemas)
            else set()
        )
        sch_ok = bool(allowed_sch) and bool(obj_schema) and obj_schema in allowed_sch
        cls_ok = (
            (rule is not None) and bool(obj_class) and obj_class in rule.allowed_dependent_classes
        )
        if rule is None or edge.get("identity_portable") is not True or not sch_ok or not cls_ok:
            blockers.add("extension-dependency-unsupported")
    return blockers


def derive_database_blockers_with_policy(
    database_catalog: Mapping[str, object],
    *,
    policy: TrustedExtensionRestorePolicy | None = None,
    server_provenance: Mapping[str, object] | None = None,
) -> set[str]:
    resolved = resolve_extension_restore_policy(policy)
    blockers: set[str] = set()
    db_role_raw = database_catalog.get("database_role")
    db_role = str(db_role_raw) if db_role_raw in _ALLOWED_DATABASE_ROLES else None
    installed = database_catalog.get("installed_extensions")
    if not isinstance(installed, list):
        return {"extension-catalog-incomplete"}
    admitted: dict[str, TrustedExtensionRule] = {}
    has_non_baseline = False
    for item in installed:
        if not isinstance(item, Mapping):
            blockers.add("extension-catalog-incomplete")
            continue
        name, schema, version, owner = (
            item.get("name"),
            item.get("schema"),
            item.get("version"),
            item.get("owner"),
        )
        cfg_tables, conds, prereqs = (
            item.get("extconfig_tables"),
            item.get("extcondition"),
            item.get("prerequisite_extensions"),
        )
        own_class, reloc, is_base = (
            item.get("ownership_classification"),
            item.get("relocatable"),
            item.get("is_baseline"),
        )
        if (
            not isinstance(name, str)
            or name == ""
            or not isinstance(schema, str)
            or schema == ""
            or not isinstance(cfg_tables, list)
            or not isinstance(conds, list)
            or not isinstance(prereqs, list)
            or not isinstance(own_class, str)
            or not isinstance(reloc, bool)
            or not isinstance(is_base, bool)
        ):
            blockers.add("extension-catalog-incomplete")
            continue
        if cfg_tables or conds:
            blockers.add("extension-config-table-unsupported")
            if not resolved.allow_extension_v2:
                blockers.add("extension-restore-protocol-unimplemented")
        if name == BASELINE_EXTENSION_NAME:
            if schema != BASELINE_EXTENSION_SCHEMA:
                blockers.update(
                    ("extension-schema-unsupported", "extension-restore-protocol-unimplemented")
                )
            continue
        has_non_baseline = True
        rule = (
            resolved.rule_for(name, database_role=db_role)
            if (resolved.allow_extension_v2 and db_role is not None)
            else None
        )
        if rule is None:
            blockers.add("extension-not-allowlisted")
            if not resolved.allow_extension_v2:
                blockers.add("extension-restore-protocol-unimplemented")
            if schema not in (BASELINE_EXTENSION_SCHEMA, "public"):
                blockers.add("extension-schema-unsupported")
            continue
        admitted[name] = rule
        if not isinstance(version, str) or version not in rule.exact_versions:
            blockers.add("extension-version-not-qualified")
        if schema != rule.required_schema or (
            rule.relocatable is not None and reloc != rule.relocatable
        ):
            blockers.add("extension-schema-unsupported")
        if not isinstance(owner, str) or owner not in rule.allowed_owners:
            blockers.add("extension-owner-unapproved")
        if [str(p) for p in prereqs] != sorted(rule.prerequisites):
            blockers.add("extension-dependency-unsupported")
        if (
            own_class != rule.ownership_classification
            or item.get("declaration_identity") != rule.declaration_identity
            or item.get("experimental_context") != rule.experimental_context
            or item.get("baseline_origin") != rule.baseline_origin
        ):
            blockers.add("extension-policy-binding-mismatch")

    for rule in admitted.values():
        if any(req not in admitted for req in rule.prerequisites):
            blockers.add("extension-dependency-unsupported")

    cfg_entries = database_catalog.get("extension_config_tables")
    if not isinstance(cfg_entries, list):
        blockers.add("extension-catalog-incomplete")
    elif cfg_entries:
        blockers.add("extension-config-table-unsupported")
        if not resolved.allow_extension_v2:
            blockers.add("extension-restore-protocol-unimplemented")
    blockers.update(
        _dependency_blockers(
            database_catalog.get("extension_dependency_summary"),
            admitted,
            allow_v2=resolved.allow_extension_v2,
        )
    )

    if has_non_baseline and resolved.allow_extension_v2:
        blockers.update(
            qualify_server_provenance(server_provenance, resolved.artifact_qualification)
        )
        if not source_creation_semantics_complete(database_catalog.get("creation_semantics")):
            blockers.add("database-creation-semantics-mismatch")
    return blockers


def catalog_requires_extension_v2(database_catalog: Mapping[str, object]) -> bool:
    installed = database_catalog.get("installed_extensions")
    if isinstance(installed, list) and any(
        isinstance(i, Mapping) and i.get("name") not in (None, "", BASELINE_EXTENSION_NAME)
        for i in installed
    ):
        return True
    dep = database_catalog.get("extension_dependency_summary")
    return isinstance(dep, Mapping) and int(dep.get("edge_count") or 0) > 0


def derive_manifest_support_with_policy(
    database_catalogs: Mapping[str, Mapping[str, object]],
    *,
    before_after_fingerprint_matched: bool,
    require_quiescence: bool = False,
    quiescence: Mapping[str, object] | None = None,
    policy: TrustedExtensionRestorePolicy | None = None,
    server_provenance: Mapping[str, object] | None = None,
    is_quiescence_held_fn: Any,
) -> tuple[str, bool, tuple[str, ...], str]:
    resolved = resolve_extension_restore_policy(policy)
    blockers: set[str] = (
        {"extension-catalog-incomplete"}
        if (not database_catalogs or len(database_catalogs) > MAX_DATABASES_PER_MANIFEST)
        else set()
    )
    needs_ext_v2 = any(catalog_requires_extension_v2(c) for c in database_catalogs.values())
    for db_catalog in database_catalogs.values():
        blockers.update(
            derive_database_blockers_with_policy(
                db_catalog, policy=resolved, server_provenance=server_provenance
            )
        )
    if before_after_fingerprint_matched is not True or (
        require_quiescence and not is_quiescence_held_fn(quiescence)
    ):
        blockers.add("quiescence-not-verified")
    protocol = (
        EXTENSION_V2_RESTORE_PROTOCOL
        if (needs_ext_v2 and resolved.allow_extension_v2)
        else CORE_V1_RESTORE_PROTOCOL
    )
    sorted_blockers = tuple(sorted(blockers))
    return protocol, len(sorted_blockers) == 0, sorted_blockers, "complete"


def evaluate_manifest_support_with_policy(
    manifest: Mapping[str, object],
    *,
    database: str | None = None,
    require_quiescence: bool = False,
    policy: TrustedExtensionRestorePolicy | None = None,
    is_quiescence_held_fn: Any,
) -> tuple[str, bool, tuple[str, ...], str]:
    resolved = resolve_extension_restore_policy(policy)
    version = manifest.get("backup_format_version")
    if not is_supported_format_version(version):
        raise provenance_error(
            "backup-format-unsupported",
            database or "manifest.json",
            "backup manifest format is unsupported",
        )
    protocol = str(manifest.get("restore_protocol") or CORE_V1_RESTORE_PROTOCOL)
    blockers: set[str] = set()
    raw_blockers, catalogs = manifest.get("restore_blockers"), manifest.get("database_catalogs")
    is_single_from_multi = (
        database is not None and isinstance(catalogs, Mapping) and len(catalogs) > 1
    )
    if not is_single_from_multi and isinstance(raw_blockers, list):
        blockers.update(str(item) for item in raw_blockers if str(item))

    if protocol not in {CORE_V1_RESTORE_PROTOCOL, EXTENSION_V2_RESTORE_PROTOCOL}:
        blockers.add("extension-restore-protocol-unimplemented")
    elif protocol == EXTENSION_V2_RESTORE_PROTOCOL and not resolved.allow_extension_v2:
        blockers.update(("extension-restore-protocol-unimplemented", "extension-not-allowlisted"))

    if version == BACKUP_FORMAT_VERSION:
        srv_raw = manifest.get("server_provenance")
        srv_map = srv_raw if isinstance(srv_raw, Mapping) else None
        needs_ext_v2 = False
        if (
            not isinstance(catalogs, Mapping)
            or not catalogs
            or len(catalogs) > MAX_DATABASES_PER_MANIFEST
        ):
            blockers.add("extension-catalog-incomplete")
        else:
            raw_dbs = manifest.get("databases")
            fallback_dbs = (
                raw_dbs
                if isinstance(raw_dbs, (list, tuple)) and raw_dbs
                else tuple(catalogs.keys())
            )
            target_dbs = (
                (database,) if database is not None else tuple(str(d) for d in fallback_dbs)
            )
            if not target_dbs:
                blockers.add("extension-catalog-incomplete")
            for db_name in target_dbs:
                db_cat = catalogs.get(db_name)
                if isinstance(db_cat, Mapping):
                    needs_ext_v2 = needs_ext_v2 or catalog_requires_extension_v2(db_cat)
                    blockers.update(
                        derive_database_blockers_with_policy(
                            db_cat, policy=resolved, server_provenance=srv_map
                        )
                    )
                else:
                    blockers.add("extension-catalog-incomplete")
        if needs_ext_v2 and protocol != EXTENSION_V2_RESTORE_PROTOCOL:
            blockers.add("extension-restore-protocol-unimplemented")
        if protocol == EXTENSION_V2_RESTORE_PROTOCOL and resolved.allow_extension_v2:
            # The stored binding must equal the current declaration record exactly; current
            # target qualification is checked separately and never enters this identity.
            art = manifest.get("artifact_provenance")
            pol_bind = art.get("policy_binding") if isinstance(art, Mapping) else None
            if not isinstance(pol_bind, Mapping) or dict(pol_bind) != (
                resolved.policy_binding_record()
            ):
                blockers.add("extension-policy-binding-mismatch")
        quiescence = manifest.get("quiescence")
        if (
            not isinstance(quiescence, Mapping)
            or quiescence.get("before_after_fingerprint_matched") is not True
            or (require_quiescence and not is_quiescence_held_fn(quiescence))
        ):
            blockers.add("quiescence-not-verified")
        raw_supported = manifest.get("restore_supported")
        flag_ok = (
            isinstance(raw_supported, bool) if is_single_from_multi else (raw_supported is True)
        )
        protocol_ok = protocol == CORE_V1_RESTORE_PROTOCOL or (
            protocol == EXTENSION_V2_RESTORE_PROTOCOL and resolved.allow_extension_v2
        )
        return (
            protocol,
            flag_ok and not blockers and protocol_ok,
            tuple(sorted(blockers)),
            "complete",
        )

    if isinstance(catalogs, Mapping):
        for db_name in (database,) if database is not None else tuple(str(k) for k in catalogs):
            db_cat = catalogs.get(db_name)
            if isinstance(db_cat, Mapping):
                blockers.update(derive_database_blockers_with_policy(db_cat, policy=None))
    raw_supported = manifest.get("restore_supported")
    return (
        protocol,
        (raw_supported is not False) and not blockers and (protocol == CORE_V1_RESTORE_PROTOCOL),
        tuple(sorted(blockers)),
        "unknown",
    )
