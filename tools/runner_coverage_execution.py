"""Execution helpers, shard diagnostics, and combine orchestration for coverage runner."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import sqlite3

from runner_coverage_receipts import read_registered_children as read_registered_children
from runner_coverage_combine import execute_shard_combine as execute_shard_combine

from typing import Any


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
    run_id: str | None = None
    source_selection: list[str] | None = None
    coverage_version: str | None = None
    child_probe_id: str | None = None
    termination_outcome: str | None = None
    launch_role: str | None = None
    test_owner: str | None = None
    ppid: int | None = None
    launch_shape: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "shard_name": self.shard_name,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "reader_status": self.reader_status,
            "stage": self.stage,
            "run_id": self.run_id,
            "source_selection": self.source_selection,
            "coverage_version": self.coverage_version,
            "child_probe_id": self.child_probe_id,
            "termination_outcome": self.termination_outcome,
            "launch_role": self.launch_role,
            "test_owner": self.test_owner,
            "ppid": self.ppid,
            "launch_shape": self.launch_shape,
        }


def extract_pid_match(name: str) -> int | None:
    if ".pid" in name:
        try:
            return int(name.split(".pid", 1)[1].split(".", 1)[0])
        except Exception:
            pass
    for t in name.split("."):
        try:
            if t.startswith("pid") and t[3:].isdigit():
                return int(t[3:])
            if t.isdigit() and len(t) >= 2:
                return int(t)
        except Exception:
            pass
    return None


def extract_child_probe_id(shard_name: str) -> str | None:
    pid = extract_pid_match(shard_name)
    return f"pid={pid}" if pid is not None else None


def create_shard_snapshot(
    *, session_name: str, shard_name: str, file_type: str, size_bytes: int,
    sha256: str | None, reader_status: str, stage: str, coverage_module: Any = None,
    source_root: Path | None = None, source_paths: tuple[Path, ...] = (),
    child_probe_id: str | None = None, termination_outcome: str | None = None,
    launch_role: str | None = None, test_owner: str | None = None,
    ppid: int | None = None, launch_shape: str | None = None,
) -> ShardDiagnosticSnapshot:
    run_id = os.environ.get("GITHUB_RUN_ID") or os.environ.get("REPO_MAP_RUN_ID") or session_name
    src_sel = [str(p) for p in source_paths] if source_paths else ([str(source_root)] if source_root else None)
    cov_ver = getattr(coverage_module, "__version__", None)
    if child_probe_id is None:
        child_probe_id = extract_child_probe_id(shard_name)
    return ShardDiagnosticSnapshot(
        session_id=session_name, shard_name=shard_name, file_type=file_type,
        size_bytes=size_bytes, sha256=sha256, reader_status=reader_status,
        stage=stage, run_id=run_id, source_selection=src_sel,
        coverage_version=cov_ver, child_probe_id=child_probe_id,
        termination_outcome=termination_outcome,
        launch_role=launch_role, test_owner=test_owner,
        ppid=ppid, launch_shape=launch_shape,
    )


def record_diagnostic(
    snapshots: list[ShardDiagnosticSnapshot],
    snapshot: ShardDiagnosticSnapshot,
    session_dir: Path,
) -> None:
    snapshots.append(snapshot)
    snapshot_file = session_dir / "coverage_anomaly_snapshot.json"
    try:
        snapshot_file.write_text(json.dumps([s.to_dict() for s in snapshots], indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_candidate_shard(child_manifest_dir: Path, pid: int) -> str | None:
    for marker in (child_manifest_dir / f"{pid}.shard", child_manifest_dir / f"{pid}.exit"):
        if marker.is_file() and not marker.is_symlink():
            try:
                text = marker.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.startswith("shard="):
                        cand = line.split("shard=", 1)[1].strip()
                        if cand:
                            return cand
                stripped = text.strip()
                if stripped and not stripped.startswith("pid="):
                    return stripped
            except OSError:
                pass
    return None


def identify_parent_shard(
    runner: Any,
    data_dir: Path,
    expected_data_file: str | None = None,
) -> str | None:
    if runner is None:
        return None
    cand: str | None = None
    try:
        if hasattr(runner, "get_data"):
            d = runner.get_data()
            if d is not None and hasattr(d, "data_filename"):
                cand = d.data_filename()
        if not cand and hasattr(runner, "_data"):
            cand = getattr(runner._data, "_filename", None)
        if not cand and expected_data_file:
            cand = expected_data_file
        elif not cand and hasattr(runner, "data_file"):
            df = getattr(runner, "data_file", None)
            if df and Path(df).is_file():
                cand = str(df)
    except Exception:
        pass
    if cand:
        cand_path = Path(cand)
        if cand_path.is_symlink():
            raise RuntimeError(f"parent coverage shard is a symlink: {cand_path}")
        if cand_path.is_file() and cand_path.parent == data_dir.resolve():
            return str(cand_path)
    return None


def _annotate_snapshot(snap: ShardDiagnosticSnapshot, child_info: dict[str, Any]) -> ShardDiagnosticSnapshot:
    return replace(snap, ppid=child_info.get("ppid"), launch_shape=child_info.get("launch_shape"))


def reconcile_child_manifests(
    registered_children: dict[int, dict[str, Any]],
    shard_paths_set: set[str],
    child_manifest_dir: Path,
    parent_data_path: str,
    parent_pid: int,
    snapshot_fn: Callable[..., ShardDiagnosticSnapshot],
    record_fn: Callable[[ShardDiagnosticSnapshot], None],
    cov_mod: Any = None,
) -> tuple[dict[int, str], set[str]]:
    consumed_shards_by_child: dict[int, str] = {}
    consumed_shard_paths: set[str] = set()

    for pid, child_info in sorted(registered_children.items()):
        exited = bool(child_info["exited"])
        cov_start = int(child_info["cov_start"])
        if cov_start == 0:
            if child_info.get("auxiliary") or child_info.get("role") == "auxiliary-runtime":
                snap = _annotate_snapshot(snapshot_fn(
                    shard_name=f"auxiliary.pid{pid}", file_type="auxiliary_runtime",
                    size_bytes=0, sha256=None, reader_status="auxiliary_process_exempted",
                    stage="pre_combine", cov_mod=cov_mod, child_probe_id=f"pid={pid}",
                    termination_outcome="auxiliary_runtime_exempt",
                    launch_role="auxiliary-runtime", test_owner=child_info.get("owner"),
                ), child_info)
                record_fn(snap)
                continue
            snap = _annotate_snapshot(snapshot_fn(
                shard_name=f"uninstrumented.pid{pid}", file_type="uninstrumented",
                size_bytes=0, sha256=None,
                reader_status=f"coverage_not_started:{child_info.get('bootstrap_error', 'unknown')}",
                stage="pre_combine", cov_mod=cov_mod, child_probe_id=f"pid={pid}",
                termination_outcome="uninstrumented_child",
                launch_role=child_info.get("role"), test_owner=child_info.get("owner"),
            ), child_info)
            record_fn(snap)
            raise RuntimeError("child coverage bootstrap failed")

        if child_info.get("terminal_error"):
            raise RuntimeError("child reported coverage save failure")
        if child_info.get("strict") and not exited:
            snap = _annotate_snapshot(snapshot_fn(
                shard_name=f"unsettled.pid{pid}", file_type="incomplete_terminal",
                size_bytes=0, sha256=None, reader_status="terminal_receipt_incomplete",
                stage="pre_combine", cov_mod=cov_mod, child_probe_id=f"pid={pid}",
                termination_outcome=("declared_abrupt_measurement_incomplete"
                                     if child_info.get("role") == "conformance-abrupt"
                                     else "unknown_termination_measurement_incomplete"),
                launch_role=child_info.get("role"), test_owner=child_info.get("owner"),
            ), child_info)
            record_fn(snap)
            raise RuntimeError("child terminal receipt is incomplete")

        cand_shard = (child_info.get("shard") if child_info.get("strict")
                      else _read_candidate_shard(child_manifest_dir, pid))
        has_shard = False
        if cand_shard:
            candidate_path = Path(cand_shard)
            if candidate_path.is_symlink():
                raise RuntimeError("child coverage shard symlink rejected")
            if candidate_path.parent.resolve() != Path(parent_data_path).parent.resolve():
                raise RuntimeError("child coverage shard escapes invocation data directory")
            resolved_cand = str(Path(cand_shard).resolve())
            cand_name = Path(resolved_cand).name
            cand_tokens = cand_name.split(".")
            is_parent = (
                resolved_cand == parent_data_path
                or ".parent." in cand_name
                or str(parent_pid) in cand_tokens
            )
            child_token = child_info.get("token")
            attributable = (
                str(pid) in cand_tokens
                or f"pid{pid}" in cand_tokens
                or (child_token is not None and child_token in cand_tokens)
            )
            if (
                resolved_cand in shard_paths_set
                and not is_parent
                and attributable
                and resolved_cand not in consumed_shard_paths
            ):
                has_shard = True
                consumed_shards_by_child[pid] = resolved_cand
                consumed_shard_paths.add(resolved_cand)

        if not has_shard:
            if child_info.get("auxiliary") or child_info.get("role") == "auxiliary-runtime":
                snap = _annotate_snapshot(snapshot_fn(
                    shard_name=f"auxiliary.pid{pid}", file_type="auxiliary_runtime",
                    size_bytes=0, sha256=None, reader_status="auxiliary_shard_exempted",
                    stage="pre_combine", cov_mod=cov_mod, child_probe_id=f"pid={pid}",
                    termination_outcome="auxiliary_runtime_exempt",
                    launch_role="auxiliary-runtime", test_owner=child_info.get("owner"),
                ), child_info)
                record_fn(snap)
                continue
            is_alive = False
            if not exited:
                try:
                    os.kill(pid, 0)
                    is_alive = True
                except OSError:
                    is_alive = False

            term_outcome: str = (
                "clean_exit_no_shard"
                if exited
                else ("live_child_no_shard" if is_alive else "abrupt_termination_no_shard")
            )
            snap = _annotate_snapshot(snapshot_fn(
                shard_name=f"missing.pid{pid}", file_type="missing", size_bytes=0,
                sha256=None, reader_status="no_shard_produced", stage="pre_combine",
                cov_mod=cov_mod, child_probe_id=f"pid={pid}",
                termination_outcome=term_outcome,
                launch_role=child_info.get("role"), test_owner=child_info.get("owner"),
            ), child_info)
            record_fn(snap)
            raise RuntimeError(
                f"coverage shard for child PID {pid} is missing: "
                f"child process executed without producing coverage data"
            )

    return consumed_shards_by_child, consumed_shard_paths



def validate_shard_file(
    sp: str,
    registered_children: dict[int, dict[str, Any]],
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
        term_outcome = "clean_exit" if registered_children[pid_match]["exited"] else "abrupt_termination"
    probe_id = f"pid={pid_match}" if pid_match else None

    def _fail(ft: str, rs: str, msg: str, sz: int = 0, sha: str | None = None, out: str = "error", exc: Exception | None = None) -> None:
        snap = snapshot_fn(
            shard_name=p.name, file_type=ft, size_bytes=sz, sha256=sha, reader_status=rs,
            stage="pre_combine", cov_mod=cov_mod, child_probe_id=probe_id,
            termination_outcome=term_outcome or out,
        )
        record_fn(snap)
        err = f"coverage shard {sp} is empty or unreadable: {msg}"
        raise RuntimeError(err) from exc if exc else RuntimeError(err)

    if not p.is_file():
        _fail("not_a_file", "not_a_regular_file", "not a regular file", out="not_a_file")
    try:
        size = p.stat().st_size
    except OSError as exc:
        _fail("unreadable", f"stat_error: {exc}", str(exc), sz=-1, out="stat_error", exc=exc)
    if size == 0:
        _fail("zero_byte", "rejected_zero_byte", "zero-byte file (size=0)", out="zero_byte")
    try:
        with open(p, "rb") as stream:
            header = stream.read(16)
    except OSError as exc:
        _fail("unreadable", f"read_error: {exc}", str(exc), sz=size, out="read_error", exc=exc)
    if header != b"SQLite format 3\x00":
        try:
            sha_val = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            sha_val = None
        _fail("corrupt_nonempty", "invalid_sqlite_header", "invalid SQLite header", sz=size, sha=sha_val, out="corrupt_header")

    conn = None
    try:
        conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA schema_version")
    except sqlite3.DatabaseError as exc:
        try:
            sha_val = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            sha_val = None
        _fail("corrupt_nonempty", f"sqlite_corrupt: {exc}", f"corrupt database ({exc})", sz=size, sha=sha_val, out="corrupt_database", exc=exc)
    finally:
        if conn is not None:
            conn.close()
    if pid_match in registered_children and registered_children[pid_match].get("strict"):
        import coverage

        data = coverage.CoverageData(basename=str(p))
        try:
            data.read()
            measured = "selected_hits" if any(data.lines(f) for f in data.measured_files()) else "no_selected_hits"
            if registered_children[pid_match].get("measurement") != measured:
                _fail("measurement_mismatch", "receipt_content_mismatch", "measurement content mismatch")
        finally:
            if hasattr(data, "close"):
                data.close()
