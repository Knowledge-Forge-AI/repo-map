"""Synthetic canary registry and recursive output/envelope/report leak scanner (S2)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


CANARY_REGISTRY: dict[str, str] = {
    "mailbox_incident_body": "CANARY_PRIVATE_EMAIL_BODY_SECRET_99281",
    "mailbox_private_thread_body": "CANARY_PRIVATE_THREAD_PAYLOAD_44102",
    "companion_unselected_cache": "CANARY_UNSELECTED_CACHE_SCRATCH_88310",
}


@dataclass(frozen=True)
class CanaryFinding:
    """One detected synthetic canary token in an inspected output payload."""

    canary_id: str
    canary_token: str
    location_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "canary_id": self.canary_id,
            "canary_token": self.canary_token,
            "location_path": self.location_path,
        }


def _scan_value(
    value: Any,
    location: str,
    registry: Mapping[str, str],
    findings: list[CanaryFinding],
) -> None:
    if isinstance(value, str):
        for canary_id, token in registry.items():
            if token in value:
                findings.append(
                    CanaryFinding(
                        canary_id=canary_id,
                        canary_token=token,
                        location_path=location,
                    )
                )
        return
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        _scan_value(decoded, location, registry, findings)
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            _scan_value(str(k), f"{location}.<key:{k}>", registry, findings)
            _scan_value(v, f"{location}.{k}", registry, findings)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for idx, item in enumerate(value):
            _scan_value(item, f"{location}[{idx}]", registry, findings)
        return
    if hasattr(value, "to_dict") and callable(value.to_dict):
        _scan_value(value.to_dict(), location, registry, findings)
        return
    try:
        serialized = json.dumps(value, default=str)
    except Exception:
        serialized = str(value)
    _scan_value(serialized, location, registry, findings)


def scan_for_canaries(
    payload: Any,
    *,
    registry: Mapping[str, str] | None = None,
) -> tuple[CanaryFinding, ...]:
    """Scan any string, mapping, sequence, or serializable object for canary tokens."""
    active_registry = registry if registry is not None else CANARY_REGISTRY
    findings: list[CanaryFinding] = []
    _scan_value(payload, "$", active_registry, findings)
    return tuple(findings)


def assert_canary_free(
    payload: Any,
    *,
    registry: Mapping[str, str] | None = None,
) -> None:
    """Raise ValueError if any registered synthetic canary token is present in payload."""
    findings = scan_for_canaries(payload, registry=registry)
    if findings:
        summary = ", ".join(f"{f.canary_id} at {f.location_path}" for f in findings)
        raise ValueError(f"synthetic privacy canary leak detected: {summary}")


__all__ = [
    "CANARY_REGISTRY",
    "CanaryFinding",
    "assert_canary_free",
    "scan_for_canaries",
]
