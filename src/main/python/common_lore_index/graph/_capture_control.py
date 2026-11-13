"""Graph-local cooperative control; carriers belong only to the capture boundary."""
from __future__ import annotations
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

T = TypeVar("T")
CancelCheck = Callable[[], None]


class _CaptureAbort(BaseException):
    def __init__(self, original: Exception) -> None:
        super().__init__()
        self.original = original


def validate_cancel_check(callback: CancelCheck | None) -> None:
    if callback is not None and not callable(callback):
        raise ValueError("capture cancellation check must be callable")


def validate_capture_cancel(callback: CancelCheck | None, meter: object | None) -> None:
    validate_cancel_check(callback)
    if callback is not None and meter is not None:
        raise ValueError("capture cancellation cannot use a sealing meter")


def _noop() -> None:
    pass


def check_function(callback: CancelCheck | None) -> CancelCheck:
    return _noop if callback is None else callback


def _public_chain(error: BaseException) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for name in ("__cause__", "__context__"):
            link = getattr(current, name)
            while isinstance(link, _CaptureAbort):
                link = link.original
            if link is not getattr(current, name):
                setattr(current, name, link)
            if link is not None:
                pending.append(link)


def controlled_capture(callback: CancelCheck | None,
                       operation: Callable[[CancelCheck | None], T]) -> T:
    """Called inside the public entrypoint's owned workspace, before its cleanup."""
    validate_cancel_check(callback)
    if callback is None:
        return operation(None)

    def guarded() -> None:
        try:
            callback()
        except Exception as error:
            raise _CaptureAbort(error) from None

    failure: Exception
    try:
        return operation(guarded)
    except _CaptureAbort as abort:
        failure = abort.original
    except BaseException as error:
        _public_chain(error)
        raise
    # Raising outside except avoids changing the original's context to a carrier.
    _public_chain(failure)
    raise failure


class CaptureControl:
    """Helpers call the supplied callback as-is; they never create carriers."""
    def __init__(self, callback: CancelCheck | None = None) -> None:
        validate_cancel_check(callback)
        self.callback = callback
        self.check = check_function(callback)

    @property
    def keywords(self) -> dict[str, Any]:
        return {} if self.callback is None else {"cancel_check": self.callback}

    def _values(self, iterator: Iterator[T]) -> Iterator[T]:
        while True:
            self.check()
            try:
                item = next(iterator)
            except StopIteration:
                return
            self.check()
            yield item

    @contextmanager
    def iterating(self, values: Iterable[T]) -> Iterator[Iterator[T]]:
        iterator = iter(values)
        failed = False
        try:
            self.check()
            yield self._values(iterator)
        except BaseException:
            failed = True
            raise
        finally:
            try:
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
            except Exception:
                if not failed:
                    raise

    def collect(self, values: Iterable[T]) -> tuple[T, ...]:
        if self.callback is None:
            return tuple(values)
        with self.iterating(values) as iterator:
            return tuple(iterator)

    def extend_into(self, target: list[T], values: Iterable[T]) -> None:
        if self.callback is None:
            target.extend(values)
            return
        with self.iterating(values) as iterator:
            target.extend(iterator)
