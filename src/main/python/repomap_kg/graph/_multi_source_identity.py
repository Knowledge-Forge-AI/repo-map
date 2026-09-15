"""Private canonical framing primitives for multi-source identities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_TOKEN_BYTES = 124


class MultiSourceIdentityError(ValueError):
    """A multi-source identity or canonical input is invalid."""


def bounded_ascii(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise MultiSourceIdentityError(f"{label} is invalid")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise MultiSourceIdentityError(f"{label} is invalid") from None
    if len(encoded) > maximum:
        raise MultiSourceIdentityError(f"{label} exceeds its byte bound")
    return value


def token(value: object, label: str, maximum: int = MAX_TOKEN_BYTES) -> str:
    text = bounded_ascii(value, label, maximum)
    if TOKEN_PATTERN.fullmatch(text) is None:
        raise MultiSourceIdentityError(f"{label} is invalid")
    return text


def prefixed_token(value: object, prefix: str, label: str) -> str:
    text = bounded_ascii(value, label, len(prefix) + MAX_TOKEN_BYTES)
    if not text.startswith(prefix):
        raise MultiSourceIdentityError(f"{label} has an unsupported version")
    token(text[len(prefix) :], label)
    return text


def prefixed_digest(value: object, prefix: str, label: str) -> str:
    text = bounded_ascii(value, label, len(prefix) + 64)
    if not text.startswith(prefix):
        raise MultiSourceIdentityError(f"{label} has an unsupported version")
    if HEX_PATTERN.fullmatch(text[len(prefix) :]) is None:
        raise MultiSourceIdentityError(f"{label} is invalid")
    return text


def digest(domain: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
