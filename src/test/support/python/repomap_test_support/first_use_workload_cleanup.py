"""Bounded cleanup custody primitives for the first-use workload driver."""

from __future__ import annotations

from collections.abc import Callable, Sequence

CLEANUP_FAILED = "cleanup_failed"


class CleanupFailure(Exception):
    """A cleanup failure with only the existing bounded reason exposed."""

    def __init__(self, labels: tuple[str, ...] = (CLEANUP_FAILED,)) -> None:
        safe = tuple(label for label in labels if label == CLEANUP_FAILED)
        self.labels = safe or (CLEANUP_FAILED,)
        super().__init__(CLEANUP_FAILED)


def cleanup_labels(error: BaseException) -> tuple[str, ...]:
    """Return bounded labels; never expose exception text."""
    if isinstance(error, CleanupFailure):
        return error.labels
    return (CLEANUP_FAILED,)


class CleanupRegistry:
    """Attempt each registered callback once, in reverse order."""

    def __init__(self) -> None:
        self._items: list[tuple[str, Callable[[], None]]] = []
        self.errors: list[str] = []
        self._control_error: BaseException | None = None

    def register(self, key: str, action: Callable[[], None]) -> None:
        if any(name == key for name, _action in self._items):
            raise ValueError("first-use-cleanup-duplicate")
        self._items.append((key, action))

    def _record(self, error: BaseException) -> list[str]:
        labels = list(cleanup_labels(error))
        self.errors.extend(labels)
        if not isinstance(error, Exception) and self._control_error is None:
            self._control_error = error
        return labels

    def release(self, key: str) -> list[str]:
        """Attempt one callback once; retain a bounded failure label."""
        for position, (name, action) in enumerate(self._items):
            if name == key:
                del self._items[position]
                try:
                    action()
                except BaseException as error:
                    return self._record(error)
                return []
        raise KeyError(key)

    def pending(self) -> tuple[str, ...]:
        return tuple(name for name, _action in self._items)

    def unwind(self) -> list[str]:
        failures: list[str] = []
        while self._items:
            _name, action = self._items.pop()
            try:
                action()
            except BaseException as error:
                failures.extend(self._record(error))
        return failures

    def drain_errors(self) -> list[str]:
        failures = list(self.errors)
        self.errors.clear()
        return failures

    def take_control_error(self) -> BaseException | None:
        error = self._control_error
        self._control_error = None
        return error


def run_terminal_cleanup(
    action: Callable[[], None], registry: CleanupRegistry, prior_failures: Sequence[str] = (),
) -> None:
    """Run row cleanup, then registry custody, preserving its first exception."""
    primary: BaseException | None = None
    try:
        action()
    except BaseException as error:
        primary = error
    before = len(registry.errors)
    existing = tuple(registry.errors)
    registry.unwind()
    recorded = tuple(registry.errors)
    failures = recorded[before:]
    if primary is not None:
        raise primary
    if prior_failures or existing or failures:
        raise CleanupFailure((*prior_failures, *existing, *failures))
