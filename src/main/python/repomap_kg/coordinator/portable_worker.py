"""ASYNC1 portable-snapshot semantic worker process."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading

from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    load_portable_capability,
)
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
from repomap_kg.coordinator._portable_semantic_adapter import (
    FailureReceiptWrite,
    PortableExecutionError,
    create_failure_receipt,
    execute_portable_extraction,
)
from repomap_kg.coordinator._protocol_core import (
    MAX_JSONL_LINE_BYTES,
    ProtocolError,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args(argv)
    try:
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
            decode_jsonl(sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1))
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
            args=(session, identity, lock, stop),
            daemon=True,
        )
        cancellation_reader = threading.Thread(
            target=_read_cancellation,
            args=(session, identity, lock, stop, cancel_event),
            daemon=True,
        )
        heartbeat.start()
        cancellation_reader.start()
        try:
            result = execute_portable_extraction(
                capability,
                emit_progress=progress,
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                terminal = _cancellation_terminal(
                    identity, capability, started_at
                )
            else:
                counts = result.bundle.family_counts
                terminal = {
                    "schema_version": 1,
                    "message_type": "result",
                    **identity,
                    "job_kind": "refresh_graph",
                    "graph_id": capability.graph_id,
                    "status": "succeeded",
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "phase": "complete",
                    "files": result.manifest.total_files,
                    "observations": counts["raw_observations"],
                    "canonical_nodes": counts["canonical_nodes"],
                    "canonical_edges": counts["canonical_edges"],
                    "warnings": [],
                    "diagnostics": [],
                    "publication_state": "not_started",
                    "latest_run_identity": None,
                    "source_generation": capability.source_generation,
                    "config_generation": capability.config_generation,
                    "extractor_generation": capability.extractor_generation,
                    "canonicalizer_generation": capability.canonicalizer_generation,
                    "retryable": False,
                    "error_category": None,
                    "portable_snapshot": {
                        "contract_version": "1.0",
                        "outcome": "completed",
                        "receipt": result.receipt_reference.to_mapping(),
                        "receipt_status": "stored",
                        "receipt_diagnostic": None,
                        "bundle": result.bundle_reference.to_mapping(),
                    },
                }
        except PortableExecutionError as error:
            if error.category == "cancelled" or cancel_event.is_set():
                terminal = _cancellation_terminal(
                    identity,
                    capability,
                    started_at,
                )
            else:
                terminal = _failure_terminal(
                    identity,
                    capability,
                    started_at,
                    error.category,
                )
        except (KeyError, OSError, TypeError, ValueError, ProtocolError, RuntimeError) as error:
            terminal = _failure_terminal(
                identity,
                capability,
                started_at,
                _execution_error_category(error),
            )
        finally:
            stop.set()
            heartbeat.join(timeout=1.0)
        emit(terminal)
        return 0
    except (KeyError, OSError, TypeError, ValueError, ProtocolError, RuntimeError):
        return 2


def _heartbeat_loop(session, identity, lock, stop) -> None:
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
            except ProtocolError:
                return


def _read_cancellation(session, identity, lock, stop, cancel_event) -> None:
    frame = sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1)
    if stop.is_set() or not frame:
        return
    try:
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
        cancel_event.set()


def _cancellation_terminal(
    identity: dict[str, object],
    capability: PortableExecutionCapability,
    started_at: str,
    receipt_ref: ArtifactReference | FailureReceiptWrite | None = None,
) -> dict[str, object]:
    if receipt_ref is None:
        receipt_ref = create_failure_receipt(
            capability, "cancelled", cancellation_requested=True
        )
    receipt_write = _receipt_write(receipt_ref)
    return {
        "schema_version": 1,
        "message_type": "result",
        **identity,
        "job_kind": "refresh_graph",
        "graph_id": capability.graph_id,
        "status": "cancelled",
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
        "error_category": None,
        "portable_snapshot": {
            "contract_version": "1.0",
            "outcome": "cancelled",
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


def _failure_terminal(
    identity: dict[str, object],
    capability: PortableExecutionCapability,
    started_at: str,
    category: str,
    receipt_ref: ArtifactReference | FailureReceiptWrite | None = None,
) -> dict[str, object]:
    if receipt_ref is None:
        receipt_ref = create_failure_receipt(
            capability, category, cancellation_requested=False
        )
    receipt_write = _receipt_write(receipt_ref)
    return {
        "schema_version": 1,
        "message_type": "error",
        **identity,
        "job_kind": "refresh_graph",
        "graph_id": capability.graph_id,
        "status": "failed",
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
        "error_category": category,
        "portable_snapshot": {
            "contract_version": "1.0",
            "outcome": category,
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


def _receipt_write(
    value: ArtifactReference | FailureReceiptWrite,
) -> FailureReceiptWrite:
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
    if isinstance(error, OSError):
        return "source_capture"
    return "semantic_workload"


def _write(message: dict[str, object]) -> None:
    sys.stdout.buffer.write(encode_jsonl(message))
    sys.stdout.buffer.flush()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
