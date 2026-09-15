"""TEST-HYGIENE3A retention, terminal-stamp, and receipt contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repomap_test_support.resource_receipts import (
    read_append_record,
    read_close_receipt,
    report_source_release,
    verify_appended_report_packet,
    write_close_receipt,
    write_operator_release,
)
from repomap_test_support.resource_report_packet import MAX_PACKET_BYTES
from repomap_test_support.resource_retention import (
    RetentionClass,
    RetentionError,
    TerminalOutcome,
    create_terminal_stamp,
)


def _packet(report_id: str, *, phase: str = "TEST-HYGIENE3A") -> bytes:
    line = b"=" * 80
    payload = b"public-safe operational payload\n"
    common = (
        b"RECORD-TYPE: operational-report\n"
        b"RECORD-FORMAT-VERSION: 1\n"
        + f"RECORD-ID: {report_id}\n".encode()
        + b"PROJECT: repo-map_dev\n"
        + f"PHASE: {phase}\n".encode()
    )
    return b"".join(
        (
            line,
            b"\nBEGIN AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            common,
            b"PAYLOAD-SHA256: " + hashlib.sha256(payload).hexdigest().encode() + b"\n",
            b"PAYLOAD-SIZE-BYTES: " + str(len(payload)).encode() + b"\n",
            line,
            b"\n",
            payload,
            line,
            b"\nEND AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            common,
            b"RECORD-COMPLETE: true\n",
            line,
            b"\n",
        )
    )


def _append(tmp_path: Path, *, verified_at: int = 100):
    report_id = "OPERATIONAL-REPORT-" + "a" * 64
    packet = tmp_path / "packet.txt"
    packet.write_bytes(_packet(report_id))
    return verify_appended_report_packet(
        tmp_path / "append.json",
        packet_path=packet,
        phase="TEST-HYGIENE3A",
        run_id="run1",
        expected_report_id=report_id,
        append_verified_at_seconds=verified_at,
    )


def test_retention_vocabulary_and_ttls_are_closed():
    assert RetentionClass.SUCCESSFUL_EVIDENCE.ttl_seconds == 7 * 86400
    assert RetentionClass.FAILED_EVIDENCE.ttl_seconds == 30 * 86400
    assert RetentionClass.CORRECTION_REQUIRED_EVIDENCE.ttl_seconds == 90 * 86400
    assert RetentionClass.OPERATOR_PINNED.ttl_seconds is None


@pytest.mark.parametrize("value", [True, 1.5, -1, "1", None])
def test_terminal_stamp_requires_exact_timestamp(value):
    with pytest.raises(RetentionError, match="nonnegative integer"):
        create_terminal_stamp(TerminalOutcome.PASSED, value)


def test_report_source_requires_ordered_receipt_and_close_based_grace(tmp_path: Path):
    append = _append(tmp_path)
    assert report_source_release(append, None, now_seconds=100000).released is False
    receipt = write_close_receipt(
        tmp_path / "close.json",
        phase="TEST-HYGIENE3A",
        run_id="run1",
        commit="b" * 40,
        commit_verified_at_seconds=150,
        append=append,
        closed_at_seconds=200,
    )
    assert report_source_release(append, receipt, now_seconds=200 + 86399).released is False
    assert report_source_release(append, receipt, now_seconds=200 + 86400).released is True


def test_receipt_records_are_immutable(tmp_path: Path):
    _append(tmp_path)
    with pytest.raises(RetentionError, match="already exists"):
        _append(tmp_path)


def test_operator_release_is_explicit_and_still_observes_grace(tmp_path: Path):
    append = _append(tmp_path)
    release = write_operator_release(
        tmp_path / "release.json",
        phase="TEST-HYGIENE3A",
        run_id="run1",
        append_record_id=append.append_record_id,
        released_at_seconds=200,
    )
    assert report_source_release(
        append,
        None,
        now_seconds=200 + 86400,
        operator_release=release,
    ).released is True


def test_loaded_receipts_are_strict_and_append_integrity_is_rechecked(tmp_path: Path):
    append = _append(tmp_path)
    receipt_path = tmp_path / "close.json"
    write_close_receipt(
        receipt_path,
        phase="TEST-HYGIENE3A",
        run_id="run1",
        commit="b" * 40,
        commit_verified_at_seconds=150,
        append=append,
        closed_at_seconds=200,
    )
    assert read_close_receipt(receipt_path).closed_at_seconds == 200
    payload = json.loads(append.path.read_text())
    payload["append_record_id"] = "c" * 64
    append.path.write_text(json.dumps(payload))
    with pytest.raises(RetentionError, match="invalid"):
        read_append_record(append.path)


def test_loaded_close_receipt_rechecks_strict_ordering(tmp_path: Path):
    append = _append(tmp_path)
    receipt_path = tmp_path / "close.json"
    write_close_receipt(
        receipt_path,
        phase="TEST-HYGIENE3A",
        run_id="run1",
        commit="b" * 40,
        commit_verified_at_seconds=150,
        append=append,
        closed_at_seconds=200,
    )
    payload = json.loads(receipt_path.read_text())
    payload["closed_at_seconds"] = payload["append_verified_at_seconds"]
    receipt_path.write_text(json.dumps(payload))

    with pytest.raises(RetentionError, match="invalid"):
        read_close_receipt(receipt_path)


@pytest.mark.parametrize("field", ["append_verified_at_seconds", "record_complete"])
def test_append_integrity_covers_release_authority_fields(tmp_path: Path, field):
    append = _append(tmp_path)
    payload = json.loads(append.path.read_text())
    payload[field] = 101 if field == "append_verified_at_seconds" else False
    append.path.write_text(json.dumps(payload))
    with pytest.raises(RetentionError, match="invalid"):
        read_append_record(append.path)


def test_receipt_writer_refuses_symlink_parent(tmp_path: Path):
    report_id = "OPERATIONAL-REPORT-" + "a" * 64
    packet = tmp_path / "packet.txt"
    packet.write_bytes(_packet(report_id))
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(RetentionError, match="creation failed"):
        verify_appended_report_packet(
            linked / "append.json",
            packet_path=packet,
            phase="TEST-HYGIENE3A",
            run_id="run1",
            expected_report_id=report_id,
            append_verified_at_seconds=100,
        )


def test_receipt_writer_refuses_symlink_ancestor(tmp_path: Path):
    report_id = "OPERATIONAL-REPORT-" + "a" * 64
    packet = tmp_path / "packet.txt"
    packet.write_bytes(_packet(report_id))
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(RetentionError, match="creation failed"):
        verify_appended_report_packet(
            linked / "nested" / "append.json",
            packet_path=packet,
            phase="TEST-HYGIENE3A",
            run_id="run1",
            expected_report_id=report_id,
            append_verified_at_seconds=100,
        )
    assert not (real / "nested").exists()


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_phase", "digest"])
def test_packet_verifier_rejects_ambiguous_or_malformed_envelopes(
    tmp_path: Path, mutation: str
):
    report_id = "OPERATIONAL-REPORT-" + "a" * 64
    packet = _packet(report_id)
    if mutation == "duplicate":
        packet += packet
    elif mutation == "wrong_phase":
        packet = _packet(report_id, phase="FOREIGN")
    else:
        packet = packet.replace(b"public-safe", b"public-fake", 1)
    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(packet)
    with pytest.raises(RetentionError, match="verification failed"):
        verify_appended_report_packet(
            tmp_path / "append.json",
            packet_path=packet_path,
            phase="TEST-HYGIENE3A",
            run_id="run1",
            expected_report_id=report_id,
            append_verified_at_seconds=100,
        )


def test_packet_verifier_enforces_strict_size_limit(tmp_path: Path):
    packet_path = tmp_path / "packet.txt"
    packet_path.write_bytes(b"x" * (MAX_PACKET_BYTES + 1))

    with pytest.raises(RetentionError, match="verification failed"):
        verify_appended_report_packet(
            tmp_path / "append.json",
            packet_path=packet_path,
            phase="TEST-HYGIENE3A",
            run_id="run1",
            expected_report_id="OPERATIONAL-REPORT-" + "a" * 64,
            append_verified_at_seconds=100,
        )
