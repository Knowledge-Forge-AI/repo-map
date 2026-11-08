"""Real retained artifacts and PostgreSQL proof refuse races and mismatches."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from common_lore_index.ops import retained_attempt_recovery as recovery
from common_lore_index.ops import _retained_attempt_record as records
from common_lore_index.ops._retained_attempt_record import BACKUP_NAME
from common_lore_index.ops._server_retention_lock import ServerRetentionLock
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.server_retained_recovery_fixture import (
    prepare_retained_server, publish_unsettled,
)


def test_real_database_binding_mismatches_and_unavailability_leave_metadata_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-custody")
        original = capture.result_path.read_bytes()
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            run = connection.execute(
                "SELECT id, source_generation, portable_stage_id, publication_bundle_id, publication_job_id "
                "FROM public.runs WHERE publication_job_id = %s", ("retained-custody",),
            ).fetchone()
        assert run is not None
        for statement, invalid, previous in (
            ("UPDATE public.runs SET source_generation = %s WHERE id = %s", "sg1:changed", run[1]),
            ("UPDATE public.runs SET portable_stage_id = %s WHERE id = %s", "stage-" + "f" * 48, run[2]),
            ("UPDATE public.runs SET publication_bundle_id = %s WHERE id = %s", "bundle1:" + "f" * 64, run[3]),
            ("UPDATE public.runs SET publication_job_id = %s WHERE id = %s", "different-job", run[4]),
        ):
            with psycopg.connect(conninfo) as connection:
                connection.execute(statement, (invalid, run[0]))
            try:
                outcome = recovery.recover_server_retained_attempt(
                    fixture.config, fixture.graph.id, "retained-custody", 1,
                    settle=True, psql_command=postgres.psql_command,
                )
                assert outcome.exit_code == 1 and outcome.result == "held"
                assert capture.result_path.read_bytes() == original
                assert not (capture.result_path.parent / BACKUP_NAME).exists()
            finally:
                with psycopg.connect(conninfo) as connection:
                    connection.execute(statement, (previous, run[0]))

        with psycopg.connect(conninfo) as connection:
            repository = connection.execute(
                "SELECT repo.id, repo.repository_identity FROM public.repositories repo "
                "JOIN public.runs run ON run.repository_id = repo.id WHERE run.id = %s", (run[0],),
            ).fetchone()
        assert repository is not None
        with psycopg.connect(conninfo) as connection:
            connection.execute(
                "UPDATE public.repositories SET repository_identity = %s WHERE id = %s",
                ("repo1:foreign-graph", repository[0]),
            )
        try:
            foreign = recovery.recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-custody", 1,
                settle=True, psql_command=postgres.psql_command,
            )
            assert foreign.result == "held" and foreign.publication_proof == "invalid"
            assert capture.result_path.read_bytes() == original
        finally:
            with psycopg.connect(conninfo) as connection:
                connection.execute(
                    "UPDATE public.repositories SET repository_identity = %s WHERE id = %s",
                    (repository[1], repository[0]),
                )

        bundle = capture.store.object_path(capture.bundle_reference)
        retained_bundle = capture.result_path.parent / "bundle-missing-test"
        bundle.rename(retained_bundle)
        try:
            missing = recovery.recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-custody", 1,
                settle=True, psql_command=postgres.psql_command,
            )
            assert missing.result == "held" and missing.artifact_proof == "invalid"
            assert capture.result_path.read_bytes() == original
        finally:
            retained_bundle.rename(bundle)

        unavailable = recovery.recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-custody", 1,
            settle=True, psql_command="nonexistent-retained-readback",
        )
        assert unavailable.result == "held" and unavailable.publication_proof == "unavailable"
        assert capture.result_path.read_bytes() == original
        for graph, operation in (("unknown-graph", "retained-custody"), (fixture.graph.id, "foreign-operation")):
            refused = recovery.recover_server_retained_attempt(
                fixture.config, graph, operation, 1, settle=True, psql_command=postgres.psql_command,
            )
            assert refused.exit_code == 1
            assert capture.result_path.read_bytes() == original


def test_real_proof_cannot_replace_a_cooperating_writer_new_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-race")
        original = capture.result_path.read_bytes()
        inode = capture.result_path.stat().st_ino
        original_proof = recovery._proof

        def prove_then_replace(*args, **kwargs):
            matched = original_proof(*args, **kwargs)
            assert matched
            with ServerRetentionLock(capture.result_path.parent.parent):
                temporary = capture.result_path.with_name("cooperating-writer.tmp")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, capture.result_path)
            return matched

        monkeypatch.setattr(recovery, "_proof", prove_then_replace)
        result = recovery.recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-race", 1,
            settle=True, psql_command=postgres.psql_command,
        )
        assert result.exit_code == 1 and result.reason == "metadata-race"
        assert capture.result_path.stat().st_ino != inode
        assert capture.result_path.read_bytes() == original
        assert not (capture.result_path.parent / BACKUP_NAME).exists()


def test_real_retained_namespace_and_record_refusals_never_settle_or_change_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-refusals")
        path = capture.result_path
        original = path.read_bytes()
        root = path.parent
        side = root / "owned-record-test-copy"
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            before = connection.execute("SELECT count(*), max(id) FROM public.runs").fetchone()
        bundle = capture.store.object_path(capture.bundle_reference)
        bundle_before = bundle.read_bytes()
        cases = (
            ("missing", "record-missing"), ("symlink", "unsafe-record"),
            ("hardlink", "unsafe-record"), ("record-mode", "unsafe-record"),
            ("directory-mode", "unsafe-record"), ("oversized", "unsafe-record"),
            ("malformed", "record-invalid"), ("non-utf8", "record-invalid"),
            ("duplicate", "record-invalid"), ("legacy", "legacy-record"),
            ("state", "record-invalid"), ("extra", "record-invalid"),
            ("reference", "record-invalid"), ("missing-receipt", "record-invalid"),
            ("unsettled-expiry", "record-invalid"), ("boolean-expiry", "record-invalid"),
            ("accepted-no-expiry", "record-invalid"), ("failed", "terminal-failed"),
        )
        for case, reason in cases:
            payload = json.loads(original)
            try:
                if case in {"missing", "symlink"}:
                    path.rename(side)
                    if case == "symlink":
                        path.symlink_to(side.name)
                elif case == "hardlink":
                    os.link(path, side)
                elif case == "record-mode":
                    path.chmod(0o644)
                elif case == "directory-mode":
                    root.chmod(0o755)
                elif case == "oversized":
                    path.write_bytes(b"x" * (records.RECORD_LIMIT + 1))
                elif case == "malformed":
                    path.write_bytes(b"{")
                elif case == "non-utf8":
                    path.write_bytes(b"\xff")
                elif case == "duplicate":
                    path.write_bytes(b'{"manifest_id":"first","manifest_id":"second"}')
                else:
                    if case == "legacy":
                        del payload["manifest"]
                    elif case == "state":
                        payload["retention_class"] = "running"
                    elif case == "extra":
                        payload["unexpected"] = "private-test-value"
                    elif case == "reference":
                        payload["bundle"] = []
                    elif case == "missing-receipt":
                        del payload["receipt"]
                    elif case == "unsettled-expiry":
                        payload["expires_at_epoch"] = 1
                    else:
                        payload["retention_class"] = "terminal-failed" if case == "failed" else "terminal-accepted"
                        if case != "accepted-no-expiry":
                            payload["expires_at_epoch"] = 1 if case == "failed" else True
                    path.write_bytes(json.dumps(payload).encode())
                before_inode = path.lstat() if case != "missing" else None
                outcome = recovery.recover_server_retained_attempt(
                    fixture.config, fixture.graph.id, "retained-refusals", 1,
                    settle=True, psql_command=postgres.psql_command,
                )
                assert outcome.result == "held" and outcome.reason == reason, case
                assert outcome.metadata_write_state == "not-attempted"
                assert not (root / BACKUP_NAME).exists()
                after_inode = path.lstat() if case != "missing" else None
                if before_inode is None:
                    assert after_inode is None
                else:
                    assert after_inode is not None
                    assert (after_inode.st_dev, after_inode.st_ino, after_inode.st_mode, after_inode.st_nlink, after_inode.st_size) == (
                        before_inode.st_dev, before_inode.st_ino, before_inode.st_mode, before_inode.st_nlink, before_inode.st_size,
                    )
                assert bundle.read_bytes() == bundle_before
                assert "private-test-value" not in str(outcome.to_jsonable())
            finally:
                root.chmod(0o700)
                if path.is_symlink():
                    path.unlink()
                if case in {"missing", "symlink"}:
                    side.rename(path)
                elif side.exists():
                    side.unlink()
                path.chmod(0o600)
                path.write_bytes(original)
        with psycopg.connect(conninfo) as connection:
            assert connection.execute("SELECT count(*), max(id) FROM public.runs").fetchone() == before


@pytest.mark.parametrize("sync_number", [1, 2])
def test_real_settlement_sync_failure_preserves_proof_and_supports_exact_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sync_number: int,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-sync")
        path = capture.result_path
        original = path.read_bytes()
        sync = records._sync_directory
        calls = 0

        def fail_selected_sync(directory: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == sync_number:
                raise OSError("private injected directory sync detail")
            sync(directory)

        with monkeypatch.context() as fault:
            fault.setattr(records, "_sync_directory", fail_selected_sync)
            result = recovery.recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-sync", 1,
                settle=True, psql_command=postgres.psql_command,
            )
        assert result.result == ("held" if sync_number == 1 else "uncertain")
        assert result.metadata_write_state == ("not-attempted" if sync_number == 1 else "uncertain")
        assert "private injected" not in str(result.to_jsonable())
        backup = path.parent / BACKUP_NAME
        assert backup.read_bytes() == original and stat.S_IMODE(backup.stat().st_mode) == 0o600
        before_retry = path.read_bytes()
        if sync_number == 1:
            assert before_retry == original
        else:
            assert json.loads(before_retry)["retention_class"] == "terminal-accepted"
        retried = recovery.recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-sync", 1,
            settle=True, psql_command=postgres.psql_command,
        )
        assert retried.result == ("settled" if sync_number == 1 else "already-settled")
        if sync_number == 2:
            assert path.read_bytes() == before_retry
        assert backup.read_bytes() == original
        assert not tuple(path.parent.glob(".portable-result.json.*.tmp"))


def test_real_record_close_failure_stays_categorical_and_closes_its_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-close")
        path = capture.result_path
        original = path.read_bytes()
        identity = path.stat()
        close = os.close
        closed: list[int] = []

        def close_then_fail(descriptor: int) -> None:
            details = os.fstat(descriptor)
            close(descriptor)
            if (details.st_dev, details.st_ino) == (identity.st_dev, identity.st_ino):
                closed.append(descriptor)
                raise OSError("private injected close detail")

        with monkeypatch.context() as fault:
            fault.setattr(records.os, "close", close_then_fail)
            result = recovery.recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-close", 1,
                settle=True, psql_command=postgres.psql_command,
            )
        assert result.result == "held" and result.reason == "record-unavailable"
        assert result.artifact_proof == "not-checked" and len(closed) == 1
        with pytest.raises(OSError):
            os.fstat(closed[0])
        assert path.read_bytes() == original
        assert not (path.parent / BACKUP_NAME).exists()
        assert "private injected close detail" not in str(result.to_jsonable())
