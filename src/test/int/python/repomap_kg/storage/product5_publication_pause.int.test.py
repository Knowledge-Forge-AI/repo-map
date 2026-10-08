"""Real staged publication honors safe pause paths and consumer release."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from repomap_kg.runtime import system_test_pause
from repomap_kg.storage import _staged_publication_pause as pause_module
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.staged_ingestion import (
    new_direct_authority,
    run_staged_full_refresh,
)
from repomap_test_support.postgres_harness import temporary_postgres


def _refresh(postgres):
    return run_staged_full_refresh(
        postgres.psql_args,
        [],
        repository_name="pause-fixture",
        root_path="fixture-root",
        authority=new_direct_authority(
            source_generation="sg1:pause",
            config_generation="cg1:pause",
            extractor_generation="eg1:pause",
            canonicalizer_generation="kg1:pause",
        ),
    )


def _migrate(postgres):
    apply_migrations(
        default_rdbms_root(), postgres.psql_args,
        psql_command=postgres.psql_command,
    )


@pytest.mark.parametrize("checkpoint", ["STAGED", "POST_PUBLICATION"])
def test_consumer_release_keeps_publication_uncommitted_until_checkpoint(
    tmp_path, monkeypatch, checkpoint,
):
    pause = tmp_path / "publication-pause"
    ready = Path(f"{pause}.ready")
    pause.touch()
    monkeypatch.setenv(f"_REPOMAP_SYSTEM_TEST_{checkpoint}_PAUSE_PATH", str(pause))
    markers: list[dict[str, str]] = []
    failures: list[BaseException] = []
    producer_waiting = threading.Event()

    class ObservedClock:
        monotonic = staticmethod(time.monotonic)

        @staticmethod
        def sleep(seconds):
            producer_waiting.set()
            time.sleep(seconds)

    monkeypatch.setattr(pause_module, "time", ObservedClock)
    with temporary_postgres() as postgres:
        _migrate(postgres)

        def consume():
            try:
                deadline = time.monotonic() + 10
                marker: dict[str, str] = {}
                expected = {"pid", "job_id", "attempt", "handoff"} if checkpoint == "STAGED" else {"pid"}
                while not expected <= marker.keys():
                    if time.monotonic() >= deadline:
                        raise AssertionError("publication checkpoint never became ready")
                    if ready.exists():
                        content = ready.read_text()
                        if content.endswith("\n"):
                            marker = dict(line.split("=", 1) for line in content.splitlines())
                    threading.Event().wait(0.01)
                assert int(marker["pid"]) == os.getpid()
                assert producer_waiting.wait(timeout=2)
                assert ready.stat().st_mode & 0o777 == 0o600
                if checkpoint == "STAGED":
                    handoff = json.loads(marker["handoff"])
                    assert handoff["receipt"]["publication_job_id"] == marker["job_id"]
                    assert handoff["receipt"]["publication_attempt"] == int(marker["attempt"])
                else:
                    assert set(marker) == {"pid"}
                assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'complete'") == "0"
                assert postgres.psql_scalar("SELECT count(*) FROM ingestion_stages WHERE state = 'validated'") == "1"
                markers.append(marker)
            except BaseException as error:
                failures.append(error)
            finally:
                pause.unlink(missing_ok=True)

        consumer = threading.Thread(target=consume)
        consumer.start()
        try:
            summary = _refresh(postgres)
        finally:
            pause.unlink(missing_ok=True)
            consumer.join(timeout=12)
        assert not consumer.is_alive()
        assert not failures, [type(error).__name__ for error in failures]
        assert len(markers) == 1
        assert not ready.exists()
        assert summary.publication_receipt is not None
        assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'complete'") == "1"
        assert postgres.psql_scalar("SELECT count(*) FROM ingestion_stages WHERE state = 'published'") == "1"


@pytest.mark.parametrize("unsafe", [
    "relative", "symlink", "parent-symlink", "insecure-parent",
    "missing-parent", "existing-marker",
])
def test_unsafe_pause_paths_do_not_block_or_overwrite_publication(
    tmp_path, monkeypatch, unsafe,
):
    directory = tmp_path / "pause"
    directory.mkdir(mode=0o700)
    pause = directory / "trigger"
    sentinel = directory / "sentinel"
    sentinel.write_text("fixture-sentinel")
    if unsafe == "relative":
        monkeypatch.chdir(tmp_path)
        pause = Path("relative-publication-trigger")
        pause.touch()
    elif unsafe == "symlink":
        pause.symlink_to(sentinel)
    elif unsafe == "parent-symlink":
        link = tmp_path / "linked-pause"
        link.symlink_to(directory, target_is_directory=True)
        pause = link / "trigger"
        pause.touch()
    elif unsafe == "insecure-parent":
        directory.chmod(0o755)
        pause.touch()
    elif unsafe == "missing-parent":
        pause = tmp_path / "missing" / "trigger"
    ready = Path(f"{pause}.ready")
    if unsafe == "existing-marker":
        pause.touch()
        ready.write_text("existing-marker")
        ready.chmod(0o600)
    def refuse_wait(_seconds):
        raise AssertionError("unsafe path entered the publication pause window")
    monkeypatch.setattr(
        pause_module, "time", SimpleNamespace(monotonic=time.monotonic, sleep=refuse_wait),
    )
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(pause))
    with temporary_postgres() as postgres:
        _migrate(postgres)
        summary = _refresh(postgres)
        assert summary.publication_receipt is not None
        assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'complete'") == "1"
    assert sentinel.read_text() == "fixture-sentinel"
    if unsafe == "existing-marker":
        assert ready.read_text() == "existing-marker"
    else:
        assert not ready.exists()


@pytest.mark.parametrize("setting,value,message", [
    ("SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS", float("inf"), "finite and positive"),
    ("SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS", 25.0, "exceed consumer deadline"),
    ("SYSTEM_TEST_STATUS_TIMEOUT_SECONDS", 40.0, "strictly less"),
])
def test_invalid_consumer_budget_refuses_before_transaction_and_retires_stage(
    tmp_path, monkeypatch, setting, value, message,
):
    pause = tmp_path / "invalid-budget"
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(pause))
    monkeypatch.setattr(system_test_pause, setting, value)
    with temporary_postgres() as postgres:
        _migrate(postgres)
        with pytest.raises(ValueError, match=message):
            _refresh(postgres)
        assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'complete'") == "0"
        assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'failed'") == "1"
        assert postgres.psql_scalar("SELECT count(*) FROM ingestion_stages WHERE state = 'failed'") == "1"
    assert not Path(f"{pause}.ready").exists()
