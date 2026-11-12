"""Evaluator-only rejection predicates for captured public-text inputs.

The maintained v1 redactor is unchanged. These small stdlib rules enforce the
credential shapes on the new input boundary; rejected text is never redacted
and then admitted. No raw input is retained or included in diagnostics.

Structured metadata ids (keys, kinds, names, paths, evidence keys) do not use
the body assignment heuristic; they keep length, Cc/Cs, the maintained
sanitizer with private markers, credential URIs and PEM private-key headers.
Excerpt bodies additionally refuse every assignment shape conservatively.
Inputs are bounded by their callers (1024 metadata characters, 4096 excerpt
bytes), which bounds regular-expression backtracking.
"""

from __future__ import annotations

from collections.abc import Sequence
import re
import unicodedata

from retrieval_semantic_primitives import is_sanitized_public_string

MAX_METADATA_CHARACTERS = 1024
# Any scheme with user:password@ userinfo; token-only userinfo is a disclosed coverage limit.
_CREDENTIAL_URI = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,31}://[^\s/?#@:]+:[^\s/?#@]+@")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credentials?|authorization)"
    r"[a-z0-9_.-]*[\"']?\s*[:=]\s*[^\s,;]+"
)
_PEM_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")

EXCERPT_MARKER = "marker"
EXCERPT_CREDENTIAL_SHAPE = "credential_shape"
EXCERPT_SANITIZER = "sanitizer"


def credential_uri(value: str) -> bool:
    return _CREDENTIAL_URI.search(value) is not None


def credential_assignment(value: str) -> bool:
    return _CREDENTIAL_ASSIGNMENT.search(value) is not None


def pem_private_key(value: str) -> bool:
    return _PEM_PRIVATE_KEY.search(value) is not None


def credential_shaped_text(value: str) -> bool:
    """Detect the body credential shapes without substituting or exposing values."""
    return credential_uri(value) or credential_assignment(value) or pem_private_key(value)


def _has_marker(value: str, private_markers: Sequence[str]) -> bool:
    return any(marker and marker in value for marker in private_markers)


def is_safe_public_metadata(value: object, *, private_markers: Sequence[str] = ()) -> bool:
    """Structured-id bounds before any source body read; no body assignment heuristic."""
    return (
        type(value) is str and bool(value.strip()) and len(value) <= MAX_METADATA_CHARACTERS
        and not any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in value)
        and not credential_uri(value) and not pem_private_key(value)
        and is_sanitized_public_string(value, private_markers=tuple(private_markers))
    )


def excerpt_privacy_class(value: str, *, private_markers: Sequence[str]) -> str | None:
    """Closed classification: private marker, then credential shape, then the maintained sanitizer."""
    markers = tuple(private_markers)
    if _has_marker(value, markers):
        return EXCERPT_MARKER
    if credential_shaped_text(value):
        return EXCERPT_CREDENTIAL_SHAPE
    if not is_sanitized_public_string(value, private_markers=markers):
        return EXCERPT_SANITIZER
    return None


def is_safe_public_excerpt(value: str, *, private_markers: Sequence[str]) -> bool:
    """True only when no marker, credential shape or maintained-sanitizer change applies."""
    return excerpt_privacy_class(value, private_markers=private_markers) is None
