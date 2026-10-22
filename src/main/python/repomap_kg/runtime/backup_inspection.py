"""Read-only inspection and verification for RepoMap backups."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime._backup_provenance import (
    BACKUP_FORMAT_VERSION,
    CORE_V1_RESTORE_PROTOCOL,
    DEFAULT_TOC_TIMEOUT_SECONDS,
    MAX_TOC_OUTPUT_BYTES,
    _STDLIB_SUBPROCESS_RUN,
    parse_and_verify_toc_provenance,
    parse_toc_entries,
    provenance_error,
    run_bounded_popen,
    runtime_postgres_password,
)
from repomap_kg.runtime._backup_support import (
    BackupSupportEvaluation,
    raise_for_unsupported_restore,
    require_backup_restore_supported,
)
from repomap_kg.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy,
    resolve_extension_restore_policy,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    backup_root,
    decode_process_output,
    planned_pg_restore_list_command,
    run_container_command,
)
from repomap_kg.runtime.backup_manifests import (
    infer_dump_format,
    read_manifest_file,
    resolve_backup_manifest_path,
    resolve_dump_file_for_inspection,
    safe_dump_file_name,
    select_dump_file_for_database,
    summarize_pg_restore_toc,
    verify_dump_file_checksum,
    verify_dump_file_checksum_for_inspection,
)
from repomap_kg.runtime.backup_records import (
    BackupInfoResult,
    BackupInspectResult,
    BackupListingResult,
    DumpTocSummary,
    LocalDbBackupError,
    LocalDbBackupResult,
    RuntimeContainerMetadata,
    safe_manifest_summary,
)
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan


def list_backups(repo_map_home: str | Path | None) -> BackupListingResult:
    home = resolve_repo_map_home(repo_map_home)
    backups_root = backup_root(home)
    backups: list[dict[str, Any]] = []
    diagnostics: list[LocalRuntimeDiagnostic] = []
    if backups_root.exists():
        for manifest_path in sorted(backups_root.rglob("manifest.json")):
            try:
                manifest = read_manifest_file(manifest_path)
            except LocalDbBackupError as error:
                diagnostics.extend(error.diagnostics)
                continue
            backups.append(safe_manifest_summary(manifest, manifest_path.parent))
    return BackupListingResult(
        repo_map_home=home,
        backups_root=backups_root,
        backups=tuple(backups),
        diagnostics=tuple(diagnostics),
    )


def read_backup_info(
    repo_map_home: str | Path | None,
    backup_id_or_path: str | Path,
) -> BackupInfoResult:
    home = resolve_repo_map_home(repo_map_home)
    backups_root = backup_root(home)
    manifest_path = resolve_backup_manifest_path(backups_root, backup_id_or_path)
    manifest = read_manifest_file(manifest_path)
    return BackupInfoResult(
        repo_map_home=home,
        backups_root=backups_root,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def inspect_backup(
    repo_map_home: str | Path | None,
    backup_id_or_path: str | Path,
    *,
    command_runner: CommandRunner | None,
    default_command_runner: CommandRunner,
    build_local_runtime_plan: Callable[..., LocalRuntimePlan],
    inspect_owned_postgres_container: Callable[..., RuntimeContainerMetadata],
    run_pg_restore_list: Callable[..., str],
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> BackupInspectResult:
    resolved_policy = resolve_extension_restore_policy(extension_restore_policy)
    runner = command_runner or default_command_runner
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    backups_root = backup_root(home)
    manifest_path = resolve_backup_manifest_path(backups_root, backup_id_or_path)
    manifest = read_manifest_file(manifest_path)
    backup_dir = manifest_path.parent
    diagnostics: list[LocalRuntimeDiagnostic] = []
    dump_summaries: list[DumpTocSummary] = []
    checksum_results: list[bool] = []
    container: RuntimeContainerMetadata | None = None
    manifest_dump_format = manifest.get("dump_format")
    for dump_file in manifest.get("dump_files", []):
        if not isinstance(dump_file, Mapping):
            diagnostics.append(LocalRuntimeDiagnostic("warning", "backup-dump-metadata-invalid", "dump_files", "backup dump metadata entry is not an object"))
            checksum_results.append(False)
            continue
        dump_name = safe_dump_file_name(dump_file.get("name"))
        dump_path, dump_name_safe = resolve_dump_file_for_inspection(backup_dir, dump_file)
        if dump_path is None:
            diagnostics.append(LocalRuntimeDiagnostic("error", "backup-dump-name-unsafe", dump_name, "backup dump file name is not safe for inspection"))
            checksum_results.append(False)
            continue
        checksum_ok, checksum_diagnostics = verify_dump_file_checksum_for_inspection(dump_path, dump_file, dump_name_safe)
        diagnostics.extend(checksum_diagnostics)
        checksum_results.append(checksum_ok)
        dump_format = str(manifest_dump_format or infer_dump_format(dump_name_safe))
        if not checksum_ok:
            continue
        if dump_format != "pgcustom":
            diagnostics.append(LocalRuntimeDiagnostic("warning", "backup-dump-toc-unsupported", dump_name_safe, "backup dump TOC inspection is supported for pgcustom dumps only"))
            dump_summaries.append(DumpTocSummary(dump_file=dump_name_safe, dump_format=dump_format, dump_contents_read=False))
            continue
        if container is None:
            container = inspect_owned_postgres_container(runtime_plan, runner)
        cmd = planned_pg_restore_list_command(runtime_plan)
        if run_pg_restore_list is globals().get("run_pg_restore_list"):
            raw_toc_bytes = _run_pg_restore_list_bytes(runtime_plan, dump_path, cmd, runner)
            toc_text = decode_process_output(raw_toc_bytes)
        else:
            toc_out: Any = run_pg_restore_list(runtime_plan, dump_path, cmd, runner)
            raw_toc_bytes = toc_out if isinstance(toc_out, bytes) else str(toc_out).encode("utf-8")
            toc_text = decode_process_output(toc_out)
        summary = summarize_pg_restore_toc(toc_text, dump_file=dump_name_safe, dump_format=dump_format)
        dump_summaries.append(summary)
        is_v2 = manifest.get("backup_format_version") == BACKUP_FORMAT_VERSION
        if is_v2:
            db_for_dump = _database_for_dump_name(manifest, dump_name_safe)
            catalogs = manifest.get("database_catalogs")
            db_cat = catalogs.get(db_for_dump) if isinstance(catalogs, Mapping) and db_for_dump else None
            if isinstance(db_cat, Mapping) and db_for_dump:
                try:
                    toc_obs = parse_and_verify_toc_provenance(raw_toc_bytes, database=db_for_dump, database_catalog=db_cat)
                    _verify_manifest_toc_binding(manifest, database=db_for_dump, dump_file=dump_name_safe, toc_sha256=toc_obs.toc_sha256)
                except LocalDbBackupError as error:
                    diagnostics.extend(error.diagnostics)
                    manifest = _mark_manifest_toc_inconsistent(manifest)
            else:
                diagnostics.append(LocalRuntimeDiagnostic("error", "backup-toc-inconsistent", dump_name_safe, "missing database catalog for dump"))
                manifest = _mark_manifest_toc_inconsistent(manifest)
        for ext in summary.extensions:
            if ext == "plpgsql":
                continue
            if not is_v2 or not resolved_policy.allow_extension_v2:
                manifest = _mark_manifest_blocker(_mark_manifest_blocker(manifest, "extension-not-allowlisted"), "extension-restore-protocol-unimplemented")
            elif resolved_policy.rule_for(ext) is None:
                manifest = _mark_manifest_blocker(manifest, "extension-not-allowlisted")
    return BackupInspectResult(
        repo_map_home=home,
        backups_root=backups_root,
        manifest_path=manifest_path,
        manifest=manifest,
        dump_summaries=tuple(dump_summaries),
        checksum_verified=bool(checksum_results) and all(checksum_results),
        diagnostics=tuple(diagnostics),
        container=container,
    )


def _database_for_dump_name(manifest: Mapping[str, Any], dump_name: str) -> str | None:
    if isinstance(manifest.get("database"), str):
        return str(manifest["database"])
    if dump_name.endswith(".pgcustom"):
        return dump_name[: -len(".pgcustom")]
    return None


def _verify_manifest_toc_binding(
    manifest: Mapping[str, Any], *, database: str, dump_file: str, toc_sha256: str
) -> None:
    art = manifest.get("artifact_provenance")
    bindings = art.get("archive_bindings") if isinstance(art, Mapping) else None
    if isinstance(bindings, list):
        for binding in bindings:
            if (
                isinstance(binding, Mapping)
                and binding.get("database") == database
                and binding.get("dump_file") == dump_file
            ):
                if binding.get("toc_sha256") != toc_sha256:
                    raise provenance_error("backup-toc-inconsistent", database, "archive TOC digest mismatch")
                return
    raise provenance_error("backup-toc-inconsistent", database, "archive TOC binding missing in manifest")


def _mark_manifest_blocker(manifest: Mapping[str, Any], blocker: str) -> dict[str, Any]:
    updated = dict(manifest)
    raw = updated.get("restore_blockers")
    blockers = {str(b) for b in raw if isinstance(b, str)} if isinstance(raw, list) else set()
    blockers.add(blocker)
    updated["restore_blockers"] = sorted(blockers)
    updated["restore_supported"] = False
    return updated


def _mark_manifest_toc_inconsistent(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return _mark_manifest_blocker(manifest, "backup-toc-inconsistent")


def _run_pg_restore_list_bytes(
    plan: LocalRuntimePlan,
    dump_path: Path,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> bytes:
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        import os

        secret = runtime_postgres_password(plan)
        env = dict(os.environ, PGPASSWORD=secret)
        return run_bounded_popen(
            command,
            max_output_bytes=MAX_TOC_OUTPUT_BYTES,
            timeout_seconds=DEFAULT_TOC_TIMEOUT_SECONDS,
            error_code="backup-toc-inconsistent",
            field=dump_path.name,
            secret=secret,
            env=env,
            stdin_path=dump_path,
        )
    try:
        with dump_path.open("rb") as input_stream:
            result = run_container_command(
                plan,
                command,
                command_runner,
                label="pg_restore -l",
                input_stream=input_stream,
            )
    except OSError as exc:
        raise provenance_error(
            "backup-toc-inconsistent",
            dump_path.name,
            "failed to open archive for TOC check",
        ) from exc
    raw = (
        result.stdout
        if isinstance(result.stdout, bytes)
        else decode_process_output(result.stdout).encode("utf-8")
    )
    if len(raw) > MAX_TOC_OUTPUT_BYTES:
        raise provenance_error("backup-toc-inconsistent", dump_path.name, "TOC output exceeded ceiling")
    return raw


def run_pg_restore_list(
    plan: LocalRuntimePlan,
    dump_path: Path,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> str:
    return decode_process_output(_run_pg_restore_list_bytes(plan, dump_path, command, command_runner))


def verify_archive_toc_for_restore(
    plan: LocalRuntimePlan,
    manifest: Mapping[str, Any],
    *,
    database: str,
    dump_path: Path,
    command_runner: CommandRunner,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
    **_ignored: Any,
) -> None:
    resolved_policy = resolve_extension_restore_policy(extension_restore_policy)
    raw_toc_bytes = _run_pg_restore_list_bytes(
        plan,
        dump_path,
        planned_pg_restore_list_command(plan),
        command_runner,
    )
    toc_obs = parse_toc_entries(raw_toc_bytes, database=database)
    toc_text = decode_process_output(raw_toc_bytes)
    summary = summarize_pg_restore_toc(
        toc_text, dump_file=dump_path.name, dump_format="pgcustom"
    )
    is_v2 = manifest.get("backup_format_version") == BACKUP_FORMAT_VERSION
    toc_exts = (*summary.extensions, *toc_obs.extensions)
    if any(
        ext != "plpgsql" and (not is_v2 or not resolved_policy.allow_extension_v2 or resolved_policy.rule_for(ext) is None)
        for ext in toc_exts
    ):
        raise_for_unsupported_restore(
            BackupSupportEvaluation(
                restore_protocol=CORE_V1_RESTORE_PROTOCOL,
                restore_supported=False,
                restore_blockers=(
                    "extension-not-allowlisted",
                    "extension-restore-protocol-unimplemented",
                ),
                extension_census_state="unknown",
            ),
            target=database,
        )
    if is_v2:
        catalogs = manifest.get("database_catalogs")
        db_cat = catalogs.get(database) if isinstance(catalogs, Mapping) else None
        if not isinstance(db_cat, Mapping):
            raise provenance_error("backup-toc-inconsistent", database, "missing database catalog")
        toc_obs = parse_and_verify_toc_provenance(
            raw_toc_bytes, database=database, database_catalog=db_cat
        )
        _verify_manifest_toc_binding(
            manifest, database=database, dump_file=dump_path.name, toc_sha256=toc_obs.toc_sha256
        )


def verify_drop_backup(
    backup_result: LocalDbBackupResult,
    database: str,
    *,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> None:
    manifest = read_manifest_file(backup_result.plan.manifest_path)
    dump_file = select_dump_file_for_database(manifest, database)
    verify_dump_file_checksum(
        backup_result.plan.backup_path / dump_file["name"],
        dump_file,
    )
    require_backup_restore_supported(
        manifest,
        database=database,
        require_quiescence=True,
        target=database,
        extension_restore_policy=extension_restore_policy,
    )
    if not backup_result.plan.restore_path.is_file():
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-restore-note-missing",
                    str(backup_result.plan.restore_path),
                    "backup restore note is missing; drop did not run",
                ),
            )
        )
