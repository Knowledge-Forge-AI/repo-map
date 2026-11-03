"""Bounded stdout framing for the optional semantic experiment journal."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
from typing import TextIO


ARTIFACT_LINE_PREFIX = "REPO_MAP_W5_ARTIFACT_V1 "
ARTIFACT_SCHEMA = "repomap-w5-attempt-artifact-v1"
ATTEMPT_IDS = ("w5-semantic-g1", "w5-semantic-g2")
MEMBER_NAMES = (
    "declaration.json",
    "source-manifest.json",
    "sources.zip",
    "observations.jsonl",
    "report.json",
    "terminal.json",
)
MEMBER_LIMITS = {
    "declaration.json": 1 * 1024 * 1024,
    "source-manifest.json": 1 * 1024 * 1024,
    "sources.zip": 8 * 1024 * 1024,
    "observations.jsonl": 16 * 1024 * 1024,
    "report.json": 1 * 1024 * 1024,
    "terminal.json": 64 * 1024,
}
MAX_MEMBER_FRAMES = 12
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES = 96 * 1024 * 1024
_MEMBER_FRAME_FIELDS = frozenset(
    {"attempt_id", "data", "kind", "length", "member", "sha256"}
)
_FOOTER_FIELDS = frozenset({"kind", "manifest", "manifest_sha256"})
_MANIFEST_ENTRY_FIELDS = frozenset({"length", "name", "sha256"})
_JSON_MEMBERS = frozenset(
    {"declaration.json", "source-manifest.json", "report.json", "terminal.json"}
)


class ArtifactRefusal(ValueError):
    """Raised when a public artifact frame violates the bounded protocol."""


def _refuse(reason: str) -> ArtifactRefusal:
    return ArtifactRefusal(reason)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise _refuse("artifact_noncanonical_json") from error


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _refuse("artifact_duplicate_field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise _refuse("artifact_nonfinite_json")


def _strict_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except ArtifactRefusal:
        raise
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _refuse("artifact_invalid_json") from error
    if type(value) is not dict or _canonical_json(value) != raw:
        raise _refuse("artifact_noncanonical_json")
    return value


def _validate_digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != len("sha256:") + 64
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise _refuse("artifact_digest_invalid")
    return value


def _validate_attempt_id(value: object) -> str:
    if type(value) is not str or value not in ATTEMPT_IDS:
        raise _refuse("artifact_attempt_invalid")
    return value


def _validate_member(value: object) -> str:
    if type(value) is not str or value not in MEMBER_NAMES:
        raise _refuse("artifact_member_invalid")
    return value


def _validate_name(value: object) -> str:
    if type(value) is not str or value.count("/") != 1:
        raise _refuse("artifact_name_invalid")
    attempt_id, member = value.split("/", 1)
    _validate_attempt_id(attempt_id)
    _validate_member(member)
    if value != f"{attempt_id}/{member}":
        raise _refuse("artifact_name_invalid")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise _refuse("artifact_name_unsafe")
    return value


def _validate_json_member(member: str, data: bytes) -> None:
    if member in _JSON_MEMBERS:
        if not data.endswith(b"\n") or data.count(b"\n") != 1:
            raise _refuse("artifact_json_member_invalid")
        _strict_object(data[:-1])
        return
    if member != "observations.jsonl" or not data:
        return
    if not data.endswith(b"\n"):
        raise _refuse("artifact_observations_unterminated")
    for line in data[:-1].split(b"\n"):
        if not line:
            raise _refuse("artifact_observations_blank")
        _strict_object(line)


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        initial = os.lstat(path)
    except OSError as error:
        raise _refuse("artifact_member_unreadable") from error
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise _refuse("artifact_member_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise _refuse("artifact_member_unreadable") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise _refuse("artifact_member_size")
        expected = opened.st_size
        chunks: list[bytes] = []
        remaining = expected
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise _refuse("artifact_member_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (opened.st_ino, expected, opened.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise _refuse("artifact_member_changed")
        return b"".join(chunks)
    except ArtifactRefusal:
        raise
    except OSError as error:
        raise _refuse("artifact_member_unreadable") from error
    finally:
        os.close(descriptor)


def _validate_attempt_directory(raw_path: object) -> tuple[str, Path]:
    if not isinstance(raw_path, (str, os.PathLike)):
        raise _refuse("artifact_attempt_path_invalid")
    try:
        path = Path(raw_path)
    except (TypeError, ValueError) as error:
        raise _refuse("artifact_attempt_path_invalid") from error
    attempt_id = _validate_attempt_id(path.name)
    if not path.is_absolute() or any(ancestor.is_symlink() for ancestor in path.parents):
        raise _refuse("artifact_attempt_unsafe")
    try:
        info = os.lstat(path)
    except OSError as error:
        raise _refuse("artifact_attempt_unreadable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise _refuse("artifact_attempt_unsafe")
    return attempt_id, path


def _load_attempt(raw_path: object) -> tuple[str, dict[str, bytes]]:
    attempt_id, path = _validate_attempt_directory(raw_path)
    values: dict[str, bytes] = {}
    for member in MEMBER_NAMES:
        data = _read_bounded(path / member, MEMBER_LIMITS[member])
        _validate_json_member(member, data)
        values[member] = data
    return attempt_id, values


def _member_frame(attempt_id: str, member: str, data: bytes) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "data": base64.b64encode(data).decode("ascii"),
        "kind": "member",
        "length": len(data),
        "member": member,
        "sha256": _sha256(data),
    }


def _manifest_entry(attempt_id: str, member: str, data: bytes) -> dict[str, object]:
    return {
        "length": len(data),
        "name": f"{attempt_id}/{member}",
        "sha256": _sha256(data),
    }


def emit_attempt_artifacts(
    journal_dirs: object, *, stream: TextIO | None = None
) -> None:
    """Emit bounded, opaque journal members as prefixed stdout frames."""
    if isinstance(journal_dirs, (str, bytes)) or not isinstance(journal_dirs, Sequence):
        raise _refuse("artifact_attempts_invalid")
    loaded: dict[str, dict[str, bytes]] = {}
    for raw_path in journal_dirs:
        attempt_id, members = _load_attempt(raw_path)
        if attempt_id in loaded or len(loaded) >= len(ATTEMPT_IDS):
            raise _refuse("artifact_attempt_duplicate")
        loaded[attempt_id] = members
    total_decoded = sum(
        len(data) for members in loaded.values() for data in members.values()
    )
    if total_decoded > MAX_DECODED_BYTES:
        raise _refuse("artifact_decoded_size")
    frames: list[dict[str, object]] = []
    manifest: list[dict[str, object]] = []
    for attempt_id in sorted(loaded):
        for member in MEMBER_NAMES:
            data = loaded[attempt_id][member]
            frames.append(_member_frame(attempt_id, member, data))
            manifest.append(_manifest_entry(attempt_id, member, data))
    if len(frames) > MAX_MEMBER_FRAMES:
        raise _refuse("artifact_frame_count")
    manifest.sort(key=lambda entry: str(entry["name"]).encode("ascii"))
    footer = {
        "kind": "footer",
        "manifest": manifest,
        "manifest_sha256": _sha256(_canonical_json(manifest)),
    }
    prefix = ARTIFACT_LINE_PREFIX
    lines = [prefix + _canonical_json(frame).decode("ascii") + "\n" for frame in frames]
    lines.append(prefix + _canonical_json(footer).decode("ascii") + "\n")
    if 1 + sum(len(line.encode("ascii")) for line in lines) > MAX_INPUT_BYTES:
        raise _refuse("artifact_input_size")
    output = sys.stdout if stream is None else stream
    output.write("\n")
    for line in lines:
        output.write(line)
    flush = getattr(output, "flush", None)
    if callable(flush):
        flush()


def _decode_member_frame(frame: dict[str, object]) -> tuple[str, str, bytes]:
    if frozenset(frame) != _MEMBER_FRAME_FIELDS or frame.get("kind") != "member":
        raise _refuse("artifact_member_frame_fields")
    attempt_id = _validate_attempt_id(frame.get("attempt_id"))
    member = _validate_member(frame.get("member"))
    length = frame.get("length")
    if type(length) is not int or length < 0 or length > MEMBER_LIMITS[member]:
        raise _refuse("artifact_member_frame_size")
    digest = _validate_digest(frame.get("sha256"))
    encoded = frame.get("data")
    if type(encoded) is not str:
        raise _refuse("artifact_member_frame_data")
    max_encoded = 4 * ((MEMBER_LIMITS[member] + 2) // 3)
    if len(encoded) > max_encoded:
        raise _refuse("artifact_member_frame_size")
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise _refuse("artifact_member_frame_base64") from error
    if base64.b64encode(data).decode("ascii") != encoded:
        raise _refuse("artifact_member_frame_base64")
    if len(data) != length or _sha256(data) != digest:
        raise _refuse("artifact_member_frame_digest")
    _validate_json_member(member, data)
    return attempt_id, member, data


def _decode_footer(frame: dict[str, object], expected: list[dict[str, object]]) -> None:
    if frozenset(frame) != _FOOTER_FIELDS or frame.get("kind") != "footer":
        raise _refuse("artifact_footer_fields")
    raw_manifest = frame.get("manifest")
    if type(raw_manifest) is not list or len(raw_manifest) > MAX_MEMBER_FRAMES:
        raise _refuse("artifact_footer_manifest")
    manifest: list[dict[str, object]] = []
    for raw_entry in raw_manifest:
        if type(raw_entry) is not dict or frozenset(raw_entry) != _MANIFEST_ENTRY_FIELDS:
            raise _refuse("artifact_footer_manifest")
        name = _validate_name(raw_entry.get("name"))
        length = raw_entry.get("length")
        if type(length) is not int or length < 0 or length > MAX_DECODED_BYTES:
            raise _refuse("artifact_footer_manifest")
        manifest.append(
            {"length": length, "name": name, "sha256": _validate_digest(raw_entry.get("sha256"))}
        )
    if manifest != sorted(manifest, key=lambda entry: str(entry["name"]).encode("ascii")):
        raise _refuse("artifact_footer_order")
    if _sha256(_canonical_json(manifest)) != _validate_digest(frame.get("manifest_sha256")):
        raise _refuse("artifact_footer_digest")
    if manifest != expected:
        raise _refuse("artifact_footer_mismatch")


def decode_attempt_artifacts(raw_log: bytes) -> dict[str, bytes]:
    """Decode a complete two-attempt artifact capsule from captured stdout."""
    if type(raw_log) is not bytes:
        raise _refuse("artifact_input_invalid")
    if len(raw_log) > MAX_INPUT_BYTES:
        raise _refuse("artifact_input_size")
    prefix = ARTIFACT_LINE_PREFIX.encode("ascii")
    decoded: dict[tuple[str, str], bytes] = {}
    footer: dict[str, object] | None = None
    parts = raw_log.split(b"\n")
    for index, line in enumerate(parts):
        if not line.startswith(prefix):
            continue
        if index == len(parts) - 1 and not raw_log.endswith(b"\n"):
            raise _refuse("artifact_frame_unterminated")
        frame = _strict_object(line[len(prefix) :])
        kind = frame.get("kind")
        if kind == "member":
            if footer is not None or len(decoded) >= MAX_MEMBER_FRAMES:
                raise _refuse("artifact_frame_order")
            attempt_id, member, data = _decode_member_frame(frame)
            key = (attempt_id, member)
            if key in decoded:
                raise _refuse("artifact_duplicate_member")
            decoded[key] = data
        elif kind == "footer":
            if footer is not None:
                raise _refuse("artifact_duplicate_footer")
            footer = frame
        else:
            raise _refuse("artifact_frame_kind")
    if footer is None:
        raise _refuse("artifact_footer_missing")
    if sum(len(data) for data in decoded.values()) > MAX_DECODED_BYTES:
        raise _refuse("artifact_decoded_size")
    expected = [
        _manifest_entry(attempt_id, member, decoded[(attempt_id, member)])
        for attempt_id, member in sorted(decoded)
    ]
    _decode_footer(footer, expected)
    required = {(attempt_id, member) for attempt_id in ATTEMPT_IDS for member in MEMBER_NAMES}
    if set(decoded) != required:
        raise _refuse("artifact_incomplete")
    return {
        f"{attempt_id}/{member}": decoded[(attempt_id, member)]
        for attempt_id, member in sorted(decoded)
    }


__all__ = [
    "ARTIFACT_LINE_PREFIX",
    "ARTIFACT_SCHEMA",
    "ATTEMPT_IDS",
    "ArtifactRefusal",
    "MEMBER_LIMITS",
    "MEMBER_NAMES",
    "MAX_DECODED_BYTES",
    "MAX_INPUT_BYTES",
    "decode_attempt_artifacts",
    "emit_attempt_artifacts",
]
