"""Wire-level contracts for portable_worker.main driven over real descriptors."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.coordinator import portable_worker as pw
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability
from repomap_kg.coordinator._portable_semantic_adapter import (
    FailureReceiptWrite,
    PortableExecutionError,
)
from repomap_kg.coordinator._protocol_core import ProtocolError, encode_jsonl
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def _reference(media_type: str, fill: str) -> ArtifactReference:
    return ArtifactReference(
        "sha256:" + fill * 64,
        123,
        media_type,
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", f"objects/{fill * 2}/value", "filesystem-v1-abc"),
    )


MANIFEST = _reference("application/x-repomap-snapshot-manifest-v1+json", "a")
RECEIPT = _reference("application/x-repomap-extraction-receipt-v1+json", "c")
BUNDLE = _reference("application/x-repomap-publication-bundle-v1+jsonl", "d")
STORED = FailureReceiptWrite(RECEIPT, "stored", None)


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _capability(tmp_path: Path) -> PortableExecutionCapability:
    store, workspace = tmp_path / "store", tmp_path / "workspace"
    store.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    return PortableExecutionCapability(
        schema_version=1, job_id="job-123", attempt=1, graph_id="test-graph",
        store_root=store, workspace_root=workspace, manifest_reference=MANIFEST,
        source_generation="sg1:" + "1" * 64, config_generation="cg1:" + "2" * 64,
        extractor_generation="eg1:" + "3" * 64, canonicalizer_generation="kg1:" + "4" * 64,
        max_artifact_bytes=1024, max_bundle_bytes=4096,
    )


def _line(message: dict[str, object]) -> bytes:
    return json.dumps(message).encode("utf-8") + b"\n"


def _job_start(cap: PortableExecutionCapability, **overrides: object) -> bytes:
    message: dict[str, object] = {
        "schema_version": 1, "message_type": "job_start", "job_id": cap.job_id,
        "attempt": cap.attempt, "job_kind": "refresh_graph", "graph_id": cap.graph_id,
        "source_generation": cap.source_generation, "config_generation": cap.config_generation,
        "portable_snapshot": {
            "contract_version": "1.0", "required": True,
            "snapshot_manifest": MANIFEST.to_mapping(),
        },
    }
    message.update(overrides)
    return _line(message)


def _cancel(cap: PortableExecutionCapability) -> bytes:
    return _line({
        "schema_version": 1, "message_type": "cancel",
        "job_id": cap.job_id, "attempt": cap.attempt,
    })


def _result() -> SimpleNamespace:
    counts = {"raw_observations": 7, "canonical_nodes": 5, "canonical_edges": 4}
    return SimpleNamespace(
        bundle=SimpleNamespace(family_counts=counts),
        manifest=SimpleNamespace(total_files=3),
        receipt_reference=RECEIPT,
        bundle_reference=BUNDLE,
    )


def _wire(stdout: Any) -> list[dict[str, Any]]:
    data = os.pread(stdout.fileno(), 1 << 22, 0)
    return [json.loads(line) for line in data.splitlines()]


def _await_wire(stdout: Any, predicate: Callable[[list[dict[str, Any]]], bool]) -> None:
    deadline = time.monotonic() + 5.0
    while not predicate(_wire(stdout)):
        assert time.monotonic() < deadline, "expected wire message never appeared"
        time.sleep(0.01)


def _run(
    cap: PortableExecutionCapability,
    stdin: bytes,
    execute: Callable[..., Any] | None,
    stdout: Any,
    *,
    pipe_stdin: bool = False,
    receipt: FailureReceiptWrite = STORED,
    write: Callable[[dict[str, object]], None] | None = None,
    max_frame: int | None = None,
) -> SimpleNamespace:
    guard = Mock()
    create_receipt = Mock(return_value=receipt)
    extraction = Mock(side_effect=execute)
    stderr = io.StringIO()
    with ExitStack() as stack:
        if pipe_stdin:
            read_fd, write_fd = os.pipe()
            os.write(write_fd, stdin)
            stack.callback(os.close, read_fd)
            stack.callback(os.close, write_fd)
            stdin_handle: Any = SimpleNamespace(fileno=lambda: read_fd)
        else:
            stdin_handle = stack.enter_context(tempfile.TemporaryFile())
            stdin_handle.write(stdin)
            stdin_handle.flush()
            stdin_handle.seek(0)
        for name, value in (
            ("load_portable_capability", Mock(return_value=cap)),
            ("install_portable_authority_guard", guard),
            ("create_failure_receipt", create_receipt),
            ("execute_portable_extraction", extraction),
        ):
            stack.enter_context(patch.object(pw, name, value))
        stack.enter_context(patch.object(pw.sys, "stdin", stdin_handle))
        stack.enter_context(patch.object(pw.sys, "stdout", stdout))
        stack.enter_context(patch.object(pw.sys, "stderr", stderr))
        if write is not None:
            stack.enter_context(patch.object(pw, "_write", side_effect=write))
        if max_frame is not None:
            stack.enter_context(patch.object(pw, "MAX_JSONL_LINE_BYTES", max_frame))
        code = pw.main([
            "--capability", str(cap.workspace_root / "capability"),
            "--job-id", cap.job_id, "--attempt", str(cap.attempt),
        ])
    return SimpleNamespace(
        code=code, stderr=stderr.getvalue(), guard=guard,
        create_receipt=create_receipt, extraction=extraction,
    )


@pytest.fixture
def stdout() -> Iterator[Any]:
    with tempfile.TemporaryFile() as handle:
        yield handle


def test_worker_streams_progress_and_heartbeat_then_reports_success_terminal(
    tmp_path: Path, stdout: Any
) -> None:
    cap = _capability(tmp_path)
    seen: dict[str, object] = {}

    def execute(capability: object, *, emit_progress: Callable[..., None], cancel_event: Any) -> object:
        seen.update(capability=capability, cancelled=cancel_event.is_set())
        emit_progress("discovery", 1, 3)
        _await_wire(stdout, lambda wire: any(m["message_type"] == "heartbeat" for m in wire))
        return _result()

    run = _run(cap, _job_start(cap), execute, stdout, pipe_stdin=True)

    assert run.code == 0 and run.stderr == ""
    run.guard.assert_called_once_with(
        store_root=cap.store_root,
        workspace_root=cap.workspace_root,
        code_roots=(Path(pw.__file__).resolve().parents[2],),
    )
    run.create_receipt.assert_not_called()
    assert seen == {"capability": cap, "cancelled": False}
    wire = _wire(stdout)
    types = [message["message_type"] for message in wire]
    assert types[0] == "worker_hello" and types[-1] == "result"
    assert types.count("result") == 1 and "heartbeat" in types
    assert wire[0]["capabilities"] == ["refresh_graph", "portable_snapshot_v1"]
    progress = next(m for m in wire if m["message_type"] == "progress")
    assert (progress["phase"], progress["completed"], progress["total"], progress["unit"]) == (
        "discovery", 1, 3, "files",
    )
    heartbeat = next(m for m in wire if m["message_type"] == "heartbeat")
    assert (heartbeat["job_id"], heartbeat["attempt"]) == (cap.job_id, cap.attempt)
    terminal = wire[-1]
    assert (terminal["status"], terminal["error_category"], terminal["publication_state"]) == (
        "succeeded", None, "not_started",
    )
    assert (terminal["files"], terminal["observations"]) == (3, 7)
    assert (terminal["canonical_nodes"], terminal["canonical_edges"]) == (5, 4)
    assert terminal["latest_run_identity"] is None
    assert terminal["portable_snapshot"] == {
        "contract_version": "1.0", "outcome": "completed",
        "receipt": _json(RECEIPT.to_mapping()), "receipt_status": "stored",
        "receipt_diagnostic": None, "bundle": _json(BUNDLE.to_mapping()),
    }


@pytest.mark.parametrize("finish", ("raise", "complete"))
def test_accepted_cancellation_acknowledges_then_wins_over_extraction_outcome(
    tmp_path: Path, stdout: Any, finish: str
) -> None:
    cap = _capability(tmp_path)

    def execute(capability: object, *, emit_progress: Callable[..., None], cancel_event: Any) -> object:
        assert cancel_event.wait(5.0)
        if finish == "raise":
            raise PortableExecutionError("cancelled")
        return _result()

    run = _run(cap, _job_start(cap) + _cancel(cap), execute, stdout)

    assert run.code == 0 and run.stderr == ""
    wire = _wire(stdout)
    types = [message["message_type"] for message in wire]
    acknowledgements = [m for m in wire if m["message_type"] == "cancel_ack"]
    assert [m["status"] for m in acknowledgements] == ["accepted"]
    assert types.index("cancel_ack") < types.index("result")
    terminal = wire[-1]
    assert terminal["message_type"] == "result" and types.count("result") == 1
    assert (terminal["status"], terminal["error_category"]) == ("cancelled", None)
    assert terminal["publication_state"] == "not_started"
    assert terminal["portable_snapshot"] == {
        "contract_version": "1.0", "outcome": "cancelled",
        "receipt": _json(RECEIPT.to_mapping()), "receipt_status": "stored",
        "receipt_diagnostic": None, "bundle": None,
    }
    run.create_receipt.assert_called_once_with(cap, "cancelled", cancellation_requested=True)


@pytest.mark.parametrize(
    ("error", "category", "cause"),
    (
        (PortableExecutionError("artifact_stale"), "artifact_stale", "source_capture"),
        (PermissionError("portable worker runtime authority denied"),
         "unsupported_capability", "helper_launch_denied"),
        (PermissionError("portable worker filesystem authority denied"),
         "unsupported_capability", "filesystem_capture_denied"),
        (ValueError("invalid capability"), "contract_validation", "contract_validation"),
        (FileNotFoundError("gone"), "source_capture", "source_capture"),
        (RuntimeError("boom"), "semantic_workload", "semantic_workload"),
        (ProtocolError("invalid_frame"), "malformed_protocol", "malformed_protocol"),
    ),
)
def test_extraction_failure_emits_sanitized_category_terminal_with_stored_receipt(
    tmp_path: Path, stdout: Any, error: Exception, category: str, cause: str
) -> None:
    cap = _capability(tmp_path)

    def execute(capability: object, **_kwargs: object) -> object:
        raise error

    run = _run(cap, _job_start(cap), execute, stdout)

    assert run.code == 0
    assert run.stderr == f"refresh-failure:portable-worker:{cause}\n"
    run.create_receipt.assert_called_once_with(cap, category, cancellation_requested=False)
    terminal = _wire(stdout)[-1]
    assert terminal["message_type"] == "error" and terminal["status"] == "failed"
    assert terminal["error_category"] == category
    assert (terminal["publication_state"], terminal["retryable"]) == ("not_started", False)
    assert terminal["portable_snapshot"] == {
        "contract_version": "1.0", "outcome": category,
        "receipt": _json(RECEIPT.to_mapping()), "receipt_status": "stored",
        "receipt_diagnostic": None, "bundle": None,
    }


def test_failure_terminal_reports_unavailable_receipt_diagnostic(
    tmp_path: Path, stdout: Any
) -> None:
    cap = _capability(tmp_path)

    def execute(capability: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    run = _run(
        cap, _job_start(cap), execute, stdout,
        receipt=FailureReceiptWrite(None, "unavailable", "write_failed"),
    )

    assert run.code == 0
    terminal = _wire(stdout)[-1]
    assert terminal["error_category"] == "semantic_workload"
    assert terminal["portable_snapshot"] == {
        "contract_version": "1.0", "outcome": "semantic_workload", "receipt": None,
        "receipt_status": "unavailable", "receipt_diagnostic": "write_failed", "bundle": None,
    }


def test_malformed_cancel_frame_withholds_terminal_and_exits_with_protocol_failure(
    tmp_path: Path, stdout: Any
) -> None:
    cap = _capability(tmp_path)

    def execute(capability: object, *, emit_progress: Callable[..., None], cancel_event: Any) -> object:
        assert cancel_event.wait(5.0)
        raise PortableExecutionError("cancelled")

    run = _run(cap, _job_start(cap) + b"not-json\n", execute, stdout)

    assert run.code == 2
    assert run.stderr == "refresh-failure:portable-worker:semantic_workload\n"
    assert {m["message_type"] for m in _wire(stdout)}.isdisjoint({"result", "error"})


def test_heartbeat_write_failure_withholds_terminal_and_exits_with_failure(
    tmp_path: Path, stdout: Any
) -> None:
    cap = _capability(tmp_path)
    attempted = threading.Event()

    def write(message: dict[str, object]) -> None:
        if message["message_type"] == "heartbeat":
            attempted.set()
            raise OSError("protocol output closed")
        os.write(stdout.fileno(), encode_jsonl(message))

    def execute(capability: object, **_kwargs: object) -> object:
        assert attempted.wait(5.0)
        return _result()

    run = _run(cap, _job_start(cap), execute, stdout, write=write)

    assert run.code == 2
    assert run.stderr == "refresh-failure:portable-worker:semantic_workload\n"
    assert {m["message_type"] for m in _wire(stdout)}.isdisjoint({"result", "error"})


@pytest.mark.parametrize("case", ("eof", "oversized", "foreign-identity"))
def test_refused_start_frame_exits_two_after_hello_without_running_extraction(
    tmp_path: Path, stdout: Any, case: str
) -> None:
    cap = _capability(tmp_path)
    stdin = {
        "eof": b"",
        "oversized": b"x" * 200,
        "foreign-identity": _job_start(cap, job_id="other-job"),
    }[case]

    run = _run(cap, stdin, None, stdout, max_frame=64 if case == "oversized" else None)

    assert run.code == 2
    assert run.stderr == "refresh-failure:portable-worker:malformed_protocol\n"
    run.extraction.assert_not_called()
    assert [m["message_type"] for m in _wire(stdout)] == ["worker_hello"]


def test_worker_exits_bounded_when_protocol_output_never_drains(tmp_path: Path) -> None:
    cap = _capability(tmp_path)
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    try:
        for size in (4096, 1):
            while True:
                try:
                    os.write(write_fd, b"x" * size)
                except BlockingIOError:
                    break
        started = time.monotonic()
        run = _run(cap, _job_start(cap), None, SimpleNamespace(fileno=lambda: write_fd))
        elapsed = time.monotonic() - started
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert run.code == 2
    assert run.stderr == "refresh-failure:portable-worker:semantic_workload\n"
    assert elapsed < 5.0
    run.extraction.assert_not_called()
