"""Opt-in descriptor-anchored structural advisory freshness (W4 Epic C §5.2)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import errno
import os
from pathlib import Path
import stat
from typing import Any

from common_lore_index.retrieval.context_contracts import (
    ADVISORY_FRESHNESS_SCHEMA_VERSION,
    FreshnessCheckConfig,
)

FRESHNESS_MAX_FILE_BYTES = 65536
FRESHNESS_MAX_SPAN_LINES = 80
FRESHNESS_MAX_FILES_PER_REQUEST = 16
FRESHNESS_MAX_AGGREGATE_BYTES = 262144
MAX_RELATIVE_PATH_CHARS = 4096

STRUCTURAL_LIMITS: tuple[str, ...] = (
    "structural_span_only",
    "no_lexical_anchor",
    "no_body_text",
)


def is_valid_freshness_relative_path(value: Any) -> bool:
    """Exact lexical grammar parity with tools.portable_handoff._relative (no NFC rewrite)."""
    if type(value) is not str or not (0 < len(value) <= MAX_RELATIVE_PATH_CHARS):
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    if value.startswith(("/", "~")) or ":" in value or "\\" in value:
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def make_freshness_observation(
    *,
    state: str,
    reason: str,
    limits: tuple[str, ...] = STRUCTURAL_LIMITS,
    inspected_span: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build per-location freshness observation in CONTEXT_FRESHNESS_OBS_KEYS order."""
    return {
        "state": state,
        "reason": reason,
        "limits": list(limits),
        "inspected_span": inspected_span,
    }


def reserve_freshness_observation(loc: Mapping[str, Any]) -> dict[str, Any]:
    """Worst-case byte reservation attached during budget admission before source opens."""
    start = loc.get("start_line")
    end = loc.get("end_line")
    span = (
        {"start_line": int(start), "end_line": int(end)}
        if type(start) is int and type(end) is int and 1 <= start <= end
        else None
    )
    return make_freshness_observation(
        state="no_change_observed_with_limits",
        reason="structural_span_only_no_lexical_anchor",
        limits=STRUCTURAL_LIMITS,
        inspected_span=span,
    )


def default_freshness_summary(*, state: str = "not_requested") -> dict[str, Any]:
    """Return initial packet-level freshness summary block."""
    return {
        "schema": ADVISORY_FRESHNESS_SCHEMA_VERSION,
        "state": state,
        "files_checked": 0,
        "bytes_read": 0,
        "counts": {
            "changed_observed": 0,
            "no_change_observed_with_limits": 0,
            "not_checked": 0,
            "unavailable": 0,
        },
    }


def _platform_supports_dir_fd_nofollow() -> bool:
    return (
        os.open in getattr(os, "supports_dir_fd", set())
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
    )


def _close_owned_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _line_counts(text: str) -> tuple[int, int]:
    """Return LF-only and Python splitlines counts for the decoded source."""
    splitlines_count = len(text.splitlines())
    lf_count = text.count("\n")
    if text and not text.endswith("\n"):
        lf_count += 1
    return lf_count, splitlines_count


def _open_freshness_root(root_path: Path) -> tuple[int | None, str]:
    """Open and validate one caller-selected root, returning a cached refusal on failure."""
    if not _platform_supports_dir_fd_nofollow():
        return None, "platform_unsupported"
    if not isinstance(root_path, Path) or not root_path.is_absolute():
        return None, "missing_root"

    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(str(root_path), dir_flags)
    except FileNotFoundError:
        return None, "missing_root"
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            return None, "symlink_or_traversal_rejected"
        return None, "missing_root"
    try:
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            _close_owned_fd(root_fd)
            return None, "missing_root"
    except OSError:
        _close_owned_fd(root_fd)
        return None, "read_error"
    except BaseException:
        _close_owned_fd(root_fd)
        raise
    return root_fd, ""


