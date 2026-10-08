"""Diagnostic snapshots, shard forensics, and error recording for coverage runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, NoReturn

from runner_coverage_forensics import classify_measured_files
from runner_coverage_observer import (
    ProcessObservationRecord,
    ProcessObserver,
)

_BASE_KEYS: frozenset[str] = frozenset({
    "session_id", "shard_name", "file_type", "size_bytes",
    "sha256", "reader_status", "stage", "measured_files_count",
})


def compute_bounded_file_digest(
    path: Path, max_bytes: int = 16 * 1024 * 1024, chunk_size: int = 65536,
) -> tuple[str | None, int, bytes, bool, str]:
    """Return (digest_hex, file_size, header_16, truncated, algorithm_name)."""
    if not path.is_file() or path.is_symlink():
        return None, -1, b"", False, "none"
    try:
        size = path.stat().st_size
    except OSError:
        return None, -1, b"", False, "none"

    h = hashlib.sha256()
    header = b""
    read_total = 0
    with open(path, "rb") as stream:
        header = stream.read(16)
        h.update(header)
        read_total += len(header)
        while read_total < max_bytes:
            to_read = min(chunk_size, max_bytes - read_total)
            chunk = stream.read(to_read)
            if not chunk:
                break
            h.update(chunk)
            read_total += len(chunk)

    truncated = size > max_bytes
    alg = f"sha256_prefix_{max_bytes}" if truncated else "sha256"
    return h.hexdigest(), size, header, truncated, alg


def compute_streaming_sha256(
    path: Path, max_bytes: int = 16 * 1024 * 1024, chunk_size: int = 65536,
) -> tuple[str | None, int, bytes]:
    """Compute (sha256_hex, file_size, header_16) boundedly using streaming I/O."""
    digest, size, header, truncated, _ = compute_bounded_file_digest(
        path, max_bytes=max_bytes, chunk_size=chunk_size
    )
    return (None if truncated else digest), size, header


@dataclass(frozen=True)
class ShardDiagnosticSnapshot:
    """Diagnostic evidence retained on coverage shard anomaly."""

    session_id: str
    shard_name: str
    file_type: str
    size_bytes: int
    sha256: str | None
    reader_status: str
    stage: str
    digest_algorithm: str = "sha256"
    digest_truncated: bool = False
    digest_bytes_bound: int = 16 * 1024 * 1024
    run_id: str | None = None
    source_selection: list[str] | None = None
    coverage_version: str | None = None
    child_probe_id: str | None = None
    termination_outcome: str | None = None
    launch_role: str | None = None
    test_owner: str | None = None
    ppid: int | None = None
    launch_shape: str | None = None
    invocation_id: str | None = None
    suite: str | None = None
    source_revision: str | None = None
    has_config: bool | None = None
    has_manifest: bool | None = None
    has_token: bool | None = None
    bootstrap_stage: str | None = None
    failure_class: str | None = None
    failure_reason: str | None = None
    forensic_verdict: str | None = None
    measured_files_count: int | None = None
    measured_classification: dict[str, Any] | None = None
    sys_argv: str | None = None
    sys_argv_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None or f.name in _BASE_KEYS
        }



def extract_pid_match(name: str) -> int | None:
    if ".pid" in name:
        try:
            return int(name.split(".pid", 1)[1].split(".", 1)[0])
        except (ValueError, IndexError):
            pass
    for t in name.split("."):
        if (t.startswith("pid") and t[3:].isdigit()) or (t.isdigit() and len(t) >= 2):
            try:
                return int(t[3:] if t.startswith("pid") else t)
            except (ValueError, IndexError):
                pass
    return None


def extract_child_probe_id(shard_name: str) -> str | None:
    pid = extract_pid_match(shard_name)
    return f"pid={pid}" if pid is not None else None


def create_shard_snapshot(
    *, session_name: str = "", shard_name: str, file_type: str,
    size_bytes: int, sha256: str | None, reader_status: str, stage: str,
    digest_algorithm: str = "sha256", digest_truncated: bool = False,
    coverage_module: Any = None, cov_mod: Any = None,
    source_root: Path | None = None, source_paths: tuple[Path, ...] = (),
    child_probe_id: str | None = None, **kwargs: Any,
) -> ShardDiagnosticSnapshot:
    run_id = (
        kwargs.pop("run_id", None)
        or os.environ.get("GITHUB_RUN_ID")
        or os.environ.get("REPO_MAP_RUN_ID")
        or session_name
    )
    src_sel = (
        kwargs.pop("source_selection", None)
        or ([str(p) for p in source_paths] if source_paths else None)
        or ([str(source_root)] if source_root else None)
    )
    cov_eff = cov_mod if cov_mod is not None else coverage_module
    cov_ver = kwargs.pop("coverage_version", None) or getattr(cov_eff, "__version__", None)
    probe_id = child_probe_id or kwargs.pop("child_probe_id", None) or extract_child_probe_id(shard_name)
    return ShardDiagnosticSnapshot(
        session_id=session_name,
        shard_name=shard_name,
        file_type=file_type,
        size_bytes=size_bytes,
        sha256=sha256,
        reader_status=reader_status,
        stage=stage,
        digest_algorithm=digest_algorithm,
        digest_truncated=digest_truncated,
        run_id=run_id,
        source_selection=src_sel,
        coverage_version=cov_ver,
        child_probe_id=probe_id,
        **kwargs,
    )


def record_diagnostic(
    snapshots: list[ShardDiagnosticSnapshot], snapshot: ShardDiagnosticSnapshot, session_dir: Path,
) -> None:
    snapshots.append(snapshot)
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "coverage_anomaly_snapshot.json").write_text(
            json.dumps([s.to_dict() for s in snapshots], indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(
            f"failed to write coverage anomaly snapshot to {session_dir}: {exc}"
        ) from exc


def _annotate_snapshot(
    snap: ShardDiagnosticSnapshot, child_info: dict[str, Any]
) -> ShardDiagnosticSnapshot:
    return merge_diagnostic_snapshot(snap, child_info=child_info)


def _first_not_none(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def merge_diagnostic_snapshot(
    snap: ShardDiagnosticSnapshot,
    child_info: dict[str, Any] | None = None,
    obs: ProcessObservationRecord | None = None,
    forensics: dict[str, Any] | None = None,
    sqlite_valid: bool = False,
    forensic_verdict: str | None = None,
) -> ShardDiagnosticSnapshot:
    """Deterministic precedence merge for shard anomalies, observations, and forensics."""
    c = child_info or {}
    f_total = forensics.get("observed_total") if forensics else None
    m_count = _first_not_none(c.get("measured_files_count"), f_total, snap.measured_files_count)
    f_verdict = _first_not_none(forensic_verdict, snap.forensic_verdict)
    if f_verdict:
        default_fclass = f_verdict.split(":", 1)[0]
        fb_reason = (
            f"forensic_verdict={f_verdict}:sqlite_valid={sqlite_valid}:"
            f"measured_files={'unknown' if m_count is None else m_count}"
        )
    else:
        default_fclass = "valid_sqlite" if sqlite_valid else "corrupt_or_empty"
        if m_count is None:
            fb_reason = f"sqlite_valid={sqlite_valid}:measured_files=unknown"
        else:
            fb_reason = f"sqlite_valid={sqlite_valid}:measured_files={m_count}"
    f_cls = forensics.get("classification") if forensics else None
    f_ppid = forensics.get("ppid") if forensics else None
    f_owner = forensics.get("test_owner") if forensics else None
    f_argv = forensics.get("sys_argv") if forensics else None
    f_argv_dig = forensics.get("sys_argv_digest") if forensics else None

    primary_reason = _first_not_none(c.get("failure_reason"), snap.failure_reason)
    if primary_reason is not None and f_verdict is not None and f"forensic_verdict={f_verdict}" not in primary_reason:
        merged_reason = f"{primary_reason};forensic_verdict={f_verdict}"
    else:
        merged_reason = primary_reason or fb_reason

    return replace(
        snap,
        failure_class=_first_not_none(
            c.get("failure_class"), snap.failure_class, default_fclass,
        ),
        failure_reason=merged_reason,
        forensic_verdict=f_verdict,
        measured_files_count=m_count,
        measured_classification=_first_not_none(
            c.get("measured_classification"), f_cls, snap.measured_classification,
        ),
        ppid=_first_not_none(c.get("ppid"), obs.ppid if obs else None, f_ppid, snap.ppid),
        launch_shape=_first_not_none(
            c.get("launch_shape"),
            forensics.get("launch_shape") if forensics else None,
            obs.launch_shape_hash if obs else None,
            snap.launch_shape,
        ),
        test_owner=_first_not_none(
            c.get("owner"), obs.test_owner_hash if obs else None, f_owner, snap.test_owner,
        ),
        has_config=_first_not_none(
            c.get("has_config"), obs.has_coverage_capability if obs else None, snap.has_config,
        ),
        has_manifest=_first_not_none(
            c.get("has_manifest"), obs.has_manifest_authority if obs else None, snap.has_manifest,
        ),
        has_token=_first_not_none(
            c.get("has_token"), obs.has_token if obs else None, snap.has_token,
        ),
        bootstrap_stage=_first_not_none(c.get("bootstrap_stage"), snap.bootstrap_stage),
        launch_role=_first_not_none(c.get("role"), snap.launch_role),
        sys_argv=_first_not_none(c.get("sys_argv"), f_argv, snap.sys_argv),
        sys_argv_digest=_first_not_none(c.get("sys_argv_digest"), f_argv_dig, snap.sys_argv_digest),
    )


def validate_shard_file(
    sp: str, registered_children: dict[int, dict[str, Any]],
    snapshot_fn: Callable[..., ShardDiagnosticSnapshot],
    record_fn: Callable[[ShardDiagnosticSnapshot], None],
    cov_mod: Any = None,
) -> None:
    p = Path(sp)
    if p.is_symlink():
        raise RuntimeError("coverage shard symlink rejected")
    pid_match = extract_pid_match(p.name)
    term_outcome = None
    if pid_match is not None and pid_match in registered_children:
        term_outcome = (
            "clean_exit"
            if registered_children[pid_match]["exited"]
            else "abrupt_termination"
        )
    probe_id = f"pid={pid_match}" if pid_match else None

    def _fail(
        ft: str, rs: str, msg: str, sz: int = 0,
        sha: str | None = None, out: str = "error", exc: Exception | None = None,
    ) -> NoReturn:
        snap = snapshot_fn(
            shard_name=p.name, file_type=ft, size_bytes=sz, sha256=sha,
            reader_status=rs, stage="pre_combine", cov_mod=cov_mod,
            child_probe_id=probe_id, termination_outcome=term_outcome or out,
        )
        record_fn(snap)
        err = f"coverage shard {sp} is empty or unreadable: {msg}"
        if exc is not None:
            raise RuntimeError(err) from exc
        raise RuntimeError(err)

    if not p.is_file():
        _fail("not_a_file", "not_a_regular_file", "not a regular file", out="not_a_file")
    try:
        size = p.stat().st_size
    except OSError as exc:
        _fail("unreadable", f"stat_error: {exc}", str(exc), sz=-1, out="stat_error", exc=exc)
    if size == 0:
        _fail("zero_byte", "rejected_zero_byte", "zero-byte file (size=0)", out="zero_byte")
    try:
        sha_val, size, header, truncated, alg = compute_bounded_file_digest(p)
    except OSError as exc:
        _fail("unreadable", f"read_error: {exc}", str(exc), sz=size, out="read_error", exc=exc)
    if not header.startswith(b"SQLite format 3\x00"):
        _fail(
            "corrupt_nonempty", "invalid_sqlite_header", "invalid SQLite header",
            sz=size, sha=sha_val if not truncated else None, out="corrupt_header",
        )

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA schema_version")
    except sqlite3.DatabaseError as exc:
        _fail(
            "corrupt_nonempty", f"sqlite_corrupt: {exc}", f"corrupt database ({exc})",
            sz=size, sha=sha_val if not truncated else None, out="corrupt_database", exc=exc,
        )
    finally:
        if conn is not None:
            conn.close()

    if pid_match in registered_children and registered_children[pid_match].get("strict"):
        import coverage
        data = coverage.CoverageData(basename=str(p))
        try:
            data.read()
            measured_files = sorted(data.measured_files())
            measured = (
                "selected_hits"
                if any(data.lines(f) for f in measured_files[:100])
                else "no_selected_hits"
            )
            if registered_children[pid_match].get("measurement") != measured:
                _fail(
                    "measurement_mismatch",
                    "receipt_content_mismatch",
                    "measurement content mismatch",
                )
        finally:
            if hasattr(data, "close"):
                data.close()


__all__ = (
    "ProcessObservationRecord",
    "ProcessObserver",
    "ShardDiagnosticSnapshot",
    "_annotate_snapshot",
    "classify_measured_files",
    "compute_bounded_file_digest",
    "compute_streaming_sha256",
    "create_shard_snapshot",
    "extract_child_probe_id",
    "extract_pid_match",
    "merge_diagnostic_snapshot",
    "record_diagnostic",
    "validate_shard_file",
)
