"""Deterministic identifier and path alias token splitting for ranked FTS (identifier-path-split-v1)."""

from __future__ import annotations

import re

ALIAS_SPLIT_RULE_VERSION = "identifier-path-split-v1"
MIN_ALIAS_TOKEN_LEN = 2
MAX_ALIAS_TOKEN_LEN = 64

_RAW_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_DELIMITER_SPLIT_RE = re.compile(r"[/_.:-]+")
_CAMEL_BOUNDARY_1_RE = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_BOUNDARY_2_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CLEAN_ALNUM_RE = re.compile(r"^[a-z0-9]{2,64}$")


def _split_camel_case(segment: str) -> list[str]:
    if not segment:
        return []
    step1 = _CAMEL_BOUNDARY_2_RE.sub(r"\1 \2", segment)
    step2 = _CAMEL_BOUNDARY_1_RE.sub(r"\1 \2", step1)
    base = [part.lower() for part in step2.split(" ") if part]
    expanded: list[str] = []
    for part in base:
        expanded.append(part)
        for sub in re.split(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", part):
            if sub and sub != part:
                expanded.append(sub)
    return expanded


def extract_alias_tokens(
    *,
    source_relative_path: str,
    chunk_text: str,
) -> tuple[str, ...]:
    """Extract deduplicated lowercase alphanumeric alias tokens under identifier-path-split-v1."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(token: str) -> None:
        lower = token.lower()
        if (
            MIN_ALIAS_TOKEN_LEN <= len(lower) <= MAX_ALIAS_TOKEN_LEN
            and _CLEAN_ALNUM_RE.fullmatch(lower) is not None
            and lower not in seen
        ):
            seen.add(lower)
            ordered.append(lower)

    for text_input in (source_relative_path, chunk_text):
        for match in _RAW_CANDIDATE_RE.finditer(text_input):
            raw = match.group(0)
            parts = [p for p in _DELIMITER_SPLIT_RE.split(raw) if p]
            for part in parts:
                _add(part)
                for sub in _split_camel_case(part):
                    _add(sub)
            if len(parts) > 1:
                joined = "".join(parts)
                _add(joined)

    return tuple(ordered)


def build_alias_tokens_text(
    *,
    source_relative_path: str,
    chunk_text: str,
) -> str:
    """Format extracted alias tokens as single-space-delimited lowercase text."""
    return " ".join(
        extract_alias_tokens(
            source_relative_path=source_relative_path,
            chunk_text=chunk_text,
        )
    )


def split_identifier_and_path_tokens(text: str) -> tuple[str, ...]:
    """Extract deduplicated lowercase alphanumeric alias tokens from a single string."""
    return extract_alias_tokens(source_relative_path="", chunk_text=text)


__all__ = [
    "ALIAS_SPLIT_RULE_VERSION",
    "MAX_ALIAS_TOKEN_LEN",
    "MIN_ALIAS_TOKEN_LEN",
    "build_alias_tokens_text",
    "extract_alias_tokens",
    "split_identifier_and_path_tokens",
]
