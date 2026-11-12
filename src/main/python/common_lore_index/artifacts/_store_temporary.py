"""Artifact temporary unlink preserves an in-flight producer failure."""
from __future__ import annotations

from pathlib import Path
import os
from typing import BinaryIO

from common_lore_index.artifacts._store_common import ArtifactErrorCode, ArtifactIntegrityError


def open_temporary_stream(descriptor: int) -> BinaryIO:
    """Hand over a temporary descriptor once and reclaim failed permission setup."""
    stream: BinaryIO | None = None
    try:
        stream = os.fdopen(descriptor, "wb", closefd=True)
        os.fchmod(stream.fileno(), 0o600)
        return stream
    except BaseException:
        try:
            if stream is None:
                os.close(descriptor)
            else:
                stream.close()
        except BaseException:
            pass
        raise


def remove_temporary(path: Path, *, preserve_primary: bool = False) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        if not preserve_primary:
            raise ArtifactIntegrityError(
                "artifact temporary cleanup failed", code=ArtifactErrorCode.WRITE_FAILED,
            ) from error
