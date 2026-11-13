"""Own preparation iterators while preserving the actual operation failure."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import TypeVar

_Row = TypeVar("_Row")


def check_preparation(check: Callable[[], None] | None) -> None:
    if check is not None:
        check()


def close_preparation_iterators(
    iterators: Iterable[object], *, preserve_primary: bool = False,
) -> None:
    first: BaseException | None = None
    for iterator in iterators:
        try:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
        except BaseException as error:
            if first is None:
                first = error
    if first is not None and not preserve_primary:
        raise first


@contextmanager
def own_preparation_iterator(iterator: Iterator[_Row]) -> Iterator[Iterator[_Row]]:
    failed = False
    try:
        yield iterator
    except BaseException:
        failed = True
        raise
    finally:
        close_preparation_iterators((iterator,), preserve_primary=failed)


def checked_preparation_rows(
    rows: Iterable[_Row], check: Callable[[], None],
) -> Iterator[_Row]:
    check()
    with own_preparation_iterator(iter(rows)) as iterator:
        while True:
            check()
            try:
                row = next(iterator)
            except StopIteration:
                return
            check()
            yield row
