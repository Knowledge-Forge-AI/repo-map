"""Support and refusal predicates for format-1 and format-2 backup manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

from repomap_kg.runtime._backup_observation import (
    _normalize_database_catalog, _normalize_server_provenance, _reject_nonfinite, _unique_json_pairs,
    observe_client_identities, parse_and_validate_catalog_observation, verify_provenance_fingerprints,
)
from repomap_kg.runtime._backup_provenance import (
    BACKUP_FORMAT_VERSION, BASELINE_EXTENSION_NAME, CORE_V1_RESTORE_PROTOCOL, DEFAULT_TOC_TIMEOUT_SECONDS,
    DatabaseObservation, EXTENSION_V2_RESTORE_PROTOCOL, MAX_DATABASES_PER_MANIFEST, MAX_MANIFEST_UTF8_BYTES,
    MAX_TOC_OUTPUT_BYTES, _STDLIB_SUBPROCESS_RUN, catalog_observation_sql, is_supported_format_version,
    parse_and_verify_toc_provenance, parse_toc_entries, provenance_error, run_bounded_popen,
)
from repomap_kg.runtime._extension_restore_blockers import (
    derive_database_blockers_with_policy, derive_manifest_support_with_policy, evaluate_manifest_support_with_policy,
)
from repomap_kg.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy, project_policy_for_observation, resolve_extension_restore_policy,
)
from repomap_kg.runtime.backup_records import DumpTocSummary, LocalDbBackupError
from repomap_kg.runtime.backup_streaming import describe_dump_file
from repomap_kg.runtime.local import LocalRuntimeDiagnostic
from repomap_kg.runtime.release import PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE


def quiescence_record_for_databases(*databases: str, before_after_fingerprint_matched: bool, authority_namespace: str | None = None) -> dict[str, object]:
    from repomap_kg.runtime.maintenance import quiescence_record_for_databases as _qr
    return _qr(*databases, before_after_fingerprint_matched=before_after_fingerprint_matched, authority_namespace=authority_namespace)


_PRIVATE_MANIFEST_KEYS = frozenset({"server_provenance", "artifact_provenance", "database_catalogs", "quiescence"})
_KNOWN_RESTORE_PROTOCOLS = frozenset({CORE_V1_RESTORE_PROTOCOL, EXTENSION_V2_RESTORE_PROTOCOL})
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class BackupSupportEvaluation:
    restore_protocol: str
    restore_supported: bool
    restore_blockers: tuple[str, ...]
    extension_census_state: str


def derive_database_blockers(
    database_catalog: Mapping[str, object], *, extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
    server_provenance: Mapping[str, object] | None = None,
) -> set[str]:
    return derive_database_blockers_with_policy(database_catalog, policy=extension_restore_policy, server_provenance=server_provenance)


def _is_quiescence_held(quiescence: object) -> bool:
    return isinstance(quiescence, Mapping) and (quiescence.get("maintenance_window_held") if "maintenance_window_held" in quiescence else quiescence.get("verified")) is True


def derive_manifest_support(
    database_catalogs: Mapping[str, Mapping[str, object]], *, before_after_fingerprint_matched: bool,
    require_quiescence: bool = False, quiescence: Mapping[str, object] | None = None,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None, server_provenance: Mapping[str, object] | None = None,
) -> BackupSupportEvaluation:
    return BackupSupportEvaluation(
        *derive_manifest_support_with_policy(
            database_catalogs, before_after_fingerprint_matched=before_after_fingerprint_matched,
            require_quiescence=require_quiescence, quiescence=quiescence, policy=extension_restore_policy,
            server_provenance=server_provenance, is_quiescence_held_fn=_is_quiescence_held,
        )
    )


def validate_format2_manifest_provenance(manifest: Mapping[str, object], *, manifest_path: Path, expected_databases: Sequence[str]) -> None:
    def _invalid(message: str) -> LocalDbBackupError:
        return provenance_error("backup-manifest-invalid", str(manifest_path), message)

    if len(expected_databases) > MAX_DATABASES_PER_MANIFEST or len(set(expected_databases)) != len(expected_databases):
        raise _invalid("backup manifest databases list is invalid")
    protocol, blockers, quiescence = manifest.get("restore_protocol"), manifest.get("restore_blockers"), manifest.get("quiescence")
    if not isinstance(protocol, str) or protocol not in _KNOWN_RESTORE_PROTOCOLS:
        raise _invalid("format-2 manifest requires a valid restore_protocol")
    if not isinstance(manifest.get("restore_supported"), bool):
        raise _invalid("format-2 manifest requires boolean restore_supported")
    if not isinstance(blockers, list) or not all(isinstance(i, str) and i != "" for i in blockers):
        raise _invalid("format-2 manifest requires string list restore_blockers")
    if (
        not isinstance(quiescence, Mapping) or not isinstance(quiescence.get("before_after_fingerprint_matched"), bool)
        or (not isinstance(quiescence.get("maintenance_window_held"), bool) and not isinstance(quiescence.get("verified"), bool))
        or not str(quiescence.get("maintenance_window_mode") or quiescence.get("mode") or "")
    ):
        raise _invalid("format-2 manifest requires valid quiescence provenance")
    try:
        _normalize_server_provenance(manifest.get("server_provenance"), database=str(manifest_path))
    except LocalDbBackupError as exc:
        raise _invalid("format-2 manifest has invalid server_provenance") from exc
    artifact_prov, catalogs, dump_files = manifest.get("artifact_provenance"), manifest.get("database_catalogs"), manifest.get("dump_files")
    if not isinstance(artifact_prov, Mapping) or not isinstance(catalogs, Mapping) or not catalogs:
        raise _invalid("format-2 manifest requires artifact_provenance and database_catalogs")
    is_coord, check_dbs, bindings = manifest.get("scope") == "exact-configured-graph-control-databases", tuple(expected_databases), artifact_prov.get("archive_bindings")
    if not isinstance(bindings, list):
        raise _invalid("format-2 manifest archive_bindings must be a list")
    bound_dbs = {str(b.get("database")) for b in bindings if isinstance(b, Mapping) and isinstance(b.get("database"), str)}
    if len(bindings) != len(bound_dbs) or bound_dbs != set(catalogs.keys()):
        raise _invalid("format-2 manifest archive_bindings and database_catalogs are inconsistent")
    if len(bindings) != len(check_dbs) or bound_dbs != set(check_dbs):
        raise provenance_error("coordinated-backup-topology-mismatch" if is_coord else "backup-manifest-invalid", str(manifest_path), "format-2 manifest provenance bindings do not match databases")
    if not isinstance(dump_files, list) or len(dump_files) != len(check_dbs):
        raise provenance_error("coordinated-backup-dump-set-invalid" if is_coord else "backup-manifest-invalid", str(manifest_path), "format-2 manifest dump_files must match databases")
    dump_by_name = {str(item.get("name")): item for item in dump_files if isinstance(item, Mapping) and isinstance(item.get("name"), str)}
    if is_coord and set(dump_by_name.keys()) != {f"{db}.pgcustom" for db in check_dbs}:
        raise provenance_error("coordinated-backup-dump-set-invalid", str(manifest_path), "coordinated dump_files names do not match databases")
    seen_dbs, bound_files = set(), set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise _invalid("format-2 manifest has non-object archive_binding entry")
        db_val, df_val, sha_val, size_val, toc_val = binding.get("database"), binding.get("dump_file"), binding.get("sha256"), binding.get("size_bytes"), binding.get("toc_sha256")
        df_entry = dump_by_name.get(df_val) if isinstance(df_val, str) else None
        if (
            not isinstance(db_val, str) or not db_val or not isinstance(df_val, str) or not df_val or df_entry is None
            or not isinstance(sha_val, str) or len(sha_val) != 64 or df_entry.get("sha256") != sha_val
            or isinstance(size_val, bool) or not isinstance(size_val, int) or size_val <= 0 or df_entry.get("size_bytes") != size_val
            or not isinstance(toc_val, str) or len(toc_val) != 64 or db_val in seen_dbs or df_val in bound_files
        ):
            raise _invalid("format-2 manifest has invalid archive_binding entry")
        seen_dbs.add(db_val)
        bound_files.add(df_val)
    for db_name in check_dbs:
        try:
            _normalize_database_catalog(catalogs.get(db_name), database=db_name)
        except LocalDbBackupError as exc:
            raise _invalid(f"format-2 manifest has invalid database_catalogs[{db_name!r}]") from exc


def evaluate_backup_restore_support(
    manifest: Mapping[str, object], *, database: str | None = None, require_quiescence: bool = False,
    dry_run: bool = False, extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> BackupSupportEvaluation:
    del dry_run
    return BackupSupportEvaluation(
        *evaluate_manifest_support_with_policy(
            manifest, database=database, require_quiescence=require_quiescence,
            policy=extension_restore_policy, is_quiescence_held_fn=_is_quiescence_held,
        )
    )


def raise_for_unsupported_restore(evaluation: BackupSupportEvaluation, *, target: str) -> None:
    if evaluation.restore_supported and not evaluation.restore_blockers:
        return
    blockers = evaluation.restore_blockers
    summary = ", ".join(blockers) if blockers else "restore_supported=false"
    diags: list[LocalRuntimeDiagnostic] = []
    if "backup-toc-inconsistent" in blockers:
        diags.append(LocalRuntimeDiagnostic("error", "backup-toc-inconsistent", target, f"TOC inconsistent ({summary})"))
    if "extension-config-table-unsupported" in blockers:
        diags.append(LocalRuntimeDiagnostic("error", "backup-extension-config-unsupported", target, f"extconfig unsupported ({summary})"))
    if "extension-schema-unsupported" in blockers:
        diags.append(LocalRuntimeDiagnostic("error", "backup-extension-schema-unsupported", target, f"schema unsupported ({summary})"))
    if "database-creation-semantics-mismatch" in blockers:
        diags.append(LocalRuntimeDiagnostic("error", "restore-creation-semantics-incompatible", target, f"creation semantics incompatible ({summary})"))
    ext_codes = (
        "extension-not-allowlisted", "extension-dependency-unsupported", "extension-restore-protocol-unimplemented",
        "extension-version-not-qualified", "extension-owner-unapproved", "extension-policy-binding-mismatch",
        "extension-target-incompatible", "database-creation-semantics-mismatch",
    )
    if any(c in blockers for c in ext_codes):
        diags.append(LocalRuntimeDiagnostic("error", "backup-extension-restore-unsupported", target, f"extension restore unsupported ({summary})"))
    diags.append(LocalRuntimeDiagnostic("error", "backup-restore-unsupported", target, f"backup restore unsupported for {target} (not verified and restorable): {summary}"))
    raise LocalDbBackupError(tuple(diags))


def require_backup_restore_supported(
    manifest: Mapping[str, object], *, database: str | None = None, require_quiescence: bool = False,
    dry_run: bool = False, target: str = "manifest", extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> BackupSupportEvaluation:
    evaluation = evaluate_backup_restore_support(
        manifest, database=database, require_quiescence=require_quiescence, dry_run=dry_run, extension_restore_policy=extension_restore_policy
    )
    if not evaluation.restore_supported:
        raise_for_unsupported_restore(evaluation, target=database or target)
    return evaluation


def require_verified_backup_inspection_supported(
    inspection: Any, *, database: str, extension_restore_policy: TrustedExtensionRestorePolicy | None = None
) -> BackupSupportEvaluation:
    manifest = getattr(inspection, "manifest", None)
    if not isinstance(manifest, Mapping):
        raise provenance_error("backup-restore-unsupported", database, "pre-upgrade backup verification failed")
    evaluation = require_backup_restore_supported(
        manifest, database=database, require_quiescence=False, target=database, extension_restore_policy=extension_restore_policy
    )
    has_toc = bool(getattr(inspection, "dump_summaries", ())) or (
        bool(getattr(inspection, "dump_contents_read", False)) and int(getattr(inspection, "toc_entry_count", 0) or 0) > 0
    )
    if not getattr(inspection, "checksum_verified", False) or not has_toc or bool(getattr(inspection, "diagnostics", None)):
        raise provenance_error("backup-restore-unsupported", database, "pre-upgrade backup verification failed")
    return evaluation


def sanitize_public_manifest(
    manifest: Mapping[str, object], *, extension_restore_policy: TrustedExtensionRestorePolicy | None = None
) -> dict[str, object]:
    ev = evaluate_backup_restore_support(manifest, dry_run=True, extension_restore_policy=extension_restore_policy)
    return {**{k: v for k, v in manifest.items() if k not in _PRIVATE_MANIFEST_KEYS}, "extension_census_state": ev.extension_census_state, "restore_protocol": ev.restore_protocol, "restore_blockers": list(ev.restore_blockers)}


def observe_connection_provenance(
    operator: Any, database: str, *, extension_restore_policy: TrustedExtensionRestorePolicy | None = None
) -> DatabaseObservation:
    import psycopg
    connect_fn = getattr(operator, "_connect", None)
    if not callable(connect_fn):
        raise provenance_error("backup-observation-incomplete", database, "connection authority unavailable")
    graph_dbs, ctrl_db = getattr(operator, "databases", ()), getattr(operator, "control_database", None)
    if isinstance(graph_dbs, (tuple, list, set)) and database in graph_dbs:
        role = "graph"
    elif isinstance(ctrl_db, str) and ctrl_db and database == ctrl_db:
        role = "control"
    else:
        raise provenance_error("backup-observation-incomplete", database, "database is not an owned graph or control database")
    ext_policy = project_policy_for_observation(extension_restore_policy, database_role=role)
    try:
        with connect_fn(database) as connection:
            connection.execute("SET statement_timeout = '30s'; SET lock_timeout = '30s';")
            row = connection.execute(catalog_observation_sql(role)).fetchone()
    except psycopg.Error as exc:
        raise provenance_error("backup-observation-incomplete", database, "connection catalog observation query failed") from exc
    if not row or not isinstance(row[0], str):
        raise provenance_error("backup-observation-incomplete", database, "connection catalog observation empty")
    dump_cmd = operator.pg_dump_command(database) if callable(getattr(operator, "pg_dump_command", None)) else ()
    dump_bin = str(dump_cmd[0]) if isinstance(dump_cmd, (tuple, list)) and dump_cmd else PACKAGED_PG_DUMP
    clients = observe_client_identities(pg_dump_bin=dump_bin, pg_restore_bin=PACKAGED_PG_RESTORE, psql_bin=None)
    return parse_and_validate_catalog_observation(
        row[0].encode("utf-8"), database=database, expected_role=role, extension_policy=ext_policy, observed_clients=clients
    )


def _run_trusted_toc_bytes(
    restore_client: str, dump_path: Path, *, database: str, command_runner: Any, env: Mapping[str, str] | None = None, secret: str | None = None
) -> bytes:
    cmd = (restore_client, "-l", str(dump_path))
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        return run_bounded_popen(cmd, max_output_bytes=MAX_TOC_OUTPUT_BYTES, timeout_seconds=DEFAULT_TOC_TIMEOUT_SECONDS, error_code="backup-toc-inconsistent", field=database, secret=secret, env=env)
    inspection = command_runner(cmd, stdout=-1, stderr=-1, env=dict(env) if env is not None else None, check=False)
    if getattr(inspection, "returncode", 1) != 0:
        raise provenance_error("backup-toc-inconsistent", database, "release cluster TOC check failed")
    raw_stdout = getattr(inspection, "stdout", None)
    raw_toc = raw_stdout if isinstance(raw_stdout, bytes) else (raw_stdout.encode("utf-8") if isinstance(raw_stdout, str) else None)
    if raw_toc is None or len(raw_toc) > MAX_TOC_OUTPUT_BYTES:
        raise provenance_error("backup-toc-inconsistent", database, "release cluster TOC output missing or exceeded ceiling")
    return raw_toc


def build_and_verify_release_cluster_upgrade_manifest(
    *, operator: Any, database: str, dump: Any, dump_path: Path, restore_client: str,
    command_runner: Any, env: Mapping[str, str], before_obs: DatabaseObservation,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> dict[str, object]:
    after_obs = verify_provenance_fingerprints(
        before_obs, observe_connection_provenance(operator, database, extension_restore_policy=extension_restore_policy)
    )
    raw_toc = _run_trusted_toc_bytes(PACKAGED_PG_RESTORE, dump_path, database=database, command_runner=command_runner, env=env, secret=getattr(operator, "password", None))
    toc_obs = parse_and_verify_toc_provenance(raw_toc, database=database, database_catalog=after_obs.database_catalog)
    quiescence = quiescence_record_for_databases(database, before_after_fingerprint_matched=True, authority_namespace=getattr(operator, "authority_namespace", None))
    support = derive_manifest_support(
        {database: after_obs.database_catalog},
        before_after_fingerprint_matched=True,
        require_quiescence=True,
        quiescence=quiescence,
        extension_restore_policy=extension_restore_policy,
        server_provenance=after_obs.server_provenance,
    )
    resolved = resolve_extension_restore_policy(extension_restore_policy)
    result: dict[str, object] = {
        "artifact": dump.name, "database": database, "database_catalogs": {database: after_obs.database_catalog},
        "quiescence": quiescence, "restore_blockers": list(support.restore_blockers), "restore_client": restore_client,
        "restore_protocol": support.restore_protocol, "restore_supported": support.restore_supported,
        "schema_version": BACKUP_FORMAT_VERSION, "server_provenance": after_obs.server_provenance,
        "sha256": dump.sha256, "size_bytes": dump.size_bytes, "toc_sha256": toc_obs.toc_sha256,
    }
    if resolved.allow_extension_v2:
        result["artifact_provenance"] = {"policy_binding": resolved.policy_binding_record()}
    return result


def _validate_release_archive_fields(payload: Mapping[str, object], *, database: str) -> tuple[str, str, int]:
    rec_db, art_name, sha_val, size_val = payload.get("database"), payload.get("artifact"), payload.get("sha256"), payload.get("size_bytes")
    if (
        not isinstance(rec_db, str) or rec_db != database or not isinstance(art_name, str) or not art_name or art_name in {".", ".."}
        or "/" in art_name or "\\" in art_name or Path(art_name).name != art_name or not isinstance(sha_val, str) or len(sha_val) != 64
        or not set(sha_val).issubset(_HEX_CHARS) or isinstance(size_val, bool) or not isinstance(size_val, int) or size_val <= 0
    ):
        raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json missing or invalid archive integrity fields")
    return art_name, sha_val.lower(), size_val


def load_and_verify_release_cluster_upgrade_artifact(
    artifact: Mapping[str, object] | Path,
    *,
    database: str = "repomap",
    verify_dump_on_disk: bool = False,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> tuple[dict[str, object], BackupSupportEvaluation]:
    if verify_dump_on_disk and not isinstance(artifact, Path):
        raise provenance_error("backup-manifest-invalid", database, "on-disk verification requires a filesystem path")
    base_dir: Path | None = None
    if isinstance(artifact, Path):
        if artifact.is_symlink():
            raise provenance_error("backup-manifest-invalid", database, "release artifact path cannot be a symlink")
        manifest_file = artifact / "schema-upgrade.json" if artifact.is_dir() else artifact
        base_dir = manifest_file.parent
        if manifest_file.is_symlink() or base_dir.is_symlink() or not manifest_file.is_file():
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json is missing")
        with manifest_file.open("rb") as handle:
            raw_bytes = handle.read(MAX_MANIFEST_UTF8_BYTES + 1)
        if len(raw_bytes) > MAX_MANIFEST_UTF8_BYTES:
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json exceeds ceiling")
        try:
            loaded = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_unique_json_pairs, parse_constant=_reject_nonfinite)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json is invalid JSON") from exc
        if not isinstance(loaded, Mapping):
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json must be an object")
        payload: Mapping[str, object] = loaded
    else:
        payload = artifact
    schema_version = payload.get("schema_version")
    if not is_supported_format_version(schema_version):
        raise provenance_error("backup-format-unsupported", database, "unsupported schema-upgrade.json version")
    if not isinstance(payload.get("restore_supported"), bool):
        raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json requires boolean restore_supported")
    translated: dict[str, object] = dict(payload, backup_format_version=schema_version)
    if "database_catalog" in translated and "database_catalogs" not in translated:
        translated["database_catalogs"] = {database: translated["database_catalog"]}
    evaluation = require_backup_restore_supported(
        translated, database=database, require_quiescence=(schema_version == 2), target=database, extension_restore_policy=extension_restore_policy
    )
    art_name, sha_val, size_val = _validate_release_archive_fields(payload, database=database)
    if schema_version == 2:
        toc_val, rc_val = payload.get("toc_sha256"), payload.get("restore_client")
        if not isinstance(toc_val, str) or len(toc_val) != 64 or not set(toc_val).issubset(_HEX_CHARS) or not isinstance(rc_val, str) or not rc_val:
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json missing format-2 artifact bindings")
        try:
            _normalize_server_provenance(payload.get("server_provenance"), database=database)
            cats = translated.get("database_catalogs")
            if not isinstance(cats, Mapping) or database not in cats:
                raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json missing database_catalogs")
            _normalize_database_catalog(cats[database], database=database)
        except LocalDbBackupError as exc:
            raise provenance_error("backup-manifest-invalid", database, "schema-upgrade.json has invalid provenance") from exc
    if verify_dump_on_disk and base_dir is not None:
        dump_file = base_dir / art_name
        if dump_file.is_symlink() or not dump_file.is_file() or dump_file.resolve().parent != base_dir.resolve():
            raise provenance_error("backup-manifest-invalid", database, f"upgrade dump {art_name} missing or unsafe")
        actual = describe_dump_file(dump_file)
        if actual.sha256 != sha_val or actual.size_bytes != size_val:
            raise provenance_error("backup-manifest-invalid", database, f"upgrade dump {art_name} checksum mismatch")
        raw_toc = _run_trusted_toc_bytes(PACKAGED_PG_RESTORE, dump_file, database=database, command_runner=subprocess.run)
        toc_obs = parse_toc_entries(raw_toc, database=database)
        if toc_obs.entry_count <= 0:
            raise provenance_error("backup-toc-inconsistent", database, "release upgrade artifact TOC has no entries")
        resolved = resolve_extension_restore_policy(extension_restore_policy)
        if any(
            ext != BASELINE_EXTENSION_NAME and (schema_version != 2 or not resolved.allow_extension_v2 or resolved.rule_for(ext) is None)
            for ext in toc_obs.extensions
        ):
            raise_for_unsupported_restore(BackupSupportEvaluation(CORE_V1_RESTORE_PROTOCOL, False, ("extension-not-allowlisted", "extension-restore-protocol-unimplemented"), "unknown"), target=database)
        if schema_version == 2:
            cats = translated["database_catalogs"]
            assert isinstance(cats, Mapping)
            parse_and_verify_toc_provenance(raw_toc, database=database, database_catalog=cats[database])
            if toc_obs.toc_sha256 != str(payload.get("toc_sha256")).lower():
                raise provenance_error("backup-toc-inconsistent", database, "release upgrade artifact TOC digest mismatch")
        translated["_verified_toc_summary"] = DumpTocSummary(dump_file=art_name, dump_format="pgcustom", dump_contents_read=True, toc_entry_count=toc_obs.entry_count, extensions=toc_obs.extensions, schemas=toc_obs.schemas)
    return translated, evaluation


def evaluate_release_cluster_upgrade_artifact(
    artifact: Mapping[str, object] | Path,
    *,
    database: str = "repomap",
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> BackupSupportEvaluation:
    return load_and_verify_release_cluster_upgrade_artifact(
        artifact, database=database, extension_restore_policy=extension_restore_policy
    )[1]
