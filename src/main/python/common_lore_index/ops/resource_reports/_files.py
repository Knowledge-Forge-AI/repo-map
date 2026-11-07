"""Bounded, non-following reads of private resource-report files.

Readers accept a regular file owned by the effective user with no group or
other permission bits and one or more links: a transient or failed temporary
cleanup can leave a second link to an installed report. Symlinks, FIFOs,
devices, sockets and directories are refused without being opened.
"""

from __future__ import annotations

import os
import stat

from ._codec import MAX_FILE_BYTES, ResourceReportError

_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOCTTY", 0)
)


def _private_regular(details: os.stat_result) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.geteuid()
        and details.st_mode & 0o077 == 0
        and details.st_nlink >= 1
    )


def read_report_file(path: str | os.PathLike[str]) -> bytes:
    """Return at most ``MAX_FILE_BYTES`` from one private regular report file."""
    try:
        before = os.lstat(path)
    except OSError:
        raise ResourceReportError("unreadable") from None
    if not _private_regular(before):
        raise ResourceReportError("unsafe_input")
    if before.st_size > MAX_FILE_BYTES:
        raise ResourceReportError("too_large")
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except OSError:
        raise ResourceReportError("unreadable") from None
    try:
        opened = os.fstat(descriptor)
        if (
            not _private_regular(opened)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ResourceReportError("unsafe_input")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_FILE_BYTES:
            chunk = os.read(descriptor, MAX_FILE_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except ResourceReportError:
        raise
    except OSError:
        raise ResourceReportError("unreadable") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass  # a read-only descriptor; never replace the primary outcome
    if total > MAX_FILE_BYTES:
        raise ResourceReportError("too_large")
    return b"".join(chunks)


__all__ = ("read_report_file",)
