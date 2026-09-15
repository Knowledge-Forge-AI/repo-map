import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    dump_database,
    run_pg_restore,
)
from repomap_kg.runtime.backup_commands import backup_root
from repomap_kg.runtime.backup_manifests import (
    list_manifest_paths,
    resolve_backup_manifest_path,
)
from repomap_kg.runtime.backup_records import RuntimeContainerMetadata
from repomap_kg.runtime.local import setup_local_runtime


TIMESTAMP = "20260717T120000Z"
DUMP_BYTES = b"first-chunk\x00second-chunk\xffthird-chunk"


def _container() -> RuntimeContainerMetadata:
    return RuntimeContainerMetadata(
        container_id="container-id",
        name="repomap-postgres",
        image="postgres:16-alpine",
        labels={"org.repomap.component": "postgres"},
    )


def _final_backup_path(home: Path) -> Path:
    plan = setup_local_runtime(home).plan
    return backup_root(home) / plan.identity.home_hash / "repomap" / TIMESTAMP


def test_dump_streams_to_private_staging_then_atomically_publishes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    final_path = _final_backup_path(home)
    observed_streams: list[object] = []

    def runner(command, **kwargs):
        assert "/usr/bin/pg_dump" in command
        assert not final_path.exists()
        stream = kwargs["stdout"]
        assert stream is not subprocess.PIPE
        observed_streams.append(stream)
        stream.write(DUMP_BYTES[:13])
        stream.write(DUMP_BYTES[13:])
        return subprocess.CompletedProcess(command, 0, stdout=None, stderr=b"")

    previous_umask = os.umask(0)
    try:
        with patch(
            "repomap_kg.runtime.backup.inspect_owned_postgres_container",
            return_value=_container(),
        ):
            result = dump_database(
                home,
                database="repomap",
                timestamp=TIMESTAMP,
                command_runner=runner,
            )
    finally:
        os.umask(previous_umask)

    assert result.plan.backup_path == final_path
    assert len(observed_streams) == 1
    dump_path = final_path / "dump.pgcustom"
    manifest_path = final_path / "manifest.json"
    restore_path = final_path / "restore.md"
    assert dump_path.read_bytes() == DUMP_BYTES
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backup_format_version"] == 1
    assert manifest["dump_files"] == [
        {
            "name": "dump.pgcustom",
            "sha256": hashlib.sha256(DUMP_BYTES).hexdigest(),
            "size_bytes": len(DUMP_BYTES),
        }
    ]
    assert stat.S_IMODE(final_path.stat().st_mode) == 0o700
    for directory in (
        backup_root(home),
        final_path.parent.parent,
        final_path.parent,
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for artifact in (dump_path, manifest_path, restore_path):
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert not tuple(final_path.parent.glob(f".{TIMESTAMP}.*.incomplete"))


def test_manifest_failure_removes_staging_and_never_publishes_final_set(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    final_path = _final_backup_path(home)

    def runner(command, **kwargs):
        stream = kwargs["stdout"]
        if stream is not subprocess.PIPE:
            stream.write(DUMP_BYTES)
            return subprocess.CompletedProcess(command, 0, stdout=None, stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout=DUMP_BYTES, stderr=b"")

    with (
        patch(
            "repomap_kg.runtime.backup.inspect_owned_postgres_container",
            return_value=_container(),
        ),
        patch(
            "repomap_kg.runtime.backup.write_manifest_and_restore_docs",
            side_effect=RuntimeError("synthetic manifest failure"),
        ),
        pytest.raises(RuntimeError, match="synthetic manifest failure"),
    ):
        dump_database(
            home,
            database="repomap",
            timestamp=TIMESTAMP,
            command_runner=runner,
        )

    assert not final_path.exists()
    assert not tuple(final_path.parent.glob(f".{TIMESTAMP}.*.incomplete"))


def test_midstream_dump_failure_removes_partial_staging_artifact(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    final_path = _final_backup_path(home)

    def runner(command, **kwargs):
        stream = kwargs["stdout"]
        assert stream is not subprocess.PIPE
        stream.write(b"partial-private-dump")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=None,
            stderr=b"synthetic dump failure",
        )

    with (
        patch(
            "repomap_kg.runtime.backup.inspect_owned_postgres_container",
            return_value=_container(),
        ),
        pytest.raises(LocalDbBackupError, match="synthetic dump failure"),
    ):
        dump_database(
            home,
            database="repomap",
            timestamp=TIMESTAMP,
            command_runner=runner,
        )

    assert not final_path.exists()
    assert not tuple(final_path.parent.glob(f".{TIMESTAMP}.*.incomplete"))


def test_dump_refuses_duplicate_stream_and_returned_bytes_without_fallback(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    final_path = _final_backup_path(home)

    def runner(command, **kwargs):
        kwargs["stdout"].write(b"streamed")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"returned-again",
            stderr=b"",
        )

    with (
        patch(
            "repomap_kg.runtime.backup.inspect_owned_postgres_container",
            return_value=_container(),
        ),
        pytest.raises(LocalDbBackupError) as caught,
    ):
        dump_database(
            home,
            database="repomap",
            timestamp=TIMESTAMP,
            command_runner=runner,
        )

    assert caught.value.diagnostics[0].code == "pg-dump-stream-conflict"
    assert not final_path.exists()
    assert not tuple(final_path.parent.glob(f".{TIMESTAMP}.*.incomplete"))


def test_restore_passes_verified_dump_as_file_stream_not_whole_bytes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    plan = setup_local_runtime(home).plan
    dump_path = tmp_path / "dump.pgcustom"
    dump_path.write_bytes(DUMP_BYTES)
    chunks: list[bytes] = []

    def runner(command, **kwargs):
        assert "input" not in kwargs
        stream = kwargs["stdin"]
        while chunk := stream.read(7):
            chunks.append(chunk)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    run_pg_restore(
        plan,
        "repomap",
        dump_path,
        ("docker", "exec", "repomap-postgres", "pg_restore"),
        runner,
    )

    assert b"".join(chunks) == DUMP_BYTES
    assert len(chunks) > 1


def test_incomplete_staging_set_is_not_listed_or_resolvable(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    staging = root / "runtime" / "repomap" / ".timestamp.random.incomplete"
    staging.mkdir(parents=True)
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "backup_format_version": 1,
                "backup_id": "incomplete-backup",
                "dump_files": [],
            }
        ),
        encoding="utf-8",
    )

    assert list_manifest_paths(root) == ()
    with pytest.raises(LocalDbBackupError) as caught:
        resolve_backup_manifest_path(root, manifest_path)

    assert caught.value.diagnostics[0].code == "backup-not-found"
