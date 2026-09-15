"""Shared type contracts for private test-image materialization support."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict


class MaterializationClaim(TypedDict):
    """Validated private manifest fields used by the materialization lifecycle."""

    schema: str
    project: str
    phase: str
    run_id: str
    role: str
    name: str
    base_image_id: str
    container_id: str | None
    network_mode: str
    network_id: str | None
    ledger_path: str


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise TypeError(f"materialization claim field {field!r} is not text")
    return value


def _optional_text(payload: Mapping[str, object], field: str) -> str | None:
    value = payload[field]
    if value is not None and not isinstance(value, str):
        raise TypeError(f"materialization claim field {field!r} is not text")
    return value


def materialization_claim(payload: Mapping[str, object]) -> MaterializationClaim:
    """Describe the already-validated claim payload with a concrete contract."""
    return {
        "schema": _required_text(payload, "schema"),
        "project": _required_text(payload, "project"),
        "phase": _required_text(payload, "phase"),
        "run_id": _required_text(payload, "run_id"),
        "role": _required_text(payload, "role"),
        "name": _required_text(payload, "name"),
        "base_image_id": _required_text(payload, "base_image_id"),
        "container_id": _optional_text(payload, "container_id"),
        "network_mode": _required_text(payload, "network_mode"),
        "network_id": _optional_text(payload, "network_id"),
        "ledger_path": _required_text(payload, "ledger_path"),
    }


__all__ = ["MaterializationClaim", "materialization_claim"]
