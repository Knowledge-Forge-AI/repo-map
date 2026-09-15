"""TEST-HYGIENE3A-FIX2 mixed-format packet and bounded-read regressions."""

from __future__ import annotations

import hashlib
from typing import Any
import pytest

from repomap_test_support import resource_report_packet
from repomap_test_support.resource_report_packet import (
    ReportPacketError,
    verify_packet_record,
)


_LINE = b"=" * 80
_PHASE = "TEST-HYGIENE3A-FIX2"
_TARGET_ID = "OPERATIONAL-REPORT-" + "a" * 64


def _envelope(
    record_id: str,
    *,
    record_type: str = "operational-report",
    record_version: str = "1",
    phase: str = _PHASE,
    payload: bytes = b"public-safe payload\n",
    payload_digest: str | None = None,
    payload_size: str | None = None,
    trailer_record_id: str | None = None,
) -> bytes:
    digest = payload_digest or hashlib.sha256(payload).hexdigest()
    size = payload_size or str(len(payload))
    common = (
        f"RECORD-TYPE: {record_type}\n"
        f"RECORD-FORMAT-VERSION: {record_version}\n"
        f"RECORD-ID: {record_id}\n"
        "PROJECT: repo-map_dev\n"
        f"PHASE: {phase}\n"
    ).encode()
    trailer_common = (
        f"RECORD-TYPE: {record_type}\n"
        f"RECORD-FORMAT-VERSION: {record_version}\n"
        f"RECORD-ID: {trailer_record_id or record_id}\n"
        "PROJECT: repo-map_dev\n"
        f"PHASE: {phase}\n"
    ).encode()
    return b"".join(
        (
            _LINE,
            b"\nBEGIN AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            common,
            b"PAYLOAD-SHA256: " + digest.encode() + b"\n",
            b"PAYLOAD-SIZE-BYTES: " + size.encode() + b"\n",
            _LINE,
            b"\n",
            payload,
            _LINE,
            b"\nEND AGENT-REPORT-RECORD\n",
            b"ENVELOPE-FORMAT: agent-report-record\n",
            b"ENVELOPE-VERSION: 1\n",
            trailer_common,
            b"RECORD-COMPLETE: true\n",
            _LINE,
            b"\n",
        )
    )


def _target(
    *,
    record_type: str = "operational-report",
    record_version: str = "1",
    phase: str = _PHASE,
    payload: bytes = b"public-safe payload\n",
    payload_digest: str | None = None,
    payload_size: str | None = None,
    trailer_record_id: str | None = None,
) -> bytes:
    return _envelope(
        _TARGET_ID,
        record_type=record_type,
        record_version=record_version,
        phase=phase,
        payload=payload,
        payload_digest=payload_digest,
        payload_size=payload_size,
        trailer_record_id=trailer_record_id,
    )


def _verify(packet: bytes):
    return verify_packet_record(
        packet,
        expected_report_id=_TARGET_ID,
        expected_phase=_PHASE,
    )


def test_r1_git_show_v2_before_operational_v1_is_selected():
    packet = _envelope(
        "GIT-SHOW-REPORT-" + "b" * 40,
        record_type="git-show-report",
        record_version="2",
    ) + _target()

    assert _verify(packet).report_id == _TARGET_ID


def test_r2_exact_real_mixed_order_selects_only_operational_target():
    packet = b"".join(
        (
            _envelope(
                "GIT-DIFF-REPORT-" + "c" * 64,
                record_type="git-diff-report",
            ),
            _envelope(
                "GIT-SHOW-REPORT-" + "d" * 40,
                record_type="git-show-report",
                record_version="2",
            ),
            _target(),
        )
    )

    record = _verify(packet)

    assert (record.report_id, record.phase, record.record_type) == (
        _TARGET_ID,
        _PHASE,
        "operational-report",
    )


def test_r3_future_valid_non_target_version_is_skipped():
    packet = _envelope(
        "FUTURE-REPORT-" + "e" * 64,
        record_type="future-report",
        record_version="99",
    ) + _target()

    assert _verify(packet).report_id == _TARGET_ID


def test_r4_non_target_payload_semantics_do_not_create_authority():
    packet = _envelope(
        "FUTURE-REPORT-" + "f" * 64,
        record_type="future-report",
        record_version="99",
        payload=b"\x00not a future-report payload schema\xff",
    ) + _target()

    assert _verify(packet).report_id == _TARGET_ID


def test_r5_corrupt_non_target_digest_refuses_whole_packet():
    packet = _envelope(
        "GIT-SHOW-REPORT-" + "1" * 40,
        record_type="git-show-report",
        record_version="2",
        payload_digest="0" * 64,
    ) + _target()

    with pytest.raises(ReportPacketError, match="digest"):
        _verify(packet)


def test_corrupt_non_target_after_valid_target_refuses_whole_packet():
    corrupt_neighbour = _envelope(
        "GIT-SHOW-REPORT-" + "2" * 40,
        record_type="git-show-report",
        record_version="2",
        payload_digest="0" * 64,
    )

    with pytest.raises(ReportPacketError, match="digest"):
        _verify(_target() + corrupt_neighbour)


