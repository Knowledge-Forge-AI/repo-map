"""Minimal environment boundary for packaged coordinator startup."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence


SERVICE_ENVIRONMENT_ALLOWLIST = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SystemRoot",
    "TZ",
)


def is_service_environment_request(argv: Sequence[str]) -> bool:
    """Recognize only the closed packaged foreground CLI shape."""

    return (
        len(argv) >= 2
        and tuple(argv[0:2]) == ("ops", "coordinator-serve")
        and "--service-package-environment" in argv[2:]
    )


def apply_service_environment(environ: MutableMapping[str, str]) -> None:
    """Discard ambient authority before packaged application imports."""

    retained = {
        name: environ[name]
        for name in SERVICE_ENVIRONMENT_ALLOWLIST
        if name in environ
    }
    environ.clear()
    environ.update(retained)


__all__ = [
    "SERVICE_ENVIRONMENT_ALLOWLIST",
    "apply_service_environment",
    "is_service_environment_request",
]
