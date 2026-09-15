"""Shared redaction predicates for static extractors."""

from __future__ import annotations

from collections.abc import Container

from repomap_kg.extractors.shared.scanner import identifier_parts


def secret_name_redaction_reason(
    name: str,
    secret_parts: Container[str],
    *,
    exact_names: Container[str] = (),
    exact_reason: str = "secret-like-name",
) -> str:
    """Return the redaction reason for a secret-like identifier, or ``""``."""
    if name in exact_names:
        return exact_reason
    if any(part in secret_parts for part in identifier_parts(name)):
        return "secret-like-name"
    return ""


def secret_value_redaction_reason(
    value: str,
    secret_parts: Container[str],
) -> str:
    """Return the redaction reason for a secret-like short value, or ``""``."""
    if not value:
        return ""
    if "FAKE_" in value:
        return "secret-like-value"
    if any(part in secret_parts for part in identifier_parts(value)):
        return "secret-like-value"
    return ""
