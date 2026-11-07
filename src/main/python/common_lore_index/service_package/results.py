"""Public-safe coordinator service action results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceActionResult:
    """Public-safe result for one explicit operator action."""

    action: str
    platform: str
    artifact: str
    service_identity: str
    result: str = "success"
    installed: bool | None = None
    active: bool | None = None
    enabled: bool | None = None
    ready: bool | None = None
    changed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "active": self.active,
            "artifact": self.artifact,
            "changed": self.changed,
            "command": "coordinator-service",
            "enabled": self.enabled,
            "installed": self.installed,
            "platform": self.platform,
            "ready": self.ready,
            "result": self.result,
            "service_identity": self.service_identity,
        }


__all__ = ["ServiceActionResult"]