@pytest.mark.parametrize("corruption", ["size", "trailer"])
def test_r6_corrupt_non_target_boundary_refuses_whole_packet(corruption: str):
    payload_size = "99999999" if corruption == "size" else None
    trailer_record_id = "GIT-SHOW-REPORT-" + "2" * 40 if corruption != "size" else None
    packet = _envelope(
        "GIT-SHOW-REPORT-" + "3" * 40,
        record_type="git-show-report",
        record_version="2",
        payload_size=payload_size,
        trailer_record_id=trailer_record_id,
    ) + _target()

    with pytest.raises(ReportPacketError):
        _verify(packet)


def test_r7_exact_target_with_unsupported_version_is_refused():
    with pytest.raises(ReportPacketError, match="target format"):
        _verify(_target(record_version="2"))


def test_r8_duplicate_target_across_versions_is_refused_as_ambiguous():
    with pytest.raises(ReportPacketError, match="missing or duplicated"):
        _verify(_target() + _target(record_version="2"))


def test_r9_exact_target_with_wrong_phase_is_refused():
    with pytest.raises(ReportPacketError, match="phase"):
        _verify(_target(phase="FOREIGN"))


def test_r10_exact_target_with_wrong_type_is_refused():
    with pytest.raises(ReportPacketError, match="type"):
        _verify(_target(record_type="git-show-report"))


def test_r11_target_marker_inside_payload_is_not_scanned():
    fake_target = _target(payload=b"untrusted nested payload\n")
    neighbour = _envelope(
        "FUTURE-REPORT-" + "4" * 64,
        record_type="future-report",
        record_version="99",
        payload=b"prefix\n" + fake_target + b"suffix\n",
    )

    assert _verify(neighbour + _target()).report_id == _TARGET_ID


def test_r12_more_than_one_valid_target_is_refused():
    with pytest.raises(ReportPacketError, match="missing or duplicated"):
        _verify(_target() + _target())


@pytest.mark.parametrize("placement", ["before", "after", "both"])
def test_mixed_valid_neighbours_can_surround_target(placement: str):
    neighbour = _envelope(
        "GIT-DIFF-REPORT-" + "5" * 64,
        record_type="git-diff-report",
    )
    parts = {
        "before": (neighbour, _target()),
        "after": (_target(), neighbour),
        "both": (
            neighbour,
            _target(),
            _envelope(
                "GIT-SHOW-REPORT-" + "6" * 40,
                record_type="git-show-report",
                record_version="2",
            ),
        ),
    }

    assert _verify(b"".join(parts[placement])).report_id == _TARGET_ID


@pytest.mark.parametrize("corruption", ["header", "trailer", "digest", "size"])
def test_malformed_exact_target_is_refused(corruption: str):
    packet = _target()
    if corruption == "header":
        packet = packet.replace(
            b"RECORD-TYPE: operational-report\n",
            b"RECORD-TYPE: operational-report\nRECORD-TYPE: duplicate\n",
            1,
        )
    elif corruption == "trailer":
        packet = _target(trailer_record_id="OPERATIONAL-REPORT-" + "7" * 64)
    elif corruption == "digest":
        packet = _target(payload_digest="0" * 64)
    else:
        packet = _target(payload_size="99999999")

    with pytest.raises(ReportPacketError):
        _verify(packet)


@pytest.mark.parametrize("packet", [b"", b"not an envelope"])
def test_missing_or_empty_packet_is_refused(packet: bytes):
    with pytest.raises(ReportPacketError):
        _verify(packet)


def test_non_bytes_packet_is_refused_with_controlled_error():
    invalid_packet: Any = "not bytes"  # Deliberately outside the runtime boundary.
    with pytest.raises(ReportPacketError):
        verify_packet_record(
            invalid_packet,
            expected_report_id=_TARGET_ID,
            expected_phase=_PHASE,
        )


@pytest.mark.parametrize("framing", ["leading", "inter_record", "trailing"])
def test_packet_refuses_bytes_outside_exact_record_framing(framing: str):
    packets = {
        "leading": b"garbage" + _target(),
        "inter_record": _envelope(
            "GIT-DIFF-REPORT-" + "8" * 64,
            record_type="git-diff-report",
        )
        + b"garbage"
        + _target(),
        "trailing": _target() + b"garbage",
    }

    with pytest.raises(ReportPacketError, match="framing"):
        _verify(packets[framing])


def test_invalid_non_target_field_encoding_refuses_whole_packet():
    neighbour = _envelope(
        "FUTURE-REPORT-" + "9" * 64,
        record_type="future-report",
        record_version="99",
    ).replace(b"RECORD-TYPE: future-report", b"RECORD-TYPE: \xffuture-report", 1)

    with pytest.raises(ReportPacketError, match="encoding"):
        _verify(neighbour + _target())


def test_invalid_non_target_record_version_refuses_whole_packet():
    with pytest.raises(ReportPacketError, match="record format version"):
        _verify(
            _envelope(
                "FUTURE-REPORT-" + "0" * 64,
                record_type="future-report",
                record_version="0",
            )
            + _target()
        )


def test_envelope_count_is_bounded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(resource_report_packet, "_MAX_PACKET_ENVELOPES", 1)
    neighbour = _envelope(
        "GIT-DIFF-REPORT-" + "a" * 64,
        record_type="git-diff-report",
    )

    with pytest.raises(ReportPacketError, match="too many"):
        _verify(neighbour + _target())
