"""Cancellation safe points and settled refresh outcomes preserve publication."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from repomap_kg.coordinator import _publication_phase as phase, refresh_adapter, refresh_worker
from repomap_kg.coordinator._protocol_execution import SyntheticWorkerResult
from repomap_kg.coordinator.protocol import ProtocolError, encode_jsonl
from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_test_support.executable_authority import approved_psql, search_path_for


def _capability(root: Path) -> RefreshCapability:
    root.chmod(0o700)
    config = root / "ops.toml"
    config.write_text("version = 1\n", encoding="utf-8")
    config.chmod(0o600)
    psql = approved_psql(root)
    return RefreshCapability(
        schema_version=1, job_id="job-cancel", attempt=1, graph_id="synthetic-cancel",
        config_path=config, psql_path=psql, postgres_user="repomap_refresh_publication",
        postgres_password="test-only", executable_search_path=search_path_for(psql),
        source_generation="sg1:fixture", config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        coordinator_instance_id="owner-cancel", singleton_fencing_epoch=3,
        graph_lease_fencing_epoch=7,
    )


@pytest.mark.parametrize("when", ["dispatch", "before-publication", "committed", "uncertain"])
def test_worker_consumes_cancel_at_safe_points(tmp_path, monkeypatch, when):
    capability = _capability(tmp_path)
    path = create_refresh_capability(tmp_path, capability)
    phase.initialize(tmp_path, capability)
    identity = {"job_id": capability.job_id, "attempt": capability.attempt}
    start = encode_jsonl({
        "schema_version": 1, "message_type": "job_start", **identity,
        "job_kind": "refresh_graph", "graph_id": capability.graph_id,
        "source_generation": capability.source_generation,
        "config_generation": capability.config_generation,
    })
    cancel = encode_jsonl({"schema_version": 1, "message_type": "cancel", **identity})
    read_fd, write_fd = os.pipe()
    messages: list[dict[str, object]] = []
    operations = []

    def execute(_capability, *, before_publication):
        operations.append("semantic")
        if when == "before-publication":
            os.write(write_fd, cancel)
        before_publication()
        if when in {"committed", "uncertain"}:
            os.write(write_fd, cancel)
        if when == "uncertain":
            raise OSError("publication outcome unavailable")
        return SimpleNamespace(
            result="success", run_id=7, files=1, observations=0,
            started_at="2026-10-07T12:00:00Z", finished_at="2026-10-07T12:01:00Z",
        )

    with os.fdopen(read_fd, "rb") as stream:
        try:
            os.write(write_fd, start + (cancel if when == "dispatch" else b""))
            monkeypatch.setattr(refresh_worker.sys, "stdin", SimpleNamespace(buffer=stream, fileno=stream.fileno))
            monkeypatch.setattr(refresh_worker, "_write", messages.append)
            monkeypatch.setattr(refresh_worker, "execute_refresh", execute)
            assert refresh_worker.main([
                "--capability", str(path), "--job-id", capability.job_id, "--attempt", "1",
            ]) == 0
        finally:
            os.close(write_fd)
    terminal = messages[-1]
    ack = next(message for message in messages if message["message_type"] == "cancel_ack")
    if when in {"dispatch", "before-publication"}:
        assert terminal["status"] == "cancelled"
        assert terminal["publication_state"] == "not_started"
        assert ack["status"] == "accepted"
        assert not tuple(tmp_path.glob("publication-*.decision.json"))
        assert operations == ([] if when == "dispatch" else ["semantic"])
    elif when == "committed":
        assert terminal["status"] == "succeeded"
        assert terminal["publication_state"] == "committed"
        assert terminal["latest_run_identity"] == "run-7"
        assert terminal["diagnostics"] == ["cancellation_not_applied"]
        assert ack["status"] == "already-complete"
    else:
        assert terminal["status"] == "failed"
        assert terminal["publication_state"] == "commit_unknown"
        assert ack["status"] == "deferred"
        assert phase.publication_state(tmp_path, capability) == "commit_unknown"


@pytest.mark.parametrize("pending", ["none", "complete", "fragmented", "unterminated", "malformed", "eof"])
def test_real_pipe_pending_frame_contrast_at_publication_boundary(tmp_path, monkeypatch, pending):
    capability = _capability(tmp_path)
    path = create_refresh_capability(tmp_path, capability)
    phase.initialize(tmp_path, capability)
    identity = {"job_id": capability.job_id, "attempt": capability.attempt}
    start = encode_jsonl({
        "schema_version": 1, "message_type": "job_start", **identity,
        "job_kind": "refresh_graph", "graph_id": capability.graph_id,
        "source_generation": capability.source_generation, "config_generation": capability.config_generation,
    })
    cancel = encode_jsonl({"schema_version": 1, "message_type": "cancel", **identity})
    prefix, suffix = cancel[:len(cancel) // 2], cancel[len(cancel) // 2:]
    assert prefix + suffix == cancel  # well-formed logical frame, split in transit
    messages: list[dict[str, object]] = []
    publications = []
    read_fd, write_fd = os.pipe()

    def execute(_capability, *, before_publication):
        data = {"none": b"", "complete": cancel, "fragmented": prefix,
                "unterminated": cancel[:-1], "malformed": b"{invalid}\n", "eof": b""}[pending]
        if data:
            assert os.write(write_fd, data) == len(data)
        if pending == "eof":
            os.close(write_fd)
        before_publication()
        publications.append("published")
        return SimpleNamespace(
            result="success", run_id=7, files=1, observations=0,
            started_at="2026-10-07T12:00:00Z", finished_at="2026-10-07T12:01:00Z",
        )

    with os.fdopen(read_fd, "rb") as stream:
        try:
            assert os.write(write_fd, start) == len(start)
            monkeypatch.setattr(refresh_worker.sys, "stdin", SimpleNamespace(buffer=stream, fileno=stream.fileno))
            monkeypatch.setattr(refresh_worker, "_write", messages.append)
            monkeypatch.setattr(refresh_worker, "execute_refresh", execute)
            code = refresh_worker.main(["--capability", str(path), "--job-id", capability.job_id, "--attempt", "1"])
            if pending == "fragmented":
                # The remainder arrives after the failed decision boundary.
                assert os.write(write_fd, suffix) == len(suffix)
        finally:
            if pending != "eof":
                os.close(write_fd)
    assert stream.closed
    if pending in {"fragmented", "unterminated", "malformed"}:
        assert code == 2 and publications == []
        assert not any(message["message_type"] in {"result", "error", "cancel_ack"} for message in messages)
        assert not tuple(tmp_path.glob("publication-*.decision.json"))
    else:
        assert code == 0
        assert messages[-1]["status"] == ("cancelled" if pending == "complete" else "succeeded")
        assert publications == ([] if pending == "complete" else ["published"])


@pytest.mark.parametrize("damage", ["identity", "json", "partial", "duplicate"])
@pytest.mark.parametrize("when", ["dispatch", "wrapped-before-publication"])
def test_worker_rejects_invalid_cancel_even_when_storage_wraps_failure(tmp_path, monkeypatch, damage, when):
    capability = _capability(tmp_path)
    path = create_refresh_capability(tmp_path, capability)
    identity = {"job_id": capability.job_id, "attempt": capability.attempt}
    start = encode_jsonl({
        "schema_version": 1, "message_type": "job_start", **identity,
        "job_kind": "refresh_graph", "graph_id": capability.graph_id,
        "source_generation": capability.source_generation, "config_generation": capability.config_generation,
    })
    cancel = encode_jsonl({"schema_version": 1, "message_type": "cancel", **identity})
    damaged = {
        "identity": encode_jsonl({"schema_version": 1, "message_type": "cancel", **identity, "job_id": "other-job"}),
        "json": b"{invalid}\n", "partial": b'{"schema_version":', "duplicate": cancel + cancel,
    }[damage]
    messages: list[dict[str, object]] = []
    read_fd, write_fd = os.pipe()

    def execute(_capability, *, before_publication):
        assert when == "wrapped-before-publication", "semantic work started despite invalid dispatch"
        os.write(write_fd, damaged)
        try:
            before_publication()
        except ProtocolError:
            return SimpleNamespace(
                result="failure", publication_state="not_started",
                started_at="2026-10-07T12:00:00Z", finished_at="2026-10-07T12:01:00Z",
            )
        pytest.fail("invalid cancellation reached publication")

    with os.fdopen(read_fd, "rb") as stream:
        try:
            os.write(write_fd, start + (damaged if when == "dispatch" else b""))
            monkeypatch.setattr(refresh_worker.sys, "stdin", SimpleNamespace(buffer=stream, fileno=stream.fileno))
            monkeypatch.setattr(refresh_worker, "_write", messages.append)
            monkeypatch.setattr(refresh_worker, "execute_refresh", execute)
            assert refresh_worker.main([
                "--capability", str(path), "--job-id", capability.job_id, "--attempt", "1",
            ]) == 2
        finally:
            os.close(write_fd)
    assert not any(message["message_type"] in {"result", "error"} for message in messages)


@pytest.mark.parametrize("outcome", ["accepted-success", "unknown-cancel", "unproved-cancel"])
def test_adapter_cannot_relabel_committed_or_uncertain_publication_cancelled(tmp_path, monkeypatch, outcome):
    capability = _capability(tmp_path)
    path = create_refresh_capability(tmp_path, capability)
    terminal: dict[str, object] = {
        "status": "succeeded", "publication_state": "committed",
        "latest_run_identity": "run-7", "diagnostics": [], "error_category": None,
    } if outcome == "accepted-success" else {
        "status": "cancelled", "publication_state": "not_started", "latest_run_identity": None,
    }
    original = SyntheticWorkerResult(
        (), (), terminal, "", 0, False, 0, False, False, False, False, False,
        True, "posix-process-group", True, None, outcome == "unknown-cancel",
        original_terminal=terminal,
    )

    def execute(*_args, **_kwargs):
        if outcome != "unproved-cancel":
            phase.before_publication(tmp_path, capability)
        return original

    monkeypatch.setattr(refresh_adapter, "_run_protocol_worker", execute)
    cancel = threading.Event()
    cancel.set()
    result = refresh_adapter.run_refresh_worker(
        path, {"job_id": capability.job_id, "attempt": capability.attempt},
        {"process_deadline_seconds": 5, "refresh_attempt_deadline_seconds": 10},
        job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation,
                     "config_generation": capability.config_generation}, cancel_event=cancel,
    )
    if outcome == "accepted-success":
        assert result.terminal == terminal
        assert result.terminal["status"] == "succeeded"
        assert result.terminal["publication_state"] == "committed"
        assert result.terminal["latest_run_identity"] == "run-7"
    else:
        assert result.terminal["status"] == "failed"
        assert result.terminal["publication_state"] == "commit_unknown"
        assert result.terminal["error_category"] == "publication_unknown"
    assert not path.exists()
