"""TEST-HYGIENE3A-FIX2 bounded packet-file and append regressions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from repomap_test_support import resource_report_packet_file
from repomap_test_support.resource_receipts import (
    report_source_release,
    verify_appended_report_packet,
)
from repomap_test_support.resource_report_packet import (
    MAX_PACKET_BYTES,
    ReportPacketError,
)
from repomap_test_support.resource_retention import RetentionError


_LINE = b"=" * 80
_PHASE = "TEST-HYGIENE3A-FIX2"
_TARGET_ID = "OPERATIONAL-REPORT-" + "a" * 64


def _envelope(
    record_id: str,
    *,
    record_type: str = "operational-report",
    record_version: str = "1",
    payload: bytes = b"public-safe payload\n",
) -> bytes:
    common = (
        f"RECORD-TYPE: {record_type}\n"
        f"RECORD-FORMAT-VERSION: {record_version}\n"
        f"RECORD-ID: {record_id}\n"
        "PROJECT: repo-map_dev\n"
        f"PHASE: {_PHASE}\n"
    ).encode()
    return b"".join(
        (
            _LINE,
            b"\nBEGIN AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            common,
            b"PAYLOAD-SHA256: "
            + hashlib.sha256(payload).hexdigest().encode()
            + b"\n",
            b"PAYLOAD-SIZE-BYTES: " + str(len(payload)).encode() + b"\n",
            _LINE,
            b"\n",
            payload,
            _LINE,
            b"\nEND AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            common,
            b"RECORD-COMPLETE: true\n",
            _LINE,
            b"\n",
        )
    )


def _target(*, payload: bytes = b"public-safe payload\n") -> bytes:
    return _envelope(_TARGET_ID, payload=payload)


def test_r13_oversized_packet_is_refused_before_path_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    packet_path = tmp_path / "packet.txt"
    with packet_path.open("wb") as stream:
        stream.truncate(MAX_PACKET_BYTES + 1)

    def forbidden_read_bytes(_path: Path) -> bytes:
        pytest.fail("Path.read_bytes allocated the oversized packet")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    with pytest.raises(RetentionError, match="verification failed"):
        verify_appended_report_packet(
            tmp_path / "append.json",
            packet_path=packet_path,
            phase=_PHASE,
            run_id="run1",
            expected_report_id=_TARGET_ID,
            append_verified_at_seconds=100,
        )


def test_r14_symlink_packet_file_is_refused(tmp_path: Path):
    target = tmp_path / "target.txt"
    target.write_bytes(_target())
    packet_path = tmp_path / "packet.txt"
    packet_path.symlink_to(target)

    with pytest.raises(RetentionError, match="verification failed"):
        verify_appended_report_packet(
            tmp_path / "append.json",
            packet_path=packet_path,
            phase=_PHASE,
            run_id="run1",
            expected_report_id=_TARGET_ID,
            append_verified_at_seconds=100,
        )


def test_r14_packet_replacement_during_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(_target())
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(_target(payload=b"replacement payload\n"))
    original_read = os.read
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, count)
        if not replaced:
            os.replace(replacement, packet_path)
            replaced = True
        return chunk

    monkeypatch.setattr(resource_report_packet_file.os, "read", replacing_read)
    with pytest.raises(ReportPacketError, match="changed during read"):
        resource_report_packet_file.read_packet_file(packet_path)


def test_packet_growth_during_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(_target())
    original_read = os.read
    grew = False

    def growing_read(descriptor: int, count: int) -> bytes:
        nonlocal grew
        chunk = original_read(descriptor, count)
        if not grew:
            with packet_path.open("ab") as stream:
                stream.write(b"growth")
            grew = True
        return chunk

    monkeypatch.setattr(resource_report_packet_file.os, "read", growing_read)
    with pytest.raises(ReportPacketError, match="changed during read"):
        resource_report_packet_file.read_packet_file(packet_path)


def test_packet_errors_do_not_expose_path_or_payload(tmp_path: Path):
    private_token = "private-token-do-not-expose"
    missing_path = tmp_path / private_token
    with pytest.raises(ReportPacketError) as missing:
        resource_report_packet_file.read_packet_file(missing_path)
    assert private_token not in str(missing.value)

    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(_target(payload=private_token.encode()))
    packet_path.write_bytes(packet_path.read_bytes().replace(b"a", b"b", 1))
    with pytest.raises(RetentionError) as malformed:
        verify_appended_report_packet(
            tmp_path / "append.json",
            packet_path=packet_path,
            phase=_PHASE,
            run_id="run1",
            expected_report_id=_TARGET_ID,
            append_verified_at_seconds=100,
        )
    assert private_token not in str(malformed.value)


def test_r15_r1_omnibus_packet_creates_append_without_release_authority(
    tmp_path: Path,
):
    packet = b"".join(
        (
            _envelope(
                "GIT-DIFF-REPORT-" + "b" * 64,
                record_type="git-diff-report",
            ),
            _envelope(
                "GIT-SHOW-REPORT-" + "c" * 40,
                record_type="git-show-report",
                record_version="2",
            ),
            _target(),
        )
    )
    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(packet)

    append = verify_appended_report_packet(
        tmp_path / "append.json",
        packet_path=packet_path,
        phase=_PHASE,
        run_id="run1",
        expected_report_id=_TARGET_ID,
        append_verified_at_seconds=100,
    )

    assert append.report_id == _TARGET_ID
    assert append.packet_sha256 == hashlib.sha256(packet).hexdigest()
    assert report_source_release(append, None, now_seconds=100_000).reason == (
        "close_receipt_missing"
    )
