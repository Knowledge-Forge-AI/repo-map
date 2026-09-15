"""Bounded evidence helpers for exact runtime-materialization cleanup."""

from __future__ import annotations

import re
from typing import Any, Mapping

from repomap_test_support.resource_test_image_base import TestImageError


class MaterializationCleanupError(TestImageError):
    """Exact-container cleanup failed with bounded public-safe evidence."""

    def __init__(self, failure_kind: str, evidence: Mapping[str, Any]) -> None:
        self.failure_kind = failure_kind
        self.cleanup_evidence = dict(evidence)
        super().__init__(f"managed_runtime_build_cleanup_failed: {failure_kind}")


def docker_failure_evidence(error: Exception) -> dict[str, Any]:
    status = getattr(error, "status_code", None)
    status = status if isinstance(status, int) and 400 <= status <= 599 else None
    explanation = str(getattr(error, "explanation", "")).lower()
    if "removal" in explanation and "progress" in explanation:
        category = "removal_in_progress"
    elif "running" in explanation:
        category = "container_running"
    elif status == 404:
        category = "not_found"
    elif status == 409:
        category = "conflict_other"
    elif status is None:
        category = "non_api_exception"
    else:
        category = "api_error_other"
    exception_type = error.__class__.__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception_type):
        exception_type = "DockerError"
    return {
        "exception_type": exception_type,
        "http_status_code": status,
        "daemon_explanation_category": category,
    }


def container_state(attrs: Mapping[str, Any]) -> dict[str, Any]:
    state = attrs.get("State") or {}
    return {
        "Status": str(state.get("Status") or ""),
        "Running": bool(state.get("Running", False)),
        "Paused": bool(state.get("Paused", False)),
        "Restarting": bool(state.get("Restarting", False)),
        "Dead": bool(state.get("Dead", False)),
        "ExitCode": int(state.get("ExitCode") or 0),
    }


def is_terminal_container_state(state: Mapping[str, Any]) -> bool:
    return (
        state["Status"] in {"created", "exited", "dead"}
        and not state["Running"]
        and not state["Paused"]
        and not state["Restarting"]
    )


__all__ = [
    "MaterializationCleanupError",
    "container_state",
    "docker_failure_evidence",
    "is_terminal_container_state",
]
