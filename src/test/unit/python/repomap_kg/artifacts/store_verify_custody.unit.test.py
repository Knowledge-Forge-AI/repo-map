"""Verification acquisition failures release the exact descriptor without GC."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

import pytest

from common_lore_index.artifacts import _store_filesystem as filesystem
from common_lore_index.artifacts import _store_stream as streams
from common_lore_index.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore


class _VerificationCase:
    """Retain actual owners and their original identity until assertions finish."""

    def __init__(self, root: Path, failure: str, error_type: type[BaseException]) -> None:
        self.store = FileSystemArtifactStore(root / "store")
        self.reference = self.store.put(b"public verification payload")
        self.path = self.store.root / self.reference.locator.value
        self.failure = failure
        self.primary = error_type("synthetic verification acquisition refusal")
        self.acquired: list[tuple[int, os.stat_result]] = []
        self.raw_owners: list[BinaryIO] = []
        self.real_open, self.real_stat = os.open, os.fstat
        self.real_fdopen, self.real_close = os.fdopen, os.close

    @property
    def expected(self) -> type[BaseException]:
        if self.failure == "identity" or isinstance(self.primary, OSError):
            return ArtifactIntegrityError
        return type(self.primary)

    def _open(self, candidate, flags, *args, **kwargs):
        descriptor = self.real_open(candidate, flags, *args, **kwargs)
        if Path(candidate) == self.path:
            self.acquired.append((descriptor, self.real_stat(descriptor)))
        return descriptor

    def _stat(self, descriptor):
        if self.failure in {"fstat", "cleanup"} and self.acquired and descriptor == self.acquired[0][0]:
            raise self.primary
        return self.real_stat(descriptor)

    def _fdopen(self, descriptor, *args, **kwargs):
        if self.failure == "fdopen" and self.acquired and descriptor == self.acquired[0][0]:
            raise self.primary
        raw = self.real_fdopen(descriptor, *args, **kwargs)
        self.raw_owners.append(raw)
        return raw

    def _make_reference(self, *_args):
        if self.failure == "reference":
            raise self.primary
        return self.reference

    def _refuse_wrapper(self, raw, **_kwargs):
        # Keep the raw owner reachable so collection cannot hide a lifetime bug.
        self.raw_owners.append(raw)
        raise self.primary

    def _close(self, descriptor):
        self.real_close(descriptor)
        if self.acquired and descriptor == self.acquired[0][0]:
            raise RuntimeError("synthetic secondary close refusal")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "open", self._open)
        monkeypatch.setattr(os, "fstat", self._stat)
        monkeypatch.setattr(os, "fdopen", self._fdopen)
        if self.failure == "cleanup":
            monkeypatch.setattr(os, "close", self._close)
        if self.failure == "identity":
            monkeypatch.setattr(streams, "_same_file_stat", lambda *_: False)
        if self.failure == "wrapper":
            monkeypatch.setattr(streams, "VerifyingArtifactStream", self._refuse_wrapper)

    def run(self) -> None:
        streams.verify_stream_path(
            self.path, digest=self.reference.content_digest, length=self.reference.size_bytes,
            bound=self.reference.size_bytes, expected_version=self.reference.store_version,
            owner_uid=os.getuid(), private_details_fn=filesystem._private_details,
            reference_factory=self._make_reference,
        )

    def leaked(self) -> bool:
        assert len(self.acquired) == 1
        descriptor, before = self.acquired[0]
        try:
            after = self.real_stat(descriptor)
        except OSError:
            return False
        return (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)

    def cleanup(self) -> None:
        for raw in self.raw_owners:
            raw.close()
        if self.acquired and self.leaked():
            self.real_close(self.acquired[0][0])


@pytest.mark.parametrize(("failure", "error_type"), [
    ("fstat", OSError), ("identity", OSError), ("reference", OSError),
    ("fdopen", OSError), ("wrapper", OSError),
    ("reference", KeyboardInterrupt), ("wrapper", RuntimeError), ("cleanup", OSError),
])
def test_verification_acquisition_keeps_descriptor_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, error_type: type[BaseException],
) -> None:
    case = _VerificationCase(tmp_path, failure, error_type)
    case.install(monkeypatch)
    try:
        with pytest.raises(case.expected) as caught:
            case.run()
        if isinstance(case.primary, OSError) and failure != "identity":
            assert caught.value.__cause__ is case.primary
        elif failure != "identity":
            assert caught.value is case.primary
        leaked = case.leaked()
    finally:
        case.cleanup()
    assert not leaked
