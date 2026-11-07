"""Bounded stdout frames and path-safe retention for evaluator result-v2."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import TextIO, cast

from retrieval_semantic_baseline_result_objects import BaselineResultV2
from retrieval_semantic_baseline_results import RESULT_SCHEMA, ResultRefusal
from retrieval_semantic_experiment_artifacts import (
    ATTEMPT_IDS,
    MEMBER_LIMITS,
    MEMBER_NAMES,
    MAX_INPUT_BYTES as MAX_RESULT_LOG_BYTES,
)
from retrieval_semantic_experiment_contracts import canonical_json_bytes

RESULT_LINE_PREFIX = "REPO_MAP_W5_RESULT_V2 "
RESULT_FRAME_KIND = "result"
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_RESULT_INPUT_BYTES = 8 * 1024 * 1024
_FRAME_FIELDS = frozenset({
    "attempt_id", "data", "kind", "length", "schema", "sha256",
})


def _refuse(code: str) -> ResultRefusal:
    return ResultRefusal(code)


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    if (
        type(value) is not str or len(value) != 71 or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise _refuse("result_frame_digest")
    return value


def _strict_object(raw: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _refuse("result_duplicate_field")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise _refuse("result_nonfinite_json")

    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except ResultRefusal:
        raise
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _refuse("result_invalid_json") from error
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise _refuse("result_noncanonical_json")
    return value


def read_raw_journal_members(attempt_directory: Path) -> dict[str, bytes]:
    """Read exactly the maintained six members with no symlink traversal."""
    if (
        not isinstance(attempt_directory, Path) or not attempt_directory.is_absolute()
        or attempt_directory.name not in ATTEMPT_IDS or attempt_directory.is_symlink()
        or any(parent.is_symlink() for parent in attempt_directory.parents)
    ):
        raise _refuse("result_attempt_path")
    values: dict[str, bytes] = {}
    for name in MEMBER_NAMES:
        path = attempt_directory / name
        try:
            initial = os.lstat(path)
            if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
                raise _refuse("result_member_unsafe")
            if initial.st_size > MEMBER_LIMITS[name]:
                raise _refuse("result_member_size")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(descriptor)
                if opened.st_size > MEMBER_LIMITS[name]:
                    raise _refuse("result_member_size")
                chunks: list[bytes] = []
                remaining = opened.st_size
                while remaining:
                    chunk = os.read(descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        raise _refuse("result_member_changed")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                after = os.fstat(descriptor)
                if (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns,
                ):
                    raise _refuse("result_member_changed")
                values[name] = b"".join(chunks)
            finally:
                os.close(descriptor)
        except ResultRefusal:
            raise
        except OSError as error:
            raise _refuse("result_member_unreadable") from error
    return values


def _frame(result: BaselineResultV2) -> bytes:
    data = canonical_json_bytes(result.to_mapping())
    if len(data) > MAX_RESULT_BYTES:
        raise _refuse("result_size")
    frame = {
        "attempt_id": result.attempt_id, "data": base64.b64encode(data).decode("ascii"),
        "kind": RESULT_FRAME_KIND,
        "length": len(data),
        "schema": RESULT_SCHEMA,
        "sha256": _sha(data),
    }
    return RESULT_LINE_PREFIX.encode("ascii") + canonical_json_bytes(frame) + b"\n"


def emit_result_frames(results: object, *, stream: TextIO) -> None:
    if isinstance(results, (str, bytes)) or not isinstance(results, Sequence):
        raise _refuse("result_sequence")
    frames: list[bytes] = []
    seen: set[str] = set()
    for result in cast(Sequence[object], results):
        if not isinstance(result, BaselineResultV2) or result.attempt_id in seen:
            raise _refuse("result_duplicate_attempt")
        seen.add(result.attempt_id)
        frames.append(_frame(result))
    if sum(map(len, frames)) > MAX_RESULT_INPUT_BYTES:
        raise _refuse("result_input_size")
    stream.write("\n")
    for frame in sorted(frames):
        stream.write(frame.decode("ascii"))
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def decode_result_frames(raw_log: bytes) -> dict[str, BaselineResultV2]:
    if type(raw_log) is not bytes or len(raw_log) > MAX_RESULT_LOG_BYTES:
        raise _refuse("result_input_size")
    prefix = RESULT_LINE_PREFIX.encode("ascii")
    decoded: dict[str, BaselineResultV2] = {}
    v2_bytes = 0
    parts = raw_log.split(b"\n")
    for index, line in enumerate(parts):
        if not line.startswith(prefix):
            continue
        v2_bytes += len(line) + (1 if index < len(parts) - 1 else 0)
        if v2_bytes > MAX_RESULT_INPUT_BYTES:
            raise _refuse("result_input_size")
        if index == len(parts) - 1 and not raw_log.endswith(b"\n"):
            raise _refuse("result_frame_unterminated")
        frame = _strict_object(line[len(prefix) :])
        if frozenset(frame) != _FRAME_FIELDS or frame.get("kind") != RESULT_FRAME_KIND:
            raise _refuse("result_frame_fields")
        attempt_id = frame.get("attempt_id")
        if type(attempt_id) is not str or attempt_id not in ATTEMPT_IDS or attempt_id in decoded:
            raise _refuse("result_frame_attempt")
        if frame.get("schema") != RESULT_SCHEMA:
            raise _refuse("result_frame_schema")
        length, encoded = frame.get("length"), frame.get("data")
        if (
            type(length) is not int or length < 0 or length > MAX_RESULT_BYTES
            or type(encoded) is not str
        ):
            raise _refuse("result_frame_size")
        try:
            data = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeError, binascii.Error) as error:
            raise _refuse("result_frame_base64") from error
        if len(data) != length or _sha(data) != _digest(frame.get("sha256")):
            raise _refuse("result_frame_digest")
        result = BaselineResultV2.from_mapping(_strict_object(data))
        if result.attempt_id != attempt_id:
            raise _refuse("result_frame_attempt")
        decoded[attempt_id] = result
    if not decoded:
        raise _refuse("result_frame_missing")
    return decoded


__all__ = [
    "MAX_RESULT_BYTES", "MAX_RESULT_INPUT_BYTES", "MAX_RESULT_LOG_BYTES",
    "RESULT_LINE_PREFIX",
    "decode_result_frames", "emit_result_frames", "read_raw_journal_members",
]
