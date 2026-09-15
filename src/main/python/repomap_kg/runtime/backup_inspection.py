"""Read-only inspection and verification for RepoMap backups."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from repomap_kg.ops.config import resolve_repo_map_home
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
) -> BackupInspectResult:
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
            diagnostics.append(
                LocalRuntimeDiagnostic(
                    "warning",
                    "backup-dump-metadata-invalid",
                    "dump_files",
                    "backup dump metadata entry is not an object",
                )
            )
            checksum_results.append(False)
            continue
        dump_name = safe_dump_file_name(dump_file.get("name"))
        dump_path, dump_name_safe = resolve_dump_file_for_inspection(
            backup_dir,
            dump_file,
        )
        if dump_path is None:
            diagnostics.append(
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-dump-name-unsafe",
                    dump_name,
                    "backup dump file name is not safe for inspection",
                )
            )
            checksum_results.append(False)
            continue
        checksum_ok, checksum_diagnostics = verify_dump_file_checksum_for_inspection(
            dump_path,
            dump_file,
            dump_name_safe,
        )
        diagnostics.extend(checksum_diagnostics)
        checksum_results.append(checksum_ok)
        dump_format = str(manifest_dump_format or infer_dump_format(dump_name_safe))
        if not checksum_ok:
            continue
        if dump_format != "pgcustom":
            diagnostics.append(
                LocalRuntimeDiagnostic(
                    "warning",
                    "backup-dump-toc-unsupported",
                    dump_name_safe,
                    "backup dump TOC inspection is supported for pgcustom dumps only",
                )
            )
            dump_summaries.append(
                DumpTocSummary(
                    dump_file=dump_name_safe,
                    dump_format=dump_format,
                    dump_contents_read=False,
                )
            )
            continue
        if container is None:
            container = inspect_owned_postgres_container(runtime_plan, runner)
        toc_text = run_pg_restore_list(
            runtime_plan,
            dump_path,
            planned_pg_restore_list_command(runtime_plan),
            runner,
        )
        dump_summaries.append(
            summarize_pg_restore_toc(
                toc_text,
                dump_file=dump_name_safe,
                dump_format=dump_format,
            )
        )
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


def run_pg_restore_list(
    plan: LocalRuntimePlan,
    dump_path: Path,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> str:
    result = run_container_command(
        plan,
        command,
        command_runner,
        label="pg_restore -l",
        input_data=dump_path.read_bytes(),
    )
    return decode_process_output(result.stdout)


def verify_drop_backup(
    backup_result: LocalDbBackupResult,
    database: str,
) -> None:
    manifest = read_manifest_file(backup_result.plan.manifest_path)
    dump_file = select_dump_file_for_database(manifest, database)
    verify_dump_file_checksum(
        backup_result.plan.backup_path / dump_file["name"],
        dump_file,
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
