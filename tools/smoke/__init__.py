"""Containerized smoke-test helpers for RepoMap."""

from __future__ import annotations

import re
from typing import Any

__all__ = ["is_exact_image_reference"]

_EXACT_IMAGE_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def is_exact_image_reference(reference: Any) -> bool:
    """Return whether *reference* is an exact lowercase local image ID."""
    return bool(isinstance(reference, str) and _EXACT_IMAGE_PATTERN.fullmatch(reference))
