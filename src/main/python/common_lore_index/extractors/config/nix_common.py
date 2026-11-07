"""Shared identity helpers for static Nix observation extraction."""

from __future__ import annotations

import re


EXTRACTOR_NAME = "repo-nix"
IDENTIFIER_PATTERN = r"[0-9A-Za-z_.+-]+"
_SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")


def slug(value: str) -> str:
    slug_value = _SLUG_PATTERN.sub("-", value).strip("-").lower()
    return slug_value or "path"
