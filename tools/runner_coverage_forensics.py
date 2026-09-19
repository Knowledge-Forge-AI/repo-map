"""Bounded SQLite reader and forensics for anomalous coverage shards."""

from __future__ import annotations

import ast
from collections.abc import Sequence
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any

MAX_FORENSIC_PATHS: int = 100


def classify_measured_files(
    file_paths: Sequence[str],
    source_root: Path | None = None,
    checkout_root: Path | None = None,
    *,
    max_paths: int = 100,
) -> dict[str, Any]:
    counts = {
        "inside_selected_source": 0,
        "inside_checkout_outside_selected_source": 0,
        "outside_checkout": 0,
        "unreadable_or_invalid": 0,
    }
    retained_samples: list[dict[str, Any]] = []
    src = source_root.resolve() if source_root else None
    chk = checkout_root.resolve() if checkout_root else None
    inspected = file_paths[:max_paths]

    for p_str in inspected:
        try:
            if not p_str or "\x00" in p_str:
                raise ValueError("invalid path characters")
            res = Path(p_str).resolve()
            if src and (res == src or src in res.parents):
                cat = "inside_selected_source"
                safe_repr = str(res.relative_to(src))
            elif chk and (res == chk or chk in res.parents):
                cat = "inside_checkout_outside_selected_source"
                safe_repr = str(res.relative_to(chk))
            else:
                cat = "outside_checkout"
                h = hashlib.sha256(p_str.encode("utf-8")).hexdigest()[:12]
                safe_repr = f"<external:{h}>"
        except (ValueError, OSError):
            cat = "unreadable_or_invalid"
            safe_repr = "<invalid_path>"

        counts[cat] += 1
        if len(retained_samples) < 25:
            retained_samples.append({
                "category": cat,
                "digest": hashlib.sha256(
                    p_str.encode("utf-8", errors="replace")
                ).hexdigest()[:16],
                "safe_label": safe_repr,
            })

    return {
        "observed_total": len(file_paths),
        "retained_count": len(inspected),
        "truncated": len(file_paths) > max_paths,
        "classification": counts,
        "retained_samples": retained_samples,
        **counts,
        "inside_source_root": counts["inside_selected_source"],
        "inside_checkout_outside_root": counts[
            "inside_checkout_outside_selected_source"
        ],
    }


def _get_expected_schema_version() -> int | None:
    try:
        import coverage.sqldata

        if hasattr(coverage.sqldata, "SCHEMA_VERSION"):
            return int(coverage.sqldata.SCHEMA_VERSION)
    except (ImportError, AttributeError, ValueError, TypeError):
        pass
    try:
        import coverage

        if hasattr(coverage, "CoverageData") and hasattr(
            coverage.CoverageData, "SCHEMA_VERSION"
        ):
            return int(coverage.CoverageData.SCHEMA_VERSION)
    except (ImportError, AttributeError, ValueError, TypeError):
        pass
    return None


def _sanitize_argv(raw: str, max_bytes: int = 256) -> str:
    bounded = raw[:4096]
    cleaned = re.sub(
        r"(?:[a-zA-Z]:[/\\]|[/\\]|\b[a-zA-Z0-9_.\-]+[/\\])[a-zA-Z0-9_.\-/\\]*",
        "[path]",
        bounded,
    )
    cleaned = re.sub(
        r"(?i)(password|token|secret|key)([\'\":=\s]+)\S+",
        r"\1\2[REDACTED]",
        cleaned,
    )
    encoded = cleaned.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return cleaned
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _derive_launch_shape(raw_argv: str) -> str:
    try:
        parsed = ast.literal_eval(raw_argv[:4096])
        items = [str(x) for x in parsed] if isinstance(parsed, (list, tuple)) else []
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return "unparseable_argv"
    if not items:
        return "empty_argv"
    for i, a in enumerate(items):
        if a == "-c" and i + 1 < len(items):
            cmd = items[i + 1]
            prefix = "from multiprocessing.resource_tracker import main;main("
            if i + 2 == len(items) and cmd.startswith(prefix) and cmd.endswith(")"):
                inner = cmd[len(prefix) : -1].strip()
                if inner.isdigit():
                    return "cpython:resource_tracker"
            return "cpython:-c"
        if a == "-m" and i + 1 < len(items):
            return f"-m:{items[i + 1][:24]}"
        if a.endswith(".py"):
            return f"script:{Path(a).name[:24]}"
    a0 = items[0]
    if a0.endswith(".py"):
        return f"script:{Path(a0).name[:24]}"
    if a0 == "-c":
        return "cpython:-c"
    if a0 == "-m":
        return "-m"
    return "unknown"


