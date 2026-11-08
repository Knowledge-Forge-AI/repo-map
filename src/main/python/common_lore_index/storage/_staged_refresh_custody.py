"""Exception-safe teardown for resources owned by one staged refresh."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

_Cleanup = tuple[str, Callable[[], Any]]


def note_secondary(primary: BaseException, label: str, secondary: BaseException) -> None:
    try:
        primary.add_note(
            f"staged refresh cleanup failure ({label}): {type(secondary).__name__}"
        )
    except BaseException:
        pass


def settle_owned_cleanup(
    primary: BaseException | None,
    callbacks: Iterable[_Cleanup | None],
) -> BaseException | None:
    """Run every teardown callback without replacing an active primary error."""

    cleanup_primary: BaseException | None = None
    for entry in callbacks:
        if entry is None:
            continue
        label, callback = entry
        try:
            callback()
        except BaseException as error:
            if primary is not None:
                if cleanup_primary is None:
                    cleanup_primary = error
                note_secondary(primary, label, error)
            elif cleanup_primary is None:
                cleanup_primary = error
            else:
                note_secondary(cleanup_primary, label, error)
    if primary is None and cleanup_primary is not None:
        raise cleanup_primary
    return cleanup_primary


def run_owned_step(
    primary: BaseException, label: str, callback: Callable[[], Any]
) -> bool:
    """Attempt one cleanup step while retaining the active primary error."""

    try:
        callback()
    except BaseException as error:
        note_secondary(primary, label, error)
        return False
    return True


def settle_staged_resources(
    primary: BaseException | None,
    signal_handlers: Any,
    prepared: Any,
    connection: Any,
    restore: Callable[[Any], Any],
    close: Callable[[Any], Any],
) -> BaseException | None:
    """Settle signal, prepared-row, and connection resources in order."""

    return settle_owned_cleanup(
        primary,
        (
            ("signal handler restore", lambda: restore(signal_handlers)),
            ("prepared rows close", prepared.close),
            ("connection close", lambda: close(connection))
            if connection is not None else None,
        ),
    )


__all__ = (
    "note_secondary", "run_owned_step", "settle_owned_cleanup", "settle_staged_resources",
)
