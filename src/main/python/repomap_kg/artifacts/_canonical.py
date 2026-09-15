"""Closed canonical JSON helpers for immutable artifact contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import NoReturn


class CanonicalEncodingError(ValueError):
    """The value is outside the artifact canonical-JSON domain."""


def canonical_json(value: object) -> bytes:
    """Encode the integer-only JSON domain as sorted ASCII plus one LF."""

    _validate_value(value)
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise CanonicalEncodingError("value is not canonical JSON") from error


def decode_canonical_json(data: bytes) -> dict[str, object]:
    """Decode and prove an exact canonical object encoding."""

    if not isinstance(data, bytes) or not data.endswith(b"\n"):
        raise CanonicalEncodingError("canonical JSON must end with one LF")
    try:
        value = json.loads(
            data[:-1].decode("ascii", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise CanonicalEncodingError("canonical JSON is invalid") from error
    if not isinstance(value, dict):
        raise CanonicalEncodingError("canonical JSON root must be an object")
    _validate_value(value)
    if canonical_json(value) != data:
        raise CanonicalEncodingError("JSON bytes are not canonical")
    return value


def prefixed_digest(prefix: str, domain: bytes, data: bytes) -> str:
    """Digest an exact byte domain with an explicit non-JSON separator."""

    return prefix + hashlib.sha256(domain + b"\x00" + data).hexdigest()


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _validate_value(value: object) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalEncodingError("floats are outside the canonical domain")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalEncodingError("canonical object keys must be strings")
        for item in value.values():
            _validate_value(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            _validate_value(item)
        return
    raise CanonicalEncodingError("value is outside the canonical domain")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CanonicalEncodingError("duplicate object key")
        value[key] = item
    return value


def _reject_float(_value: str) -> NoReturn:
    raise CanonicalEncodingError("floats are outside the canonical domain")
