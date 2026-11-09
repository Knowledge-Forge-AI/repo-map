"""Hash-only publication pin facts.

A pin fact is ``null`` before any publication, otherwise
``{generation, pin_sha256, manifest_sha256}``. ``pin_sha256`` hashes the
canonical accepted-publication map returned by the current selection reader;
``manifest_sha256`` hashes the canonical bytes of the retained manifest that
``manifest_for_pin`` binds to that map. Raw maps never reach the evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_domains import WorkloadError
from first_use_workload_encoding import closed, is_count, is_hex64, require

PIN_KEYS = ("generation", "manifest_sha256", "pin_sha256")
_MAP_BUDGET = 65536


def publication_digest(publication: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical accepted-publication map plus one LF."""
    if not isinstance(publication, Mapping):
        raise WorkloadError("malformed")
    try:
        body = canonical_bytes(dict(publication), _MAP_BUDGET)
    except ValueError:
        raise WorkloadError("malformed") from None
    return hashlib.sha256(body + b"\n").hexdigest()


def pin_fact(publication: Mapping[str, Any], manifest_canonical: bytes) -> dict[str, Any]:
    generation = publication.get("generation")
    if not is_count(generation) or generation == 0:
        raise WorkloadError("invalid_domain")
    return {
        "generation": generation,
        "manifest_sha256": hashlib.sha256(manifest_canonical).hexdigest(),
        "pin_sha256": publication_digest(publication),
    }


def validate_pin(raw: object) -> dict[str, Any] | None:
    if raw is None:
        return None
    pin = closed(raw, PIN_KEYS)
    require(is_count(pin["generation"]) and pin["generation"] >= 1)
    require(is_hex64(pin["pin_sha256"]) and is_hex64(pin["manifest_sha256"]))
    return pin


def advanced_by_one(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> bool:
    """The ordinary relation: cold starts at 1; each publication adds exactly 1."""
    if after is None:
        return False
    expected = 1 if before is None else before["generation"] + 1
    if after["generation"] != expected:
        return False
    # An unchanged tree may reseal an equal manifest; the accepted map must move.
    return before is None or after["pin_sha256"] != before["pin_sha256"]


def preserved(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> bool:
    """A refusal keeps the complete pin digest, not only its displayed generation."""
    return before is not None and after is not None and dict(before) == dict(after)


__all__ = [
    "PIN_KEYS", "advanced_by_one", "pin_fact", "preserved", "publication_digest", "validate_pin",
]
