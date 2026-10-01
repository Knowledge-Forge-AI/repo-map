"""Diagnostic capture, bounded marker readers, and status reporting for portable coverage."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
from typing import Any

from runner_coverage_execution import ShardDiagnosticSnapshot

MAX_MARKER_DISPLAY_BYTES: int = 4096
MAX_READ_BYTES: int = 4097

WHITELISTED_START_FIELDS: frozenset[str] = frozenset(
    {
        "token",
        "invocation",
        "suite",
        "revision",
        "pid",
        "cov_start",
        "role",
        "owner",
        "ppid",
        "launch_shape",
        "complete",
        "shard",
    }
)


def read_bounded_marker(
    path: Path, max_bytes: int = MAX_MARKER_DISPLAY_BYTES
) -> tuple[str, str, dict[str, str]]:
    """Read at most max_bytes + 1 bytes from path using an explicit file handle.

    Returns (status, display_text, whitelisted_fields).
    Observable states:
    - 'missing': file does not exist
    - 'unreadable': OSError reading handle
    - 'invalid_utf8': bytes failed strict UTF-8 decode
    - 'truncated_read': file exceeded max_bytes
    - 'valid': decoded cleanly and within size limit
    """
    try:
        if not path.is_file():
            return "missing", "missing", {}
    except OSError:
        return "unreadable", "unreadable", {}

    try:
        with open(path, "rb") as handle:
            read_len = MAX_READ_BYTES if max_bytes == MAX_MARKER_DISPLAY_BYTES else max_bytes + 1
            raw_bytes = handle.read(read_len)
    except OSError:
        return "unreadable", "unreadable", {}

    is_truncated = len(raw_bytes) > max_bytes
    bounded_bytes = raw_bytes[:max_bytes]

    try:
        text = bounded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        digest = hashlib.sha256(bounded_bytes).hexdigest()[:16]
        display = f"[invalid_utf8][bytes={len(bounded_bytes)}:sha256={digest}]"
        if is_truncated:
            display = f"{display}[truncated]"
        return "invalid_utf8", display, {}

    fields: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key in WHITELISTED_START_FIELDS:
            fields[key] = val.strip()

    status = "truncated_read" if is_truncated else "valid"
    display = ";".join(f"{k}={v}" for k, v in fields.items())
    if is_truncated:
        display = f"{display}[truncated]"
    return status, display, fields


def stat_exit_marker(path: Path) -> tuple[str, int]:
    """Stat exit marker file returning (status, size_bytes).

    Observable states:
    - 'missing': file does not exist (size -1)
    - 'empty': file exists but size 0 (size 0)
    - 'exit_stat_failure': OSError when stating (size -1)
    - 'present': file exists with size > 0
    """
    try:
        if not path.is_file():
            return "missing", -1
        size = path.stat().st_size
        if size == 0:
            return "empty", 0
        return "present", size
    except OSError:
        return "exit_stat_failure", -1


def safe_render_error(exc: BaseException | None, fallback: str) -> str:
    """Safely render an exception without letting a raising __str__ escape."""
    if exc is None:
        return ""
    try:
        text = str(exc)
        if len(text) > 500:
            text = text[:500] + "[truncated]"
        return text
    except BaseException:
        return fallback


def safe_format_exception(
    prefix: str, exc: BaseException | None, fallback_category: str
) -> str:
    """Format prefix and exception safely without raising secondary formatting errors."""
    if exc is None:
        return ""
    rendered = safe_render_error(exc, fallback_category)
    return f"{prefix}: {rendered}"


def safe_attach_note(target: BaseException | None, note: str) -> None:
    """Safely attach a note to an exception, guarding against failing add_note."""
    if target is None or not note:
        return
    try:
        target.add_note(note)
    except BaseException:
        pass


def attach_workload_disposition_notes(
    workload_exc: BaseException,
    accept_exc: Exception | None,
    meas_rec_err: BaseException | None,
    diag_rec_note: str | None,
) -> None:
    """Attach acceptance, measurement, and diagnostic notes to workload exception safely."""
    if accept_exc is not None:
        safe_attach_note(
            workload_exc,
            safe_format_exception(
                "child coverage measurement failure", accept_exc, "measurement_failure_unrenderable"
            ),
        )
    if meas_rec_err is not None:
        safe_attach_note(
            workload_exc,
            safe_format_exception(
                "measurement recording failure", meas_rec_err, "recording_failure_unrenderable"
            ),
        )
    if diag_rec_note is not None:
        note = (
            diag_rec_note
            if diag_rec_note.startswith("diagnostic recording failure:")
            else f"diagnostic recording failure: {diag_rec_note}"
        )
        safe_attach_note(workload_exc, note)


def raise_unrecorded_measurement_escalation(
    accept_exc: Exception,
    meas_rec_err: BaseException,
    diag_rec_note: str | None,
) -> None:
    """Attach diagnostic note and raise unrecorded coverage measurement failure safely."""
    if diag_rec_note is not None:
        safe_attach_note(accept_exc, diag_rec_note)
    rendered_accept = safe_render_error(accept_exc, "unrenderable_acceptance_error")
    rendered_meas = safe_render_error(meas_rec_err, "unrenderable_recording_error")
    raise RuntimeError(
        f"unrecorded coverage measurement failure: {rendered_accept}; recording failure: {rendered_meas}"
    ) from accept_exc


def build_acceptance_diagnostic_status(
    accept_exc: Exception,
    start_info: str,
    start_state: str,
    exit_bytes: int,
    exit_state: str,
    retcode: int | None,
    t_reason: str | None,
    h_to: bool | None,
    p_to: bool | None,
    hb_to: bool | None,
) -> str:
    """Format structured diagnostic message preserving causal order and observable states."""
    rendered_accept = safe_render_error(accept_exc, "acceptance_exception_unrenderable")
    return (
        f"acceptance_failure: {rendered_accept} ["
        f"start={start_info} start_state={start_state} "
        f"exit_bytes={exit_bytes} exit_state={exit_state} "
        f"retcode={retcode} reason={t_reason} "
        f"timeouts=h:{h_to}/p:{p_to}/hb:{hb_to}]"
    )


def capture_portable_acceptance_diagnostic(
    session: Any,
    capability: Any,
    token: str,
    accept_exc: Exception,
    result: Any,
    launch_role: str,
    test_owner: str,
) -> tuple[str | None, ShardDiagnosticSnapshot | None]:
    """Capture diagnostic snapshot safely without raising unhandled secondary exceptions.

    Returns (diagnostic_failure_note, created_snapshot).
    """
    sp = capability.child_manifest_dir / f"{token}.start"
    ep = capability.child_manifest_dir / f"{token}.exit"

    start_state, start_info, _ = read_bounded_marker(sp)
    exit_state, exit_bytes = stat_exit_marker(ep)

    retcode = getattr(result, "returncode", None) if result is not None else None
    t_reason = (
        result.terminal.get("reason")
        if (result is not None and isinstance(getattr(result, "terminal", None), Mapping))
        else None
    )
    h_to = getattr(result, "hello_timed_out", None)
    p_to = getattr(result, "process_timed_out", None)
    hb_to = getattr(result, "heartbeat_timed_out", None)

    diag_status = build_acceptance_diagnostic_status(
        accept_exc=accept_exc,
        start_info=start_info,
        start_state=start_state,
        exit_bytes=exit_bytes,
        exit_state=exit_state,
        retcode=retcode,
        t_reason=t_reason,
        h_to=h_to,
        p_to=p_to,
        hb_to=hb_to,
    )

    snap: ShardDiagnosticSnapshot | None = None
    diag_note: str | None = None

    if hasattr(session, "_create_snapshot"):
        try:
            snap = session._create_snapshot(
                shard_name=f"portable_child.{token}",
                file_type="missing_or_corrupt",
                size_bytes=-1,
                sha256=None,
                reader_status=diag_status,
                stage="post_worker_reap",
                child_probe_id=f"token={token}",
                termination_outcome=(
                    "declared_abrupt_measurement_incomplete"
                    if launch_role == "conformance-abrupt"
                    else "child_measurement_failed"
                ),
                launch_role=launch_role,
                test_owner=test_owner,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            diag_note = safe_format_exception(
                "snapshot_construction_failure", exc, "snapshot_construction_failed"
            )

    if snap is not None and hasattr(session, "_record_diagnostic"):
        try:
            session._record_diagnostic(snap)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            rec_note = safe_format_exception(
                "diagnostic_recording_failure", exc, "diagnostic_recording_failed"
            )
            diag_note = f"{diag_note}; {rec_note}" if diag_note else rec_note

    return diag_note, snap


__all__ = (
    "MAX_MARKER_DISPLAY_BYTES",
    "MAX_READ_BYTES",
    "WHITELISTED_START_FIELDS",
    "attach_workload_disposition_notes",
    "build_acceptance_diagnostic_status",
    "capture_portable_acceptance_diagnostic",
    "raise_unrecorded_measurement_escalation",
    "read_bounded_marker",
    "safe_attach_note",
    "safe_format_exception",
    "safe_render_error",
    "stat_exit_marker",
)
