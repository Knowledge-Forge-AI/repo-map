"""Allowlisted ASYNC4 worker entrypoint for one forced-full refresh attempt."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import sys
import threading

from repomap_kg.coordinator.protocol import (
    MAX_JSONL_LINE_BYTES,
    ProtocolError,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)
from repomap_kg.coordinator.refresh_adapter import (
    RefreshConfigurationError,
    RefreshGenerationChangedError,
    RefreshSourceError,
    execute_refresh,
    load_refresh_capability,
    refresh_terminal,
)

_PUBLIC_CONFIGURATION_DIAGNOSTICS = frozenset(
    {"multi-source-refresh-unsupported", "source-binding-refresh-unsupported"}
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        capability = load_refresh_capability(Path(args.capability))
        if capability.job_id != args.job_id or capability.attempt != args.attempt:
            raise ValueError("invalid refresh capability")
        identity = {"job_id": capability.job_id, "attempt": capability.attempt}
        session = ProtocolSession(identity)
        hello = {
            "schema_version": 1,
            "message_type": "worker_hello",
            "protocol_versions": [1],
            "worker_generation": "refresh-adapter-v1",
            "capabilities": ["refresh_graph"],
            "process_nonce": "refresh-worker-v1",
        }
        session.accept_worker(hello)
        _write(hello)
        frame = sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1)
        start = session.accept_coordinator(decode_jsonl(frame))
        if any(
            start[field] != expected
            for field, expected in (
                ("graph_id", capability.graph_id),
                ("source_generation", capability.source_generation),
                ("config_generation", capability.config_generation),
            )
        ):
            raise ProtocolError("identity_mismatch")
        protocol_lock = threading.Lock()

        def emit_heartbeat() -> None:
            heartbeat = {
                "schema_version": 1,
                "message_type": "heartbeat",
                **identity,
                "heartbeat_at": _utc_now(),
            }
            with protocol_lock:
                session.accept_worker(heartbeat)
                _write(heartbeat)

        try:
            refresh_result = _run_with_heartbeats(
                lambda: execute_refresh(capability),
                emit_heartbeat,
            )
            if getattr(refresh_result, "result", None) != "success":
                _write_failure_categories(refresh_result)
            terminal = refresh_terminal(capability, refresh_result)
        except RefreshGenerationChangedError:
            terminal = _exception_terminal(
                capability, identity, started=False, category="generation_changed"
            )
        except RefreshSourceError as error:
            terminal = _exception_terminal(
                capability, identity, started=False, category=error.category
            )
        except RefreshConfigurationError as error:
            terminal = _exception_terminal(
                capability,
                identity,
                started=False,
                diagnostic=str(error),
            )
        except (OSError, TypeError, ValueError) as error:
            from repomap_kg.ops.reports import _redact_text

            safe_error = _redact_text(str(error))[:256]
            sys.stderr.write(f"refresh-failure:worker-error:{safe_error}\n")
            sys.stderr.flush()
            terminal = _exception_terminal(capability, identity, started=True)
        with protocol_lock:
            session.accept_worker(terminal)
            _write(terminal)
        return 0
    except Exception as error:
        from repomap_kg.ops.reports import _redact_text

        category = "worker-error"
        if isinstance(error, ProtocolError):
            category = "protocol-error"
        elif isinstance(error, (ValueError, OSError)) and "capability" in str(error).lower():
            category = "capability-error"
        safe_msg = _redact_text(str(error))[:256]
        sys.stderr.write(f"refresh-failure:{category}:{safe_msg}\n")
        sys.stderr.flush()
        return 2


def _write(message: dict[str, object]) -> None:
    sys.stdout.buffer.write(encode_jsonl(message))
    sys.stdout.buffer.flush()


def _run_with_heartbeats(
    operation: Callable[[], object],
    heartbeat: Callable[[], None],
    *,
    interval_seconds: float = 5.0,
) -> object:
    """Run one synchronous operation with one owned bounded heartbeat task."""

    if interval_seconds <= 0:
        raise ValueError("heartbeat interval is invalid")
    stopped = threading.Event()
    failures: list[BaseException] = []

    def emit() -> None:
        while not stopped.wait(interval_seconds):
            try:
                heartbeat()
            except BaseException as error:
                failures.append(error)
                return

    task = threading.Thread(target=emit, name="refresh-worker-heartbeat")
    task.start()
    try:
        result = operation()
    finally:
        stopped.set()
        task.join()
    if failures:
        raise failures[0]
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _exception_terminal(
    capability,
    identity,
    *,
    started: bool,
    category: str | None = None,
    diagnostic: str | None = None,
):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "message_type": "error",
        **identity,
        "job_kind": "refresh_graph",
        "graph_id": capability.graph_id,
        "status": "failed",
        "started_at": now,
        "finished_at": now,
        "phase": "storage_publish" if started else "preflight",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": (
            [diagnostic]
            if diagnostic in _PUBLIC_CONFIGURATION_DIAGNOSTICS
            else []
        ),
        "publication_state": "commit_unknown" if started else "not_started",
        "latest_run_identity": None,
        "source_generation": capability.source_generation,
        "config_generation": capability.config_generation,
        "extractor_generation": capability.extractor_generation,
        "canonicalizer_generation": capability.canonicalizer_generation,
        "retryable": False,
        "error_category": category or (
            "publication_unknown" if started else "configuration"
        ),
    }


def _write_failure_categories(result: object) -> None:
    from repomap_kg.ops.reports import _redact_text

    categories = []
    for diagnostic in getattr(result, "diagnostics", ()):
        if isinstance(diagnostic, dict) and isinstance(diagnostic.get("code"), str):
            categories.append(diagnostic["code"])
    error = str(getattr(result, "error", "")).lower()
    if "no such file" in error or "not found" in error:
        categories.append("executable-unavailable")
    elif "connect" in error or "server" in error:
        categories.append("connection-unavailable")
    elif "schema" in error or "relation" in error:
        categories.append("schema-unavailable")
    elif "permission" in error or "password" in error:
        categories.append("authorization-failed")
    else:
        categories.append("unclassified")
    safe_error = _redact_text(str(getattr(result, "error", "")))[:512]
    sys.stderr.write(
        "refresh-failure:" + ",".join(categories[:8]) + ":" + safe_error + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
