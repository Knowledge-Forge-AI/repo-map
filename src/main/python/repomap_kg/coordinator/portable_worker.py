"""ASYNC1 portable-snapshot semantic worker process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import threading
import time

from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    load_portable_capability,
)
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
from repomap_kg.coordinator._protocol_validation import _utc_now as _utc_now
from repomap_kg.coordinator._portable_semantic_adapter import (
    FailureReceiptWrite,
    PortableExecutionError,
    create_failure_receipt,
    execute_portable_extraction,
)
from repomap_kg.coordinator._protocol_core import (
    MAX_JSONL_LINE_BYTES,
    encode_jsonl,
    ProtocolError,
    ProtocolSession,
    decode_jsonl,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        # Raw nonblocking pipes have no Python buffered locks to strand at exit.
        os.set_blocking(sys.stdin.fileno(), False)
        os.set_blocking(sys.stdout.fileno(), False)
        capability = load_portable_capability(Path(args.capability))
        if capability.job_id != args.job_id or capability.attempt != args.attempt:
            raise ValueError("invalid portable capability")
        install_portable_authority_guard(
            store_root=capability.store_root,
            workspace_root=capability.workspace_root,
            code_roots=(Path(__file__).resolve().parents[2],),
        )
        identity = {"job_id": capability.job_id, "attempt": capability.attempt}
        session = ProtocolSession(identity)
        lock = threading.Lock()
        hello = {
            "schema_version": 1,
            "message_type": "worker_hello",
            "protocol_versions": [1],
            "worker_generation": "portable-python-worker-v1",
            "capabilities": ["refresh_graph", "portable_snapshot_v1"],
            "process_nonce": "portable-worker-v1",
        }
        session.accept_worker(hello)
        _write(hello)
        start = session.accept_coordinator(
            decode_jsonl(_read_frame(threading.Event()))
        )
        started_at = _utc_now()
        extension = start.get("portable_snapshot")
        if not isinstance(extension, dict):
            terminal = _failure_terminal(
                identity, capability, started_at, "unsupported_contract"
            )
            session.accept_worker(terminal)
            _write(terminal)
            return 0
        try:
            supplied = ArtifactReference.from_mapping(extension["snapshot_manifest"])
        except (KeyError, TypeError, ValueError):
            terminal = _failure_terminal(
                identity, capability, started_at, "contract_validation"
            )
            session.accept_worker(terminal)
            _write(terminal)
            return 0
        if supplied.to_mapping() != capability.manifest_reference.to_mapping():
            terminal = _failure_terminal(
                identity, capability, started_at, "identity_mismatch"
            )
            session.accept_worker(terminal)
            _write(terminal)
            return 0
        if any(
            start[field] != expected
            for field, expected in (
                ("graph_id", capability.graph_id),
                ("source_generation", capability.source_generation),
                ("config_generation", capability.config_generation),
            )
        ):
            terminal = _failure_terminal(
                identity, capability, started_at, "identity_mismatch"
            )
            terminal.update(
                graph_id=start["graph_id"],
                source_generation=start["source_generation"],
                config_generation=start["config_generation"],
            )
            session.accept_worker(terminal)
            _write(terminal)
            return 0
        stop = threading.Event()
        cancel_event = threading.Event()
        lifecycle_failed = threading.Event()

        def emit(message: dict[str, object]) -> None:
            with lock:
                session.accept_worker(message)
                _write(message)

        def progress(phase: str, completed: int, total: int) -> None:
            emit(
                {
                    "schema_version": 1,
                    "message_type": "progress",
                    **identity,
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                    "unit": "files",
                    "message_category": "files-discovered",
                    "heartbeat_at": _utc_now(),
                }
            )

        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(session, identity, lock, stop, lifecycle_failed),
        )
        cancellation_reader = threading.Thread(
            target=_read_cancellation,
            args=(session, identity, lock, stop, cancel_event, lifecycle_failed),
        )
        heartbeat.start()
        cancellation_reader.start()
        try:
            result = execute_portable_extraction(
                capability,
                emit_progress=progress,
                cancel_event=cancel_event,
            )
            counts = result.bundle.family_counts
            terminal = _terminal_payload(
                identity, capability, started_at, "succeeded", "completed", None,
                "result", result.receipt_reference,
            )
            terminal.update(files=result.manifest.total_files, observations=counts["raw_observations"],
                            canonical_nodes=counts["canonical_nodes"], canonical_edges=counts["canonical_edges"])
            extension = terminal["portable_snapshot"]
            assert isinstance(extension, dict)
            extension["bundle"] = result.bundle_reference.to_mapping()
        except PortableExecutionError as error:
            if error.category == "cancelled" or cancel_event.is_set():
                terminal = _cancellation_terminal(identity, capability, started_at)
            else:
                _emit_failure_stderr(error)
                terminal = _failure_terminal(identity, capability, started_at, error.category)
        except (KeyError, OSError, TypeError, ValueError, ProtocolError, RuntimeError) as error:
            _emit_failure_stderr(error)
            terminal = _failure_terminal(
                identity, capability, started_at, _execution_error_category(error),
            )
        finally:
            stop.set()
            heartbeat.join(timeout=1.0)
            cancellation_reader.join(timeout=1.0)
        if heartbeat.is_alive() or cancellation_reader.is_alive() or lifecycle_failed.is_set():
            raise RuntimeError("worker protocol threads did not settle")
        # The reader may accept an already-written cancel during settlement.
        # Decide only after it has drained pending input and acknowledged it.
        if cancel_event.is_set() and terminal["status"] != "cancelled":
            terminal = _cancellation_terminal(identity, capability, started_at)
        emit(terminal)
        return 0
    except (KeyError, OSError, TypeError, ValueError, ProtocolError, RuntimeError) as error:
        _emit_failure_stderr(error)
        return 2


def _heartbeat_loop(session, identity, lock, stop, lifecycle_failed) -> None:
    while not stop.wait(0.25):
        message = {
            "schema_version": 1,
            "message_type": "heartbeat",
            **identity,
            "heartbeat_at": _utc_now(),
        }
        with lock:
            try:
                session.accept_worker(message)
                _write(message)
            except (ProtocolError, OSError, RuntimeError):
                lifecycle_failed.set()
                return


def _read_cancellation(session, identity, lock, stop, cancel_event, lifecycle_failed) -> None:
    try:
        frame = _read_frame(stop)
        if not frame:
            return
        with lock:
            session.accept_coordinator(decode_jsonl(frame))
            cancel_event.set()
            acknowledgement = {
                "schema_version": 1,
                "message_type": "cancel_ack",
                **identity,
                "status": "accepted",
            }
            session.accept_worker(acknowledgement)
            _write(acknowledgement)
    except ProtocolError:
        lifecycle_failed.set()
        cancel_event.set()
    except (OSError, RuntimeError):
        lifecycle_failed.set()
        cancel_event.set()


def _read_frame(stop: threading.Event) -> bytes:
    frame = bytearray()
    while True:
        try:
            # Do not prefetch cancellation bytes while reading job_start.
            byte = os.read(sys.stdin.fileno(), 1)
        except BlockingIOError:
            if stop.is_set():
                if frame:
                    raise ProtocolError("invalid_jsonl")
                return b""
            stop.wait(0.01)
            continue
        if not byte:
            return bytes(frame)
        frame.extend(byte)
        if byte == b"\n" or len(frame) > MAX_JSONL_LINE_BYTES:
            return bytes(frame)


def _terminal_payload(
    identity: dict[str, object],
    capability: PortableExecutionCapability,
    started_at: str,
    status: str,
    outcome: str,
    error_category: str | None,
    message_type: str,
    receipt_ref: ArtifactReference | FailureReceiptWrite | None = None,
    cancellation_requested: bool = False,
) -> dict[str, object]:
    if receipt_ref is None:
        receipt_ref = create_failure_receipt(
            capability, outcome, cancellation_requested=cancellation_requested
        )
    receipt_write = _receipt_write(receipt_ref)
    return {
        "schema_version": 1,
        "message_type": message_type,
        **identity,
        "job_kind": "refresh_graph",
        "graph_id": capability.graph_id,
        "status": status,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "phase": "complete",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": [],
        "publication_state": "not_started",
        "latest_run_identity": None,
        "source_generation": capability.source_generation,
        "config_generation": capability.config_generation,
        "extractor_generation": capability.extractor_generation,
        "canonicalizer_generation": capability.canonicalizer_generation,
        "retryable": False,
        "error_category": error_category,
        "portable_snapshot": {
            "contract_version": "1.0",
            "outcome": outcome,
            "receipt": (
                receipt_write.reference.to_mapping()
                if receipt_write.reference is not None
                else None
            ),
            "receipt_status": receipt_write.status,
            "receipt_diagnostic": receipt_write.diagnostic,
            "bundle": None,
        },
    }


def _cancellation_terminal(
    identity: dict[str, object],
    capability: PortableExecutionCapability,
    started_at: str,
    receipt_ref: ArtifactReference | FailureReceiptWrite | None = None,
) -> dict[str, object]:
    return _terminal_payload(
        identity, capability, started_at, "cancelled", "cancelled", None, "result", receipt_ref, True
    )


def _failure_terminal(
    identity: dict[str, object],
    capability: PortableExecutionCapability,
    started_at: str,
    category: str,
    receipt_ref: ArtifactReference | FailureReceiptWrite | None = None,
) -> dict[str, object]:
    return _terminal_payload(
        identity, capability, started_at, "failed", category, category, "error", receipt_ref, False
    )


def _receipt_write(value: ArtifactReference | FailureReceiptWrite) -> FailureReceiptWrite:
    if isinstance(value, ArtifactReference):
        return FailureReceiptWrite(value, "stored", None)
    return value


def _execution_error_category(error: BaseException) -> str:
    if isinstance(error, PermissionError):
        return "unsupported_capability"
    if isinstance(error, ProtocolError):
        return "malformed_protocol"
    if isinstance(error, (KeyError, TypeError, ValueError)):
        return "contract_validation"
    return "source_capture" if isinstance(error, OSError) else "semantic_workload"


def _classify_worker_cause(error: BaseException) -> str:
    curr: BaseException | None = error
    depth, seen = 0, set()
    while curr is not None and depth < 16 and id(curr) not in seen:
        seen.add(id(curr))
        depth += 1
        tname, msg = type(curr).__name__.lower(), str(curr).lower()
        if "gohelperunavailable" in tname or "helper is unavailable" in msg:
            return "helper_unavailable"
        if "goprotocolerror" in tname or "helper protocol" in msg:
            return "helper_protocol_violation"
        if "runtime authority denied" in msg or "exec authority denied" in msg:
            return "helper_launch_denied"
        if "filesystem authority denied" in msg or (
            isinstance(curr, PermissionError) and not any(k in msg for k in ("launch", "exec", "runtime"))
        ):
            return "filesystem_capture_denied"
        if "source mutation" in msg or "source stability" in msg or "file changed" in msg:
            return "source_mutation_failure"
        if isinstance(curr, PermissionError) or "authority denied" in msg:
            return "helper_launch_denied"
        curr = curr.__cause__ or curr.__context__
    allowed_sub = {"source_unavailable", "source_corrupt", "source_timeout", "source_mutation"}
    for cand in (error, getattr(error, "__cause__", None)):
        sub = getattr(cand, "category", None)
        if sub in allowed_sub:
            return f"source_capture_{sub}"
    if isinstance(error, (PortableExecutionError, OSError)):
        return "source_capture"
    return _execution_error_category(error)


def _emit_failure_stderr(error: BaseException) -> None:
    cause = _classify_worker_cause(error)
    sys.stderr.write(f"refresh-failure:portable-worker:{cause}\n")
    sys.stderr.flush()


def _write(message: dict[str, object]) -> None:
    remaining = memoryview(encode_jsonl(message))
    deadline = time.monotonic() + 0.5
    while remaining:
        if time.monotonic() >= deadline:
            raise RuntimeError("worker protocol output did not settle")
        try:
            written = os.write(sys.stdout.fileno(), remaining)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if written <= 0:
            raise RuntimeError("worker protocol output closed")
        remaining = remaining[written:]


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
