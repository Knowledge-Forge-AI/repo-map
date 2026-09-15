"""Small shared scanner helpers for static extractors."""

from __future__ import annotations

import re


def identifier_parts(value: str) -> tuple[str, ...]:
    """Split a source identifier or short value into lower-case word parts."""
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return tuple(
        part for part in re.split(r"[^0-9A-Za-z]+", expanded.lower()) if part
    )
