"""Cooperative bundle cancellation and deterministic iterator release."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

_Resource = TypeVar("_Resource")


class BundleEncodingCancelled(ValueError):
    """An actual encoder or sorter event checkpoint observed cancellation."""

    def __init__(self) -> None:
        super().__init__("cancelled")


def close_iterator(iterator: object, *, preserve_primary: bool = False) -> None:
    """Close an iterator; the owning guard explicitly identifies failure unwind."""
    close = getattr(iterator, "close", None)
    if close is None:
        return
    if not preserve_primary:
        close()
    else:
        try:
            close()
        except BaseException:
            pass


@contextmanager
def closing_bundle_resource(resource: _Resource) -> Iterator[_Resource]:
    """Release an encoder resource while retaining the guarded operation's error."""
    try:
        yield resource
    except BaseException:
        close_iterator(resource, preserve_primary=True)
        raise
    else:
        close_iterator(resource)
