"""Shared support for local database backup unit tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path

from repomap_kg.runtime.plan import LocalRuntimeIdentity


class LocalDbBackupUnitTestCase(unittest.TestCase):
    @staticmethod
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

    @staticmethod
    def unexpected_runner(command, **kwargs):
        raise AssertionError(command)

    @staticmethod
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
