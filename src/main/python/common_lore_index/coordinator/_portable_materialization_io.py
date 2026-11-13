"""Own copy-local source contexts and descriptors without relabelling the body."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from typing import BinaryIO, TypeVar

from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.store import ArtifactIntegrityError, ArtifactStore

_Result = TypeVar("_Result")


def _source_call(operation: Callable[[], _Result]) -> _Result:
    try:
        return operation()
    except OSError as error:
        raise ArtifactIntegrityError("artifact read failed") from error


def _release_all(operations: Iterable[Callable[[], object]], primary: BaseException | None) -> None:
    first: BaseException | None = None
    for operation in operations:
        try:
            operation()
        except BaseException as error:
            if first is None:
                first = error
    if primary is None and first is not None:
        raise first


def _exit_source(source: BinaryIO, primary: BaseException | None) -> object:
    kind = None if primary is None else type(primary)
    traceback = None if primary is None else primary.__traceback__
    return _source_call(lambda: source.__exit__(kind, primary, traceback))


@dataclass(frozen=True)
class CopyHandles:
    reader: BinaryIO
    descriptor: int
    identity: tuple[int, int]

    def read(self, size: int) -> bytes:
        return _source_call(lambda: self.reader.read(size))


@contextmanager
def copy_handles(
    store: ArtifactStore, reference: ArtifactReference, destination: Path, *, bound: int,
) -> Iterator[CopyHandles]:
    source = _source_call(lambda: store.open_stream(reference, max_bytes=bound))
    try:
        reader = _source_call(source.__enter__)
    except BaseException as error:
        _release_all((lambda: _source_call(source.close),), error)
        raise
    descriptor: int | None = None
    primary: BaseException | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(destination, flags, 0o600)
        details = os.fstat(descriptor)
        yield CopyHandles(reader, descriptor, (details.st_dev, details.st_ino))
    except BaseException as error:
        primary = error
        raise
    finally:
        operations: list[Callable[[], object]] = [lambda: _exit_source(source, primary)]
        if descriptor is not None:
            owned = descriptor
            descriptor = None
            operations.append(lambda: os.close(owned))
        _release_all(operations, primary)


@contextmanager
def readback_descriptor(destination: Path) -> Iterator[int]:
    descriptor = os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    primary: BaseException | None = None
    try:
        yield descriptor
    except BaseException as error:
        primary = error
        raise
    finally:
        _release_all((lambda: os.close(descriptor),), primary)
