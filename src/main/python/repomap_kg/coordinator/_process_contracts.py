"""Shared process handles and boundary errors for platform supervision."""

from __future__ import annotations

from typing import IO, Protocol


class ProcessBoundaryError(RuntimeError):
    """A worker process could not be placed in or cleaned from its boundary."""


class WorkerProcess(Protocol):
    """The Popen interface consumed after an injected launcher returns."""

    @property
    def pid(self) -> int: ...

    @property
    def stdin(self) -> IO[bytes] | None: ...

    @property
    def stdout(self) -> IO[bytes] | None: ...

    @property
    def stderr(self) -> IO[bytes] | None: ...

    @property
    def returncode(self) -> int | None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...
