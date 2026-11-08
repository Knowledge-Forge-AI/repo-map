"""Metered stable capture R5 with incumbent signature-retry semantics.

The descriptor is opened without following the final component and its
signature is compared before and after the read, exactly like
``multi_source_capture._read_stable_file``. Up to three attempts run; every
attempt after the first is one counted stable-capture retry, and bytes read by
failed attempts stay charged. A governed refusal propagates before any
``OSError`` category mapping.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from common_lore_index.artifacts._metered_io import READ_CHUNK, metered_open, read_to_eof
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import (
    STABLE_CAPTURE_MAX_ATTEMPTS,
    SealingBudgetExceeded,
)
from common_lore_index.graph.multi_source_capture import (
    _SourceCapture,
    _SourceChanged,
    _SourceInvalid,
    _file_signature,
)

_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)


def read_stable_file_metered(path: Path, meter: SealingMeter) -> tuple[str, int, bool]:
    """Return ``(sha256, size, executable)`` of one regular file under the meter."""

    for attempt in range(STABLE_CAPTURE_MAX_ATTEMPTS):
        if attempt:
            meter.note_retry()
        descriptor: int | None = None
        try:
            before = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(before.st_mode):
                raise _SourceInvalid
            meter.require_read_headroom(before.st_size)
            owned = descriptor = metered_open(meter, path, _FLAGS)
            opened = os.fstat(owned)
            if _file_signature(before) != _file_signature(opened):
                descriptor = None
                os.close(owned)
                continue
            digest = hashlib.sha256()
            read_to_eof(
                meter, "capture", owned, chunk=READ_CHUNK,
                declared=opened.st_size, consume=digest.update,
            )
            after = os.fstat(owned)
            descriptor = None
            os.close(owned)
            if _file_signature(opened) != _file_signature(after):
                continue
            return digest.hexdigest(), after.st_size, bool(after.st_mode & 0o111)
        except (_SourceInvalid, SealingBudgetExceeded):
            raise
        except FileNotFoundError as error:
            raise _SourceChanged from error
        except OSError as error:
            raise _SourceCapture from error
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    raise _SourceChanged


__all__ = ("read_stable_file_metered",)
