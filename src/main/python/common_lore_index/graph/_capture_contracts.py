"""Shared physical-capture failures and pure signature comparison; no capture I/O."""

from __future__ import annotations

import os


class MultiSourceCaptureError(ValueError):
    """Public-safe fail-closed multi-source capture error."""

    def __init__(self, message: str, *, category: str = "source_capture") -> None:
        self.category = category
        super().__init__(message)


class _SourceUnavailable(Exception):
    """A configured source could not be opened or no longer exists."""


class _SourceChanged(Exception):
    """A selected source entry changed while it was being captured."""


class _SourceCapture(Exception):
    """A source entry could not be captured safely."""


class _SourceInvalid(Exception):
    """A source inventory contains an unsupported or unsafe entry."""


def _file_signature(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_ino,
        details.st_dev,
    )
