"""PostgreSQL JSONB read semantics over SQLite Local stored raw payload text.

SQLite Local stores ``raw_observations.payload_json`` as compact JSON text;
PostgreSQL stores the same payload as ``jsonb``. The named summary and
observation reads need the PostgreSQL meaning of a handful of operators, so
this module reproduces exactly those, and nothing more:

* ``->`` / ``->>`` (:func:`text_at`): a missing key, JSON ``null`` or a
  non-object parent is SQL NULL (``None``); strings are raw; booleans are
  ``true``/``false``; numbers use PostgreSQL ``numeric`` text; containers use
  the ``jsonb`` text rendering.
* ``COALESCE(x::boolean, false)`` (:func:`flag`), including PostgreSQL's
  accepted boolean spellings; a value PostgreSQL would reject raises.
* ``?`` (:func:`has_key`), ``LIKE`` with ``\\`` escape (:func:`like`), C-locale
  ``UPPER`` (:func:`ascii_upper`) and ``jsonb::text`` (:func:`jsonb_text`).

SQL three-valued logic: every predicate helper here answers the WHERE-clause
question, so a NULL operand is false for ``=``, ``<>``, ``IN``, ``LIKE`` and
``NOT LIKE`` alike. That is exact because the maintained PostgreSQL builders
only negate atomic predicates, never an ``AND``/``OR`` that could hold a NULL.

No SQL is built here and no SQLite JSON function is used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from decimal import Decimal
from functools import lru_cache
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError

_TRUE = ("true", "yes")
_FALSE = ("false", "no")


def load(text: str) -> Any:
    """Decode stored payload text keeping the written spelling of every number."""
    return json.loads(text, parse_float=Decimal)


def _number(value: int | Decimal) -> str:
    if isinstance(value, int):
        return str(value)
    if value.is_zero():
        value = value.copy_abs()  # numeric has no negative zero
    return format(value, "f")


def _string(value: str) -> str:
    out = ['"']
    for char in value:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\b":
            out.append("\\b")
        elif char == "\f":
            out.append("\\f")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _key_order(key: str) -> tuple[int, bytes]:
    encoded = key.encode("utf-8")
    return len(encoded), encoded


def jsonb_text(value: Any) -> str:
    """The ``jsonb::text`` rendering PostgreSQL gives the same JSON value."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, Decimal)):
        return _number(value)
    if isinstance(value, float):
        return _number(Decimal(repr(value)))
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: _key_order(item[0]))
        return "{" + ", ".join(f"{_string(k)}: {jsonb_text(v)}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(jsonb_text(item) for item in value) + "]"
    raise StorageSchemaError("stored raw observation payload is not JSON")


def jsonb_value(value: Any) -> Any:
    """The value a PostgreSQL JSON readback decodes for this ``jsonb`` value."""
    return json.loads(jsonb_text(value))


def text_at(payload: Any, *keys: str) -> str | None:
    """``payload -> k1 -> ... ->> kn``."""
    current = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if current is None or isinstance(current, str):
        return current
    return jsonb_text(current)


def meta(payload: Any, key: str) -> str | None:
    """``payload_json->'metadata'->>key``."""
    return text_at(payload, "metadata", key)


def flag(value: str | None) -> bool:
    """``COALESCE(value::boolean, false)`` with PostgreSQL ``boolin`` spelling."""
    if value is None:
        return False
    text = value.strip(" \t\n\r\v\f").lower()
    if text:
        if text in ("1", "on"):
            return True
        if text in ("0", "of", "off"):
            return False
        if any(word.startswith(text) for word in _TRUE):
            return True
        if any(word.startswith(text) for word in _FALSE):
            return False
    raise StorageSchemaError("stored raw observation flag is not a boolean")


def has_key(value: Any, key: str) -> bool:
    """``value ? key``: an object key, a string array element or equal string."""
    if isinstance(value, Mapping):
        return key in value
    if isinstance(value, list):
        return any(isinstance(item, str) and item == key for item in value)
    return isinstance(value, str) and value == key


@lru_cache(maxsize=256)
def _like_pattern(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    escaped = False
    for char in pattern:
        if escaped:
            parts.append(re.escape(char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "%":
            parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    if escaped:
        raise StorageSchemaError("LIKE pattern must not end with the escape character")
    return re.compile("".join(parts), re.DOTALL)


def like(value: str | None, pattern: str) -> bool:
    """Case-sensitive ``value LIKE pattern``; NULL is false."""
    return value is not None and _like_pattern(pattern).fullmatch(value) is not None


def not_like(value: str | None, pattern: str) -> bool:
    """``value NOT LIKE pattern``; NULL is false."""
    return value is not None and _like_pattern(pattern).fullmatch(value) is None


def ne(value: str | None, literal: str) -> bool:
    """``value <> literal``; NULL is false."""
    return value is not None and value != literal


def is_in(value: str | None, literals: Collection[str]) -> bool:
    """``value IN (...)``; NULL is false."""
    return value is not None and value in literals


def ascii_upper(value: str) -> str:
    """C-locale ``UPPER``: only ASCII letters change."""
    return value.translate(_UPPER)


def ascii_lower(value: str) -> str:
    """C-locale case folding used by ``ILIKE``."""
    return value.translate(_LOWER)


_UPPER = {code: code - 32 for code in range(ord("a"), ord("z") + 1)}
_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def basename(path: str) -> str:
    """``regexp_replace(path, '^.*/', '')``."""
    return path.rsplit("/", 1)[-1]


__all__ = (
    "ascii_lower",
    "ascii_upper",
    "basename",
    "flag",
    "has_key",
    "is_in",
    "jsonb_text",
    "jsonb_value",
    "like",
    "load",
    "meta",
    "ne",
    "not_like",
    "text_at",
)
