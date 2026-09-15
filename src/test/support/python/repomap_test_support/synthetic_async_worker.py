"""Allowlisted real-process fixture for the ASYNC1 worker protocol."""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time

from repomap_kg.coordinator.protocol import (
    MAX_JSONL_LINE_BYTES,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)
from repomap_test_support.synthetic_worker_contracts import (
    ALLOWED_SYNTHETIC_WORKER_MODES,
)


_JOB_CONTEXT = {
    "graph_id": "synthetic-graph",
    "source_generation": "sg1:synthetic",
    "config_generation": "cg1:synthetic",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=sorted(ALLOWED_SYNTHETIC_WORKER_MODES), required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args(argv)
    return run_mode(args.mode, {"job_id": args.job_id, "attempt": args.attempt})


def run_mode(mode: str, identity: dict[str, object]) -> int:
    global _JOB_CONTEXT
    if mode == "malformed_json":
        write_raw(b"not-json\n")
        return 0
    if mode == "oversized_line":
        write_raw(b"x" * MAX_JSONL_LINE_BYTES + b"\n")
        return 0
    if mode == "out_of_order_message":
        write_message(progress(identity))
        return 0
    hello = worker_hello()
    if mode == "malformed_hello":
        write_message({**hello, "unexpected": "public-fixture-value"})
        return 0

    session = ProtocolSession(identity)
    emit(session, hello)
    job_start = decode_jsonl(sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1))
    session.accept_coordinator(job_start)
    _JOB_CONTEXT = {
        field: str(job_start[field])
        for field in ("graph_id", "source_generation", "config_generation")
    }

    if mode == "success":
        emit(session, progress(identity))
        return finish(session, terminal(identity, "result", "succeeded", None, "committed"))
    if mode == "delay":
        time.sleep(0.1)
        emit(session, progress(identity))
        time.sleep(0.1)
        return finish(session, terminal(identity, "result", "succeeded", None, "committed"))
    if mode == "transient_failure":
        finish(session, terminal(identity, "error", "failed", "transient", "not_started"))
        return 10
    if mode == "permanent_failure":
        finish(session, terminal(identity, "error", "failed", "permanent", "not_started"))
        return 11
    if mode == "pre_publication_crash":
        return 20
    if mode == "transaction_crash":
        finish(session, terminal(identity, "error", "failed", "worker_crash", "commit_unknown"))
        return 21
    if mode == "transaction_rollback":
        return finish(session, terminal(identity, "error", "failed", "permanent", "rolled_back"))
    if mode == "transaction_commit":
        return finish(session, terminal(identity, "result", "succeeded", None, "committed"))
    if mode == "before_commit_connection_loss":
        finish(session, terminal(identity, "error", "failed", "storage_unavailable", "not_started"))
        return 22
    if mode == "after_commit_connection_loss":
        finish(session, terminal(identity, "error", "failed", "publication_unknown", "commit_unknown"))
        return 23
    if mode == "conflicting_marker":
        return finish(session, terminal(identity, "error", "failed", "publication_unknown", "commit_unknown"))
    if mode == "duplicate_terminal":
        result = terminal(identity, "result", "succeeded", None, "committed")
        finish(session, result)
        write_message(result)
        return 0
    if mode == "stderr_flood":
        sys.stderr.buffer.write(
            b"Traceback\n/private/operator/root\npassword=not-public\n"
            b"SELECT * FROM private_table\n" + b"x" * 4096)
        sys.stderr.buffer.flush()
        return finish(session, terminal(identity, "result", "succeeded", None, "committed"))
    if mode == "heartbeat_loss":
        time.sleep(30)
        return 0
    if mode == "cooperative_cancellation":
        cancel = decode_jsonl(sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1))
        session.accept_coordinator(cancel)
        emit(session, {"schema_version": 1, "message_type": "cancel_ack",
                       **identity, "status": "accepted"})
        return finish(session, terminal(
            identity, "result", "cancelled", None, "rolled_back"))
    if mode == "non_cooperative_cancellation":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=None)
        while True:
            time.sleep(0.02)
    raise AssertionError("unreachable allowlisted worker mode")


def worker_hello() -> dict[str, object]:
    return {
        "schema_version": 1, "message_type": "worker_hello",
        "protocol_versions": [1], "worker_generation": "worker-v1",
        "capabilities": ["refresh_graph"], "process_nonce": "nonce-public-1",
    }


def progress(identity: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1, "message_type": "progress", **identity,
        "completed": 1, "total": 1, "phase": "discovery", "unit": "files",
        "message_category": "files-discovered",
        "heartbeat_at": "2026-07-13T12:00:02Z",
    }


def heartbeat(identity: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1, "message_type": "heartbeat", **identity,
        "heartbeat_at": "2026-07-13T12:00:03Z",
    }


def terminal(
    identity: dict[str, object], message_type: str, status: str,
    error_category: str | None, publication_state: str,
) -> dict[str, object]:
    committed = publication_state == "committed"
    return {
        "schema_version": 1, "message_type": message_type, **identity,
        "job_kind": "refresh_graph", "graph_id": _JOB_CONTEXT["graph_id"],
        "status": status, "started_at": "2026-07-13T12:00:01Z",
        "finished_at": "2026-07-13T12:00:04Z", "phase": "complete",
        "files": 1, "observations": 2, "canonical_nodes": 3,
        "canonical_edges": 4, "warnings": [], "diagnostics": [],
        "publication_state": publication_state,
        "latest_run_identity": "run-public-1" if committed else None,
        "source_generation": _JOB_CONTEXT["source_generation"],
        "config_generation": _JOB_CONTEXT["config_generation"],
        "extractor_generation": "eg1:synthetic",
        "canonicalizer_generation": "kg1:synthetic",
        "retryable": error_category == "transient", "error_category": error_category,
    }


def emit(session: ProtocolSession, message: dict[str, object]) -> None:
    session.accept_worker(message)
    write_message(message)


def finish(session: ProtocolSession, message: dict[str, object]) -> int:
    emit(session, message)
    return 0


def write_message(message: dict[str, object]) -> None:
    write_raw(encode_jsonl(message))


def write_raw(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
