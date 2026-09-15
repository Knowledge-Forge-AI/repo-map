import hashlib
import json
import subprocess
from pathlib import Path

from repomap_kg.runtime.local import LocalRuntimeIdentity


def write_warc_config(
    path: Path,
    *,
    max_file_count: int = 10,
    max_total_payload_bytes: int = 1048576,
) -> Path:
    path.write_text(
        "\n".join(
            [
                "[source]",
                'id = "branch-contract-warc"',
                'type = "saved_page.archive"',
                'display_name = "Branch Contract WARC"',
                "",
                "[policy]",
                'status = "allowed"',
                "max_artifact_bytes = 1048576",
                f"max_file_count = {max_file_count}",
                "max_warc_records = 100",
                "max_record_bytes = 1048576",
                f"max_total_payload_bytes = {max_total_payload_bytes}",
                'retention_policy = "materialize-safe-payloads"',
                "requires_manual_review = false",
                "",
                "[artifact]",
                'path = "warc_artifacts/example.warc"',
                'kind = "warc"',
                'profile = "warc-local-archive"',
            ]
        ),
        encoding="utf-8",
    )
    return path


def warc_record(
    record_type: str,
    record_id: str,
    target_uri: str,
    body: bytes,
    *,
    content_type: str,
) -> bytes:
    headers = {
        "WARC-Type": record_type,
        "WARC-Record-ID": f"<{record_id}>",
        "WARC-Date": "2026-06-30T12:00:00Z",
        "WARC-Target-URI": target_uri,
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    return (
        b"WARC/1.1\r\n"
        + b"".join(f"{key}: {value}\r\n".encode("utf-8") for key, value in headers.items())
        + b"\r\n"
        + body
        + b"\r\n\r\n"
    )


def owned_container_result(identity: LocalRuntimeIdentity, command):
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            [
                {
                    "Id": "container-123",
                    "Config": {
                        "Image": "postgres:16-alpine",
                        "Labels": identity.labels("postgres"),
                    },
                }
            ]
        ),
        stderr="",
    )


def unexpected_runner(command, **kwargs):
    raise AssertionError(command)


def write_backup_fixture(
    home: Path,
    runtime_id: str,
    database: str,
    *,
    all_databases: bool = False,
) -> Path:
    if all_databases:
        backup_dir = home / "backups" / runtime_id / "all-databases" / "20260702T010203Z"
        dump_name = f"{database}.pgcustom"
        backup_kind = "manual-dump-all"
        database_value = None
        databases = [database]
        backup_id = f"{runtime_id}--all-databases--20260702T010203Z"
    else:
        backup_dir = home / "backups" / runtime_id / database / "20260702T010203Z"
        dump_name = "dump.pgcustom"
        backup_kind = "manual-dump"
        database_value = database
        databases = [database]
        backup_id = f"{runtime_id}--{database}--20260702T010203Z"
    backup_dir.mkdir(parents=True)
    content = f"{database}-dump".encode("utf-8")
    (backup_dir / dump_name).write_bytes(content)
    manifest = {
        "backup_format_version": 1,
        "backup_id": backup_id,
        "backup_kind": backup_kind,
        "runtime_id": runtime_id,
        "database": database_value,
        "databases": databases,
        "timestamp": "20260702T010203Z",
        "dump_files": [
            {
                "name": dump_name,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "dump_format": "pgcustom",
        "restore_supported": False,
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return backup_dir