def _read_regular_file_anchored(
    root_fd: int,
    rel_path: str,
    *,
    remaining_aggregate_bytes: int,
    step_hook: Callable[[str], None] | None = None,
) -> tuple[str, str, tuple[int, int] | None, int]:
    """Open and read a source file using root-anchored directory descriptors.

    Returns (file_status, reason, line_counts_or_none, actual_bytes_read).
    """
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parts = rel_path.split("/")
    cur_fd = root_fd
    try:
        for part in parts[:-1]:
            if step_hook is not None:
                step_hook(part)
            try:
                next_fd = os.open(part, dir_flags, dir_fd=cur_fd)
            except FileNotFoundError:
                return "changed_observed", "file_missing", None, 0
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    return "unavailable", "symlink_or_traversal_rejected", None, 0
                return "unavailable", "read_error", None, 0
            try:
                st_dir = os.fstat(next_fd)
                if not stat.S_ISDIR(st_dir.st_mode):
                    _close_owned_fd(next_fd)
                    return "unavailable", "symlink_or_traversal_rejected", None, 0
            except OSError:
                _close_owned_fd(next_fd)
                return "unavailable", "read_error", None, 0
            except BaseException:
                _close_owned_fd(next_fd)
                raise
            if cur_fd != root_fd:
                _close_owned_fd(cur_fd)
            cur_fd = next_fd

        if step_hook is not None:
            step_hook(parts[-1])
        try:
            file_fd = os.open(parts[-1], file_flags, dir_fd=cur_fd)
        except FileNotFoundError:
            return "changed_observed", "file_missing", None, 0
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                return "unavailable", "symlink_or_traversal_rejected", None, 0
            return "unavailable", "unsafe_or_nonregular_file", None, 0

        bytes_read = 0
        try:
            st_file = os.fstat(file_fd)
            if not stat.S_ISREG(st_file.st_mode):
                return "unavailable", "unsafe_or_nonregular_file", None, 0
            if st_file.st_size > FRESHNESS_MAX_FILE_BYTES:
                return "unavailable", "file_size_limit", None, 0
            if st_file.st_size > remaining_aggregate_bytes:
                return "not_checked", "byte_limit", None, 0

            max_to_read = min(FRESHNESS_MAX_FILE_BYTES, remaining_aggregate_bytes)
            chunks: list[bytes] = []
            while True:
                want = min(16384, max_to_read - bytes_read)
                if want <= 0:
                    break
                chunk = os.read(file_fd, want)
                if not chunk:
                    break
                bytes_read += len(chunk)
                chunks.append(chunk)

            st_after = os.fstat(file_fd)
            if st_after.st_size > FRESHNESS_MAX_FILE_BYTES:
                return "unavailable", "file_size_limit", None, bytes_read
            if st_after.st_size > remaining_aggregate_bytes:
                return "not_checked", "byte_limit", None, bytes_read

            raw = b"".join(chunks)
            if b"\x00" in raw:
                return "unavailable", "invalid_utf8", None, bytes_read
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                return "unavailable", "invalid_utf8", None, bytes_read
            return "ok", "ok", _line_counts(text), bytes_read
        except OSError:
            return "unavailable", "read_error", None, bytes_read
        finally:
            _close_owned_fd(file_fd)
    finally:
        if cur_fd != root_fd:
            _close_owned_fd(cur_fd)


