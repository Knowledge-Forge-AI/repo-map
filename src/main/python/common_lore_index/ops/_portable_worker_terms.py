"""Small, behavior-preserving terms shared by the portable worker route."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.coordinator.limits import DEFAULT_LIMITS
from common_lore_index.ops._portable_retention import PortableRefreshError


PORTABLE_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024


def effective_leaf_limits(limits: object | None, authority: Any) -> object:
    """Derive the exact leaf limits selected by the existing worker owner."""
    if limits is not None:
        return limits
    leaf_deadline = authority.process_deadline_seconds if authority is not None else None
    if leaf_deadline is not None:
        return replace(DEFAULT_LIMITS, process_deadline_seconds=leaf_deadline)
    return DEFAULT_LIMITS


def _worker_references(terminal):
    extension = terminal.get("portable_snapshot")
    if terminal.get("status") != "succeeded" or not isinstance(extension, dict):
        from common_lore_index.coordinator._protocol_validation import _ERROR_CATEGORIES

        raw = terminal.get("error_category")
        category = raw if isinstance(raw, str) and raw in _ERROR_CATEGORIES else "worker_crash"
        # Preserve deterministic refusals. Other classes retain the previous
        # retry policy until independently qualified; no diagnostic parsing.
        if category not in {"contract_validation", "unsupported_contract", "unsupported_capability"}:
            category = "worker_crash"
        reason = terminal.get("reason")
        if reason in {"process_timeout", "heartbeat_timeout"}:
            category = "worker_timeout"
        elif reason == "protocol":
            category = "protocol"
        raise PortableRefreshError(
            f"portable worker did not complete ({category})", category=category
        )
    try:
        return (
            ArtifactReference.from_mapping(extension["receipt"]),
            ArtifactReference.from_mapping(extension["bundle"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PortableRefreshError("portable worker result is malformed") from error


__all__ = ("PORTABLE_MAX_ARTIFACT_BYTES", "_worker_references", "effective_leaf_limits")
