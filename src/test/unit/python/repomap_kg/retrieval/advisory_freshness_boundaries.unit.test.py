"""Root identity, read-allocation and descriptor regressions for advisory freshness."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from common_lore_index.retrieval import advisory_freshness as advisory_freshness_module
from common_lore_index.retrieval.advisory_freshness import (
    FRESHNESS_MAX_AGGREGATE_BYTES,
    FRESHNESS_MAX_FILE_BYTES,
    evaluate_packet_freshness,
    reserve_freshness_observation,
)
from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest, FreshnessCheckConfig
from repomap_test_support.context_fixture import BINDING_CORE, build_sqlite_context_fixture


def _current_packet_for_paths(
    tmp_path: Path,
    relative_paths: tuple[str, ...],
    *,
    end_line: int = 1,
) -> tuple[dict[str, Any], Path]:
    """Reuse a directly admitted fixture location while selecting tmp_path files."""
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    packet = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="exact_identity",
            canonical_key="py:pkg.billing.InvoiceService",
            freshness="none",
        ),
        adapter,
    )
    assert len(packet["items"]) == 1
    source_location = packet["items"][0]["locations"][0]
    packet["neighbors"] = []
    packet["items"][0]["locations"] = [
        {
            **source_location,
            "source_relative_path": relative_path,
            "start_line": 1,
            "end_line": end_line,
            "freshness": None,
        }
        for relative_path in relative_paths
    ]
    return packet, tmp_path / "src_core"


def test_root_stays_anchored_for_one_invocation_but_reopens_next_invocation(
    tmp_path: Path,
) -> None:
    relative_paths = ("first.py", "second.py")
    packet, root = _current_packet_for_paths(tmp_path, relative_paths, end_line=3)
    (root / "first.py").write_text("first\nline two\nline three\n", encoding="utf-8")
    (root / "second.py").write_text("original\nline two\nline three\n", encoding="utf-8")

    replacement = tmp_path / "replacement-root"
    replacement.mkdir()
    (replacement / "second.py").write_text("replacement\n", encoding="utf-8")
    retired = tmp_path / "retired-root"
    swapped = False

    def swap_root_after_first_file_is_admitted(step: str) -> None:
        nonlocal swapped
        if step in relative_paths and not swapped:
            root.rename(retired)
            replacement.rename(root)
            swapped = True

    config = FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root})
    evaluate_packet_freshness(packet, config, step_hook=swap_root_after_first_file_is_admitted)

    locations = packet["items"][0]["locations"]
    assert swapped
    assert {location["freshness"]["state"] for location in locations} == {
        "no_change_observed_with_limits"
    }
    assert {location["freshness"]["reason"] for location in locations} == {
        "structural_span_only_no_lexical_anchor"
    }

    # A new invocation is allowed to select the replacement now at the caller's path.
    evaluate_packet_freshness(packet, config)
    assert locations[1]["freshness"]["state"] == "changed_observed"
    assert locations[1]["freshness"]["reason"] == "span_beyond_eof"


def test_concurrent_growth_never_reads_past_file_or_request_byte_caps(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    relative_paths = tuple(f"bounded-{index}.txt" for index in range(5))
    packet, root = _current_packet_for_paths(tmp_path, relative_paths)
    for relative_path in relative_paths:
        (root / relative_path).write_bytes(b"x" * FRESHNESS_MAX_FILE_BYTES)

    real_open = os.open
    real_close = os.close
    real_read = os.read
    file_for_fd: dict[int, Path] = {}
    next_file = 0
    grown: set[Path] = set()
    read_requests: list[int] = []
    read_lengths: list[int] = []
    bytes_by_file: dict[Path, int] = {}

    def tracking_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal next_file
        fd = real_open(path, flags, *args, **kwargs)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            assert next_file < len(relative_paths)
            file_for_fd[fd] = root / relative_paths[next_file]
            next_file += 1
        return fd

    def tracking_close(fd: int) -> None:
        file_for_fd.pop(fd, None)
        real_close(fd)

    def growing_read(fd: int, requested: int) -> bytes:
        file_path = file_for_fd[fd]
        if file_path not in grown:
            # Grow after the product's pre-read stat, then delegate to the real syscall.
            file_path.write_bytes(b"x" * (FRESHNESS_MAX_FILE_BYTES + 1))
            grown.add(file_path)
        chunk = real_read(fd, requested)
        assert len(chunk) <= requested
        read_requests.append(requested)
        read_lengths.append(len(chunk))
        bytes_by_file[file_path] = bytes_by_file.get(file_path, 0) + len(chunk)
        return chunk

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracking_open})
    monkeypatch.setattr(os, "close", tracking_close)
    monkeypatch.setattr(os, "read", growing_read)
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
    )

    assert read_requests
    assert sum(read_lengths) == packet["freshness"]["bytes_read"]
    assert packet["freshness"]["bytes_read"] == FRESHNESS_MAX_AGGREGATE_BYTES
    assert packet["freshness"]["files_checked"] == 4
    assert all(total <= FRESHNESS_MAX_FILE_BYTES for total in bytes_by_file.values())
    assert set(bytes_by_file) == {root / relative_path for relative_path in relative_paths[:4]}
    assert all(
        location["freshness"]["reason"] == "file_size_limit"
        for location in packet["items"][0]["locations"][:4]
    )
    assert packet["items"][0]["locations"][4]["freshness"]["state"] == "not_checked"
    assert packet["items"][0]["locations"][4]["freshness"]["reason"] == "byte_limit"
    assert not file_for_fd


def test_owned_descriptors_close_for_regular_and_nonregular_results(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    relative_paths = ("nested/ok.py", "nested/not_a_file")
    packet, root = _current_packet_for_paths(tmp_path, relative_paths, end_line=2)
    nested = root / "nested"
    nested.mkdir()
    (nested / "ok.py").write_text("line one\nline two\n", encoding="utf-8")
    os.mkfifo(nested / "not_a_file")

    real_open = os.open
    real_close = os.close
    active_fds: set[int] = set()

    def tracking_open(*args: Any, **kwargs: Any) -> int:
        fd = real_open(*args, **kwargs)
        active_fds.add(fd)
        return fd

    def tracking_close(fd: int) -> None:
        assert fd in active_fds
        active_fds.remove(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracking_open})
    monkeypatch.setattr(os, "close", tracking_close)
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
    )

    assert not active_fds
    locations = packet["items"][0]["locations"]
    assert locations[0]["freshness"]["state"] == "no_change_observed_with_limits"
    assert locations[1]["freshness"]["state"] == "unavailable"
    assert locations[1]["freshness"]["reason"] == "unsafe_or_nonregular_file"


def test_file_attempt_cap_counts_pre_read_refusals_and_reuses_cached_results(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    blocked_paths = tuple(f"blocked-{index}.txt" for index in range(12))
    relative_paths = (
        "full-0.txt",
        "full-1.txt",
        "full-2.txt",
        "one-byte.txt",
        *blocked_paths,
        blocked_paths[0],
        "after-cap.txt",
    )
    packet, root = _current_packet_for_paths(tmp_path, relative_paths)
    for relative_path in relative_paths[:3]:
        (root / relative_path).write_bytes(b"x" * FRESHNESS_MAX_FILE_BYTES)
    (root / "one-byte.txt").write_bytes(b"x")
    for relative_path in blocked_paths:
        (root / relative_path).write_bytes(b"x" * FRESHNESS_MAX_FILE_BYTES)
    (root / "after-cap.txt").write_bytes(b"x" * FRESHNESS_MAX_FILE_BYTES)

    real_open = os.open
    opened_files = 0

    def tracking_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal opened_files
        fd = real_open(path, flags, *args, **kwargs)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            opened_files += 1
        return fd

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracking_open})
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
    )

    assert opened_files == 16
    assert packet["freshness"]["files_checked"] == 16
    assert packet["freshness"]["bytes_read"] == (3 * FRESHNESS_MAX_FILE_BYTES) + 1
    locations = packet["items"][0]["locations"]
    assert locations[4]["freshness"]["reason"] == "byte_limit"
    assert locations[16]["freshness"]["reason"] == "byte_limit"
    assert locations[17]["freshness"] == {
        "state": "not_checked",
        "reason": "file_limit",
        "limits": ["structural_span_only", "no_lexical_anchor", "no_body_text"],
        "inspected_span": None,
    }


def test_missing_dir_fd_nofollow_support_refuses_source_open(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packet, root = _current_packet_for_paths(tmp_path, ("unsupported.py",))
    (root / "unsupported.py").write_text("content\n", encoding="utf-8")

    monkeypatch.setattr(
        advisory_freshness_module,
        "_platform_supports_dir_fd_nofollow",
        lambda: False,
    )

    def forbidden_open(*args: Any, **kwargs: Any) -> int:
        raise AssertionError("unsupported platforms must not open a source file")

    monkeypatch.setattr(os, "open", forbidden_open)
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
    )

    location = packet["items"][0]["locations"][0]
    assert location["freshness"]["state"] == "unavailable"
    assert location["freshness"]["reason"] == "platform_unsupported"
    assert packet["freshness"]["bytes_read"] == 0


def test_root_refusal_is_cached_for_all_paths_in_one_invocation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    packet, root = _current_packet_for_paths(tmp_path, ("missing-a.py", "missing-b.py"))
    root.rename(tmp_path / "moved-root")

    real_open = os.open
    opened_roots = 0

    def tracking_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal opened_roots
        opened_roots += 1
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracking_open})
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
    )

    assert opened_roots == 1
    assert {
        location["freshness"]["reason"] for location in packet["items"][0]["locations"]
    } == {"missing_root"}


def test_ambiguous_line_separators_refuse_but_lf_verdicts_are_preserved(
    tmp_path: Path,
) -> None:
    packet, root = _current_packet_for_paths(tmp_path, ("line-semantics.txt",), end_line=2)
    location = packet["items"][0]["locations"][0]
    cases = (
        ("\f", 2, "unavailable", "line_semantics"),
        ("\u2028", 2, "unavailable", "line_semantics"),
        ("\r", 2, "unavailable", "line_semantics"),
        (
            "\n",
            2,
            "no_change_observed_with_limits",
            "structural_span_only_no_lexical_anchor",
        ),
        ("\n", 3, "changed_observed", "span_beyond_eof"),
    )

    for separator, end_line, expected_state, expected_reason in cases:
        (root / "line-semantics.txt").write_bytes(f"one{separator}two".encode("utf-8"))
        location["end_line"] = end_line
        evaluate_packet_freshness(
            packet,
            FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: root}),
        )
        observation = location["freshness"]
        assert observation["state"] == expected_state
        assert observation["reason"] == expected_reason
        if expected_reason == "line_semantics":
            reserved = reserve_freshness_observation(location)
            assert len(serialize_compact_json(observation)) <= len(
                serialize_compact_json(reserved)
            )