def evaluate_packet_freshness(
    packet: dict[str, Any],
    config: FreshnessCheckConfig | None,
    *,
    selected_bindings: set[str] | None = None,
    step_hook: Callable[[str], None] | None = None,
) -> None:
    """Evaluate opt-in structural freshness across admitted items and neighbors in place."""
    if config is None or not config.enabled:
        packet["freshness"] = default_freshness_summary(state="not_requested")
        for group_key in ("items", "neighbors"):
            for item in packet.get(group_key, ()):
                for loc in item.get("locations", ()):
                    loc["freshness"] = None
        return

    summary = default_freshness_summary(state="checked")
    counts = summary["counts"]
    files_checked = 0
    bytes_read = 0
    file_cache: dict[tuple[str, str], tuple[str, str, tuple[int, int] | None]] = {}
    root_cache: dict[str, tuple[int | None, str]] = {}
    root_fds: list[int] = []

    try:
        for group_key in ("items", "neighbors"):
            for item in packet.get(group_key, ()):
                id_state = item.get("identity_state")
                for loc in item.get("locations", ()):
                    bid = loc.get("source_binding_id")
                    rel = loc.get("source_relative_path")
                    pub_rel = loc.get("publication_relation")
                    start = loc.get("start_line")
                    end = loc.get("end_line")
                    has_span = type(start) is int and type(end) is int and 1 <= start <= end
                    span_obj = {"start_line": int(start), "end_line": int(end)} if has_span else None

                    if (
                        id_state != "verified"
                        or pub_rel != "accepted_run"
                        or not isinstance(bid, str)
                        or not bid
                        or (selected_bindings is not None and bid not in selected_bindings)
                    ):
                        loc["freshness"] = make_freshness_observation(
                            state="not_checked", reason="ineligible_location", inspected_span=None
                        )
                        counts["not_checked"] += 1
                        continue

                    if not is_valid_freshness_relative_path(rel):
                        loc["freshness"] = make_freshness_observation(
                            state="unavailable", reason="symlink_or_traversal_rejected", inspected_span=None
                        )
                        counts["unavailable"] += 1
                        continue

                    if has_span and (int(end) - int(start) + 1) > FRESHNESS_MAX_SPAN_LINES:
                        loc["freshness"] = make_freshness_observation(
                            state="not_checked", reason="line_limit", inspected_span=span_obj
                        )
                        counts["not_checked"] += 1
                        continue

                    root_path = config.source_roots.get(bid)
                    if root_path is None:
                        loc["freshness"] = make_freshness_observation(
                            state="unavailable", reason="unmapped_binding", inspected_span=None
                        )
                        counts["unavailable"] += 1
                        continue

                    cache_key = (bid, str(rel))
                    if cache_key not in file_cache:
                        if files_checked >= FRESHNESS_MAX_FILES_PER_REQUEST:
                            f_status, f_reason, lines, read_now = (
                                "not_checked", "file_limit", None, 0
                            )
                        else:
                            remaining = FRESHNESS_MAX_AGGREGATE_BYTES - bytes_read
                            if remaining <= 0:
                                f_status, f_reason, lines, read_now = (
                                    "not_checked", "byte_limit", None, 0
                                )
                            else:
                                files_checked += 1
                                root_entry = root_cache.get(bid)
                                if root_entry is None:
                                    root_entry = _open_freshness_root(Path(root_path))
                                    root_cache[bid] = root_entry
                                    if root_entry[0] is not None:
                                        root_fds.append(root_entry[0])
                                root_fd, root_reason = root_entry
                                if root_fd is None:
                                    f_status, f_reason, lines, read_now = (
                                        "unavailable", root_reason, None, 0
                                    )
                                else:
                                    f_status, f_reason, lines, read_now = _read_regular_file_anchored(
                                        root_fd,
                                        str(rel),
                                        remaining_aggregate_bytes=remaining,
                                        step_hook=step_hook,
                                    )
                            bytes_read += read_now
                        file_cache[cache_key] = (f_status, f_reason, lines)

                    f_status, f_reason, lines = file_cache[cache_key]
                    if f_status != "ok" or lines is None:
                        loc["freshness"] = make_freshness_observation(
                            state=f_status, reason=f_reason, inspected_span=None
                        )
                        counts[f_status] += 1
                        continue

                    if not has_span:
                        loc["freshness"] = make_freshness_observation(
                            state="no_change_observed_with_limits",
                            reason="file_presence_and_utf8_only",
                            inspected_span=None,
                        )
                        counts["no_change_observed_with_limits"] += 1
                    else:
                        lf_beyond_eof = int(end) > lines[0]
                        splitlines_beyond_eof = int(end) > lines[1]
                        if lf_beyond_eof != splitlines_beyond_eof:
                            loc["freshness"] = make_freshness_observation(
                                state="unavailable",
                                reason="line_semantics",
                                inspected_span=span_obj,
                            )
                            counts["unavailable"] += 1
                        elif splitlines_beyond_eof:
                            loc["freshness"] = make_freshness_observation(
                                state="changed_observed",
                                reason="span_beyond_eof",
                                inspected_span=span_obj,
                            )
                            counts["changed_observed"] += 1
                        else:
                            loc["freshness"] = make_freshness_observation(
                                state="no_change_observed_with_limits",
                                reason="structural_span_only_no_lexical_anchor",
                                inspected_span=span_obj,
                            )
                            counts["no_change_observed_with_limits"] += 1
    finally:
        for root_fd in root_fds:
            _close_owned_fd(root_fd)

    summary["files_checked"] = files_checked
    summary["bytes_read"] = bytes_read
    packet["freshness"] = summary
