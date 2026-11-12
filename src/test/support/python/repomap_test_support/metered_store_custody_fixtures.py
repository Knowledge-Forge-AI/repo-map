"""Real descriptor identities for metered-store fault witnesses; no GC proof."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, BinaryIO

import pytest

import common_lore_index.artifacts._store_metered as metered


class DescriptorWitness:
    """Retain explicit ownership and reclaim deliberately refused test closes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.real_close = os.close
        self.real_mkstemp = metered.tempfile.mkstemp
        self.real_open = metered.metered_open
        self.acquired: list[tuple[int, int, int]] = []
        self.close_attempts: list[int] = []
        self.close_faults: dict[int, tuple[BaseException, bool]] = {}
        monkeypatch.setattr(metered.tempfile, "mkstemp", self.mkstemp)
        monkeypatch.setattr(metered, "metered_open", self.open)
        monkeypatch.setattr(os, "close", self.close)

    def remember(self, descriptor: int) -> int:
        details = os.fstat(descriptor)
        self.acquired.append((descriptor, details.st_dev, details.st_ino))
        return descriptor

    def mkstemp(self, *args: Any, **kwargs: Any) -> tuple[int, str]:
        descriptor, name = self.real_mkstemp(*args, **kwargs)
        return self.remember(descriptor), name

    def open(self, *args: Any, **kwargs: Any) -> int:
        return self.remember(self.real_open(*args, **kwargs))

    def close(self, descriptor: int) -> None:
        if descriptor in self.live():
            self.close_attempts.append(descriptor)
        fault = self.close_faults.pop(descriptor, None)
        if fault is not None and not fault[1]:
            raise fault[0]
        self.real_close(descriptor)
        if fault is not None:
            raise fault[0]

    def live(self) -> list[int]:
        result = []
        for descriptor, device, inode in self.acquired:
            try:
                details = os.fstat(descriptor)
            except OSError:
                continue
            if (details.st_dev, details.st_ino) == (device, inode):
                result.append(descriptor)
        return result

    def release_witnesses(self) -> None:
        for descriptor in self.live():
            self.real_close(descriptor)


def store_state(root: Path) -> tuple[tuple[str, bytes], ...]:
    """Read only the public-safe fixture objects, with exact byte preservation."""
    return tuple(sorted((p.name, p.read_bytes()) for p in (root / "objects").iterdir()))


class CloseFaultStream:
    """Report one injected close error after releasing the real owned stream."""

    def __init__(self, stream: BinaryIO, failure: BaseException, *, release: bool = True) -> None:
        self.stream, self.failure = stream, failure
        self.release = release
        self.close_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def close(self) -> None:
        self.close_calls += 1
        if self.release:
            self.stream.close()
        raise self.failure

    def __enter__(self) -> CloseFaultStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
