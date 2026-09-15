"""Bounded generic scanning for appended Agent report packet envelopes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


MAX_PACKET_BYTES = 16 * 1024 * 1024
_MAX_PACKET_ENVELOPES = 4096
_ENVELOPE = b"=" * 80
_START = _ENVELOPE + b"\nBEGIN AGENT-REPORT-RECORD\n"
_HEADER_FIELDS = {
    "ENVELOPE-FORMAT",
    "ENVELOPE-VERSION",
    "RECORD-TYPE",
    "RECORD-FORMAT-VERSION",
    "RECORD-ID",
    "PROJECT",
    "PHASE",
    "PAYLOAD-SHA256",
    "PAYLOAD-SIZE-BYTES",
}
_TRAILER_IDENTITY_FIELDS = (
    "ENVELOPE-FORMAT",
    "ENVELOPE-VERSION",
    "RECORD-TYPE",
    "RECORD-FORMAT-VERSION",
    "RECORD-ID",
    "PROJECT",
    "PHASE",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_POSITIVE_VERSION = re.compile(r"[1-9][0-9]{0,8}\Z")
_PAYLOAD_SIZE = re.compile(r"(?:0|[1-9][0-9]{0,8})\Z")


class ReportPacketError(ValueError):
    """The packet cannot establish one exact complete report record."""


@dataclass(frozen=True)
class AgentReportEnvelope:
    envelope_format: str
    envelope_version: int
    record_type: str
    record_format_version: int
    record_id: str
    project: str
    phase: str
    payload_sha256: str
    payload_size_bytes: int
    payload_start: int
    payload_end: int
    record_end: int
    record_complete: bool


@dataclass(frozen=True)
class VerifiedPacketRecord:
    report_id: str
    phase: str
    record_type: str


def verify_packet_record(
    packet: bytes,
    *,
    expected_report_id: str,
    expected_phase: str,
) -> VerifiedPacketRecord:
    if type(packet) is not bytes or not packet or len(packet) > MAX_PACKET_BYTES:
        raise ReportPacketError("report packet size is invalid")
    _require_text(expected_report_id, "expected report id", 256)
    _require_text(expected_phase, "expected phase", 128)

    matches = [
        envelope
        for envelope in _scan_envelopes(packet)
        if envelope.record_id == expected_report_id
    ]
    if len(matches) != 1:
        raise ReportPacketError("expected report envelope is missing or duplicated")
    match = matches[0]
    if match.record_format_version != 1:
        raise ReportPacketError("target format version is unsupported")
    if match.phase != expected_phase:
        raise ReportPacketError("report phase does not match")
    if match.record_type != "operational-report":
        raise ReportPacketError("report type does not match")
    return VerifiedPacketRecord(match.record_id, match.phase, match.record_type)


def _scan_envelopes(packet: bytes) -> list[AgentReportEnvelope]:
    records: list[AgentReportEnvelope] = []
    offset = 0
    while offset < len(packet):
        if len(records) >= _MAX_PACKET_ENVELOPES:
            raise ReportPacketError("report packet contains too many envelopes")
        if not packet.startswith(_START, offset):
            raise ReportPacketError("report packet framing is invalid")
        record = _parse_envelope(packet, offset)
        records.append(record)
        offset = record.record_end
    if not records or offset != len(packet):
        raise ReportPacketError("report packet framing is invalid")
    return records


def _parse_envelope(packet: bytes, start: int) -> AgentReportEnvelope:
    header, payload_start = _read_lines(packet, start, 12)
    if header[0] != _ENVELOPE or header[1] != b"BEGIN AGENT-REPORT-RECORD":
        raise ReportPacketError("report header is malformed")
    fields = _parse_fields(header[2:11])
    if set(fields) != _HEADER_FIELDS or header[11] != _ENVELOPE:
        raise ReportPacketError("report header fields are malformed")
    _validate_common_fields(fields)

    payload_size = _parse_payload_size(fields["PAYLOAD-SIZE-BYTES"])
    payload_end = payload_start + payload_size
    if payload_end > len(packet):
        raise ReportPacketError("report payload is truncated")
    payload = packet[payload_start:payload_end]
    if hashlib.sha256(payload).hexdigest() != fields["PAYLOAD-SHA256"]:
        raise ReportPacketError("report payload digest mismatch")

    trailer, record_end = _read_lines(packet, payload_end, 11)
    if trailer[0] != _ENVELOPE or trailer[1] != b"END AGENT-REPORT-RECORD":
        raise ReportPacketError("report trailer is malformed")
    trailer_fields = _parse_fields(trailer[2:10])
    expected_trailer = {key: fields[key] for key in _TRAILER_IDENTITY_FIELDS}
    expected_trailer["RECORD-COMPLETE"] = "true"
    if trailer_fields != expected_trailer or trailer[10] != _ENVELOPE:
        raise ReportPacketError("report trailer fields are malformed")

    return AgentReportEnvelope(
        envelope_format=fields["ENVELOPE-FORMAT"],
        envelope_version=1,
        record_type=fields["RECORD-TYPE"],
        record_format_version=int(fields["RECORD-FORMAT-VERSION"]),
        record_id=fields["RECORD-ID"],
        project=fields["PROJECT"],
        phase=fields["PHASE"],
        payload_sha256=fields["PAYLOAD-SHA256"],
        payload_size_bytes=payload_size,
        payload_start=payload_start,
        payload_end=payload_end,
        record_end=record_end,
        record_complete=True,
    )


def _validate_common_fields(fields: dict[str, str]) -> None:
    if fields["ENVELOPE-FORMAT"] != "agent-report-record":
        raise ReportPacketError("report envelope format is unsupported")
    if fields["ENVELOPE-VERSION"] != "1":
        raise ReportPacketError("report envelope version is unsupported")
    if not _POSITIVE_VERSION.fullmatch(fields["RECORD-FORMAT-VERSION"]):
        raise ReportPacketError("report record format version is malformed")
    _require_text(fields["RECORD-TYPE"], "record type", 128)
    _require_text(fields["RECORD-ID"], "record id", 256)
    _require_text(fields["PROJECT"], "project", 128)
    _require_text(fields["PHASE"], "phase", 128)
    if not _SHA256.fullmatch(fields["PAYLOAD-SHA256"]):
        raise ReportPacketError("report payload digest is malformed")


def _parse_payload_size(value: str) -> int:
    if not _PAYLOAD_SIZE.fullmatch(value):
        raise ReportPacketError("report payload size is malformed")
    payload_size = int(value)
    if payload_size > MAX_PACKET_BYTES:
        raise ReportPacketError("report payload size is invalid")
    return payload_size


def _read_lines(data: bytes, offset: int, count: int) -> tuple[list[bytes], int]:
    lines: list[bytes] = []
    for _ in range(count):
        ending = data.find(b"\n", offset)
        if ending < 0:
            raise ReportPacketError("report envelope is truncated")
        lines.append(data[offset:ending])
        offset = ending + 1
    return lines, offset


def _parse_fields(lines: list[bytes]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition(b": ")
        if not separator or not key or not value:
            raise ReportPacketError("report field is malformed")
        try:
            decoded_key = key.decode("ascii")
            decoded_value = value.decode("utf-8")
        except UnicodeError as error:
            raise ReportPacketError("report field encoding is invalid") from error
        if decoded_key in fields or _has_unsafe_characters(decoded_value):
            raise ReportPacketError("report field is malformed")
        fields[decoded_key] = decoded_value
    return fields


def _require_text(value: object, label: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or _has_unsafe_characters(value)
    ):
        raise ReportPacketError(f"{label} is malformed")
    return value


def _has_unsafe_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


__all__ = [
    "MAX_PACKET_BYTES",
    "ReportPacketError",
    "verify_packet_record",
]
