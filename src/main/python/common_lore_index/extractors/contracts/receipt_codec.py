"""Strict canonical bytes, external digest and decoding for run receipts.

Decoding accepts only the exact canonical encoding: sorted keys, no
insignificant whitespace, ASCII escapes and no trailing newline. Every
refusal raises :class:`ContractError` with a categorical code and never
echoes source text or payload bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from common_lore_index.extractors.contracts.bounded_io import (
    read_regular_file,
    write_new_regular_file,
)
from common_lore_index.extractors.contracts.receipt_schema import Receipt
from common_lore_index.extractors.contracts.vocabulary import ContractError, require_sha256

MAX_RECEIPT_BYTES = 65_536
MAX_JSON_DEPTH = 6
MAX_INTEGER_DIGITS = 20


def encode_receipt(receipt: Receipt) -> bytes:
    """Return the canonical receipt bytes. The digest is computed externally."""

    if type(receipt) is not Receipt:
        raise ContractError("invalid_receipt")
    data = json.dumps(
        receipt.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    if len(data) > MAX_RECEIPT_BYTES:
        raise ContractError("oversized")
    return data


def receipt_digest(data: bytes) -> str:
    """Return the external SHA-256 of canonical receipt bytes."""

    if type(data) is not bytes:
        raise ContractError("invalid_bytes")
    return hashlib.sha256(data).hexdigest()


def decode_receipt(data: bytes, *, expected_sha256: str | None = None) -> Receipt:
    """Decode exact canonical receipt bytes, optionally binding a digest."""

    if type(data) is not bytes:
        raise ContractError("invalid_bytes")
    if len(data) > MAX_RECEIPT_BYTES:
        raise ContractError("oversized")
    if expected_sha256 is not None:
        require_sha256(expected_sha256, code="invalid_digest")
        if receipt_digest(data) != expected_sha256:
            raise ContractError("digest_mismatch")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ContractError("invalid_encoding") from None
    if _max_depth(text) > MAX_JSON_DEPTH:
        raise ContractError("too_deep")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
            parse_int=_bounded_int,
        )
    except (json.JSONDecodeError, RecursionError):
        raise ContractError("invalid_json") from None
    receipt = Receipt.from_mapping(payload)
    if encode_receipt(receipt) != data:
        raise ContractError("non_canonical")
    return receipt


def receipt_file_name(digest: str) -> str:
    """Return the fixed single-component storage name for a receipt digest."""

    return f"receipt-{require_sha256(digest, code='invalid_digest')}.json"


def store_receipt(dir_fd: int, receipt: Receipt) -> str:
    """Exclusively store canonical receipt bytes and return their digest.

    Storing is audit retention, not admission: a stored receipt authorizes
    nothing at runtime and an existing file with the same name is refused.
    """

    data = encode_receipt(receipt)
    digest = receipt_digest(data)
    write_new_regular_file(dir_fd, receipt_file_name(digest), data, max_bytes=MAX_RECEIPT_BYTES)
    return digest


def load_receipt(dir_fd: int, digest: str) -> Receipt:
    """Read and strictly decode the receipt whose external digest is given."""

    data = read_regular_file(dir_fd, receipt_file_name(digest), max_bytes=MAX_RECEIPT_BYTES)
    return decode_receipt(data, expected_sha256=digest)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise ContractError("non_finite_number")


def _reject_float(_value: str) -> Any:
    raise ContractError("float_forbidden")


def _bounded_int(value: str) -> int:
    if len(value.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise ContractError("integer_out_of_range")
    return int(value)


def _max_depth(text: str) -> int:
    """Measure container nesting outside strings before invoking the parser."""

    depth = deepest = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif character in "]}":
            depth -= 1
    return deepest
