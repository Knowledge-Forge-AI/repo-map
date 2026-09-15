"""Text table formatters for local database backup results."""

from __future__ import annotations

from typing import Any


def format_backup_result_table(result: Any) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap local DB {payload['command']}: result={payload['result']}",
        f"backup_id={payload['backup_id']}",
        f"database={payload['database']} databases={','.join(payload['databases'])}",
        (
            "safety: "
            f"direct_db_required={str(payload['direct_db_required']).lower()} "
            f"destructive_db_actions={str(payload['destructive_db_actions']).lower()} "
            f"dump_executed={str(payload['dump_executed']).lower()}"
        ),
    ]
    if payload["dump_files"]:
        lines.append(
            "dump_files="
            + ", ".join(item["name"] for item in payload["dump_files"])
        )
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)


def format_backup_listing_table(result: Any) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap local DB backups: count={payload['backup_count']}",
        "backup_id | kind | database | timestamp | total_bytes | restore_supported",
    ]
    for backup in payload["backups"]:
        lines.append(
            " | ".join(
                [
                    str(backup.get("backup_id")),
                    str(backup.get("backup_kind")),
                    str(backup.get("database") or ",".join(backup.get("databases") or [])),
                    str(backup.get("timestamp")),
                    str(backup.get("total_bytes")),
                    str(backup.get("restore_supported")).lower(),
                ]
            )
        )
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)


def format_backup_info_table(result: Any) -> str:
    payload = result.to_jsonable()
    manifest = payload["manifest"]
    return "\n".join(
        [
            "RepoMap local DB backup info",
            f"backup_id={manifest.get('backup_id')}",
            f"kind={manifest.get('backup_kind')}",
            f"database={manifest.get('database')}",
            f"timestamp={manifest.get('timestamp')}",
            f"restore_supported={str(manifest.get('restore_supported')).lower()}",
        ]
    )


def format_backup_inspect_table(result: Any) -> str:
    payload = result.to_jsonable()
    expected = payload["expected_repomap_tables"]
    present = sorted(table for table, included in expected.items() if included)
    missing = sorted(table for table, included in expected.items() if not included)
    lines = [
        "RepoMap local DB backup inspect",
        f"backup_id={payload['backup_id']}",
        f"kind={payload['backup_kind']}",
        f"database={payload['database']}",
        f"restore_supported={str(payload['restore_supported']).lower()}",
        f"checksum_verified={str(payload['checksum_verified']).lower()}",
        f"dump_contents_read={str(payload['dump_contents_read']).lower()}",
        f"toc_entries={payload['toc_entry_count']}",
        f"tables={payload['table_count']} table_data={payload['table_data_count']}",
        f"expected_present={','.join(present)}",
        f"expected_missing={','.join(missing)}",
    ]
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)


def format_init_result_table(result: Any) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap local DB init: result={payload['result']}",
        f"database={payload['database']}",
        f"source_mode={payload['source_mode']}",
        f"target_existed={str(payload['target_existed']).lower()}",
        (
            "safety: "
            f"direct_db_required={str(payload['direct_db_required']).lower()} "
            f"destructive_db_actions={str(payload['destructive_db_actions']).lower()} "
            f"database_created={str(payload['database_created']).lower()} "
            f"schema_initialized={str(payload['schema_initialized']).lower()} "
            f"dump_restored={str(payload['dump_restored']).lower()} "
            f"schema_ready={str(payload['schema_ready']).lower()}"
        ),
    ]
    if payload["backup_id"]:
        lines.append(f"backup_id={payload['backup_id']}")
    if payload["dump_file"]:
        lines.append(f"dump_file={payload['dump_file']}")
    if payload["planned_actions"]:
        lines.append("planned_actions=" + ",".join(payload["planned_actions"]))
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)


def format_drop_result_table(result: Any) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap local DB drop: result={payload['result']}",
        f"database={payload['database']}",
        f"backup_first={str(payload['backup_first']).lower()}",
        f"confirmation_received={str(payload['confirmation_received']).lower()}",
        f"target_existed={str(payload['target_existed']).lower()}",
        f"backup_id={payload['backup_id']}",
        f"restore_command={payload['restore_command_hint']}",
        (
            "safety: "
            f"checksum_verified={str(payload['checksum_verified']).lower()} "
            f"restore_note_verified={str(payload['restore_note_verified']).lower()} "
            f"database_dropped={str(payload['database_dropped']).lower()} "
            f"direct_db_required={str(payload['direct_db_required']).lower()} "
            f"destructive_db_actions={str(payload['destructive_db_actions']).lower()}"
        ),
    ]
    if payload["planned_actions"]:
        lines.append("planned_actions=" + ",".join(payload["planned_actions"]))
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)