def read_anomalous_shard_forensics(
    shard_path: Path,
    data_dir: Path,
    *,
    source_root: Path | None = None,
    checkout_root: Path | None = None,
    max_paths: int = MAX_FORENSIC_PATHS,
) -> tuple[bool, int | None, dict[str, Any] | None, str | None]:
    """Inspect an anomalous shard boundedly using read-only SQLite queries.

    Never invokes CoverageData.measured_files() or materializes the full file table.
    Returns (sqlite_valid, measured_files_count, measured_classification, failure_verdict).
    """
    p = Path(shard_path)
    d = Path(data_dir)

    # 1. Path containment and regularity
    if p.is_symlink():
        return False, None, None, "shard_symlink_rejected"
    if not p.is_file():
        return False, None, None, "shard_not_a_file"

    try:
        p_res = p.resolve()
        d_res = d.resolve()
        if p_res.parent != d_res:
            return False, None, None, "unauthorized_shard_location"
    except OSError as exc:
        return False, None, None, f"path_resolution_error:{exc}"

    # 2. Read-only SQLite connection
    conn: sqlite3.Connection | None = None
    ret: tuple[bool, int | None, dict[str, Any] | None, str | None]
    try:
        uri_imm = f"{p_res.as_uri()}?mode=ro&immutable=1"
        try:
            conn = sqlite3.connect(uri_imm, uri=True)
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            uri_ro = f"{p_res.as_uri()}?mode=ro"
            conn = sqlite3.connect(uri_ro, uri=True)

        # 3. Verify schema table and expected version
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coverage_schema'"
        )
        if cursor.fetchone() is None:
            ret = (False, None, None, "missing_coverage_schema_table")
        else:
            cursor.execute("SELECT version FROM coverage_schema LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                ret = (False, None, None, "empty_coverage_schema_table")
            else:
                observed_version = row[0]
                expected_version = _get_expected_schema_version()
                if expected_version is None:
                    ret = (False, None, None, "coverage_schema_introspection_failed")
                elif observed_version != expected_version:
                    ret = (
                        False,
                        None,
                        None,
                        f"unsupported_coverage_schema:observed={observed_version}:expected={expected_version}",
                    )
                else:
                    # 4. Verify file table
                    cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file'"
                    )
                    if cursor.fetchone() is None:
                        ret = (False, None, None, "missing_file_table")
                    else:
                        # 5. Bounded COUNT query
                        cursor.execute("SELECT COUNT(*) FROM file")
                        count_row = cursor.fetchone()
                        observed_total = int(count_row[0]) if count_row else 0

                        sys_argv_val: str | None = None
                        launch_shape_val: str | None = None
                        cursor.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
                        )
                        if cursor.fetchone() is not None:
                            cursor.execute(
                                "SELECT value FROM meta WHERE key='sys_argv' LIMIT 1"
                            )
                            meta_row = cursor.fetchone()
                            if meta_row and meta_row[0]:
                                raw_str = str(meta_row[0])[:4096]
                                sys_argv_val = _sanitize_argv(raw_str)
                                launch_shape_val = _derive_launch_shape(raw_str)
                            else:
                                launch_shape_val = "meta_sys_argv_absent"
                        else:
                            launch_shape_val = "meta_table_absent"

                        if observed_total == 0:
                            zero_classification = {
                                "observed_total": 0,
                                "retained_count": 0,
                                "truncated": False,
                                "classification": {
                                    "inside_selected_source": 0,
                                    "inside_checkout_outside_selected_source": 0,
                                    "outside_checkout": 0,
                                    "unreadable_or_invalid": 0,
                                },
                                "retained_samples": [],
                                "inside_selected_source": 0,
                                "inside_checkout_outside_selected_source": 0,
                                "outside_checkout": 0,
                                "unreadable_or_invalid": 0,
                                "inside_source_root": 0,
                                "inside_checkout_outside_root": 0,
                            }
                            if sys_argv_val is not None:
                                zero_classification["sys_argv"] = sys_argv_val
                            if launch_shape_val is not None:
                                zero_classification["launch_shape"] = launch_shape_val
                            ret = (True, 0, zero_classification, None)
                        else:
                            # 6. Bounded path query with LIMIT max_paths + 1
                            limit_bound = max_paths + 1
                            cursor.execute("SELECT path FROM file LIMIT ?", (limit_bound,))
                            file_rows = cursor.fetchall()
                            candidate_paths = [str(r[0]) for r in file_rows[:max_paths]]

                            # 7. Classify bounded paths and enforce count/truncated authority
                            forensic_result = classify_measured_files(
                                candidate_paths,
                                source_root=source_root,
                                checkout_root=checkout_root or Path.cwd(),
                                max_paths=max_paths,
                            )
                            forensic_result["observed_total"] = observed_total
                            forensic_result["retained_count"] = len(candidate_paths)
                            forensic_result["truncated"] = observed_total > max_paths
                            if sys_argv_val is not None:
                                forensic_result["sys_argv"] = sys_argv_val
                            if launch_shape_val is not None:
                                forensic_result["launch_shape"] = launch_shape_val

                            ret = (True, observed_total, forensic_result, None)

    except sqlite3.DatabaseError as exc:
        ret = (False, None, None, f"sqlite_error:{exc}")
    except (OSError, ValueError, TypeError) as exc:
        ret = (False, None, None, f"forensics_error:{exc}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    return ret


__all__ = (
    "MAX_FORENSIC_PATHS",
    "classify_measured_files",
    "read_anomalous_shard_forensics",
)
