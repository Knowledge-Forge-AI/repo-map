"""Fail-closed marker for repository-owned canonical unit resource boundaries."""

from __future__ import annotations

import os


ENV_UNIT_PURITY_GUARD = "REPOMAP_UNIT_PURITY_GUARD"


class UnitPurityState:
    """Install and restore the canonical marker around one pytest item."""

    def __init__(self) -> None:
        self._previous: str | None = None
        self._installed = False

    def activate(self, *, unit_item: bool) -> None:
        self.restore()
        self._previous = os.environ.get(ENV_UNIT_PURITY_GUARD)
        self._installed = True
        if unit_item:
            os.environ[ENV_UNIT_PURITY_GUARD] = "1"
        else:
            os.environ.pop(ENV_UNIT_PURITY_GUARD, None)

    def restore(self) -> None:
        if not self._installed:
            return
        if self._previous is None:
            os.environ.pop(ENV_UNIT_PURITY_GUARD, None)
        else:
            os.environ[ENV_UNIT_PURITY_GUARD] = self._previous
        self._previous = None
        self._installed = False


def unit_purity_guard_active(environ=None) -> bool:
    env = os.environ if environ is None else environ
    value = env.get(ENV_UNIT_PURITY_GUARD)
    if value is None:
        return False
    if value != "1":
        raise RuntimeError("canonical unit purity marker is invalid")
    return True


def require_live_resource_allowed(resource: str, environ=None) -> None:
    if unit_purity_guard_active(environ):
        raise RuntimeError(
            f"canonical unit purity forbids live {resource}; use an injected test double"
        )
