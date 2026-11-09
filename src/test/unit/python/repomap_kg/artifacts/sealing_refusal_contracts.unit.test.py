"""W7 source-sealing refusal contracts.

These cases exercise descriptor identity and custody at the smallest source
body boundary. They intentionally use temporary, public-safe files and do
not replace the sealing subject with a fake reader or store.
"""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._source_sealing_io import (
    SourceUnsealableError,
    open_source_body,
)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_anchored_regular_path_component_is_refused_before_body_open(
    tmp_path: Path,
) -> None:
    """A regular component cannot become a directory traversal anchor."""

    root = tmp_path / "source"
    root.mkdir()
    (root / "component").write_bytes(b"not a directory")
    meter = SealingMeter(None, governed=False)

    with pytest.raises(SourceUnsealableError, match="not sealable"):
        with open_source_body(
            root,
            "component/body.py",
            expected_size=1,
            expected_digest=_digest(b"x"),
            expected_executable=False,
            io_meter=meter,
        ):
            pass

    # The root and failed component attempts are admitted, but no body FD is
    # returned and no descriptor remains owned by the caller.
    assert meter.snapshot().opens == 2


def test_invalid_relative_path_is_rejected_without_open_attempt(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    meter = SealingMeter(None, governed=False)

    with pytest.raises(SourceUnsealableError, match="not sealable"):
        with open_source_body(
            root,
            "../outside.py",
            expected_size=1,
            expected_digest=_digest(b"x"),
            expected_executable=False,
            io_meter=meter,
        ):
            pass

    assert meter.snapshot().opens == 0


def test_same_inode_truncation_after_open_is_rejected_and_fd_is_closed(
    tmp_path: Path,
) -> None:
    """A path that shrinks after admission must not yield a partial artifact."""

    path = tmp_path / "source.py"
    content = b"stable payload"
    path.write_bytes(content)
    descriptor: int | None = None

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            tmp_path,
            path.name,
            expected_size=len(content),
            expected_digest=_digest(content),
            expected_executable=False,
        ) as body:
            descriptor = body._descriptor
            # A separate writable handle truncates the same inode; the body
            # descriptor itself remains the real read-only descriptor.
            path.write_bytes(b"")
            # The real descriptor now returns EOF before the declared size;
            # _SourceBody must still perform its identity/size final check.
            next(body)

    assert descriptor is not None
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_unconsumed_body_refuses_context_exit_and_closes_descriptor(
    tmp_path: Path,
) -> None:
    content = b"body"
    path = tmp_path / "source.py"
    path.write_bytes(content)
    descriptor: int | None = None

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            tmp_path,
            path.name,
            expected_size=len(content),
            expected_digest=_digest(content),
            expected_executable=False,
        ) as body:
            descriptor = body._descriptor
            # Leaving the body unconsumed is a failed verification, not a
            # successful empty copy.
            pass

    assert descriptor is not None
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_read_error_is_source_change_and_closes_real_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.py"
    content = b"unreadable payload"
    path.write_bytes(content)
    descriptor: int | None = None
    original_read = os.read

    def failing_read(fd: int, length: int) -> bytes:
        if fd == descriptor:
            raise OSError(errno.EIO, "injected read failure")
        return original_read(fd, length)

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            tmp_path,
            path.name,
            expected_size=len(content),
            expected_digest=_digest(content),
            expected_executable=False,
        ) as body:
            descriptor = body._descriptor
            monkeypatch.setattr(os, "read", failing_read)
            next(body)

    assert descriptor is not None
    with pytest.raises(OSError):
        os.fstat(descriptor)
