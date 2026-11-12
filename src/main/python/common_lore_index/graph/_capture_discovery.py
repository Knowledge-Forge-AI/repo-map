"""Classification-preserving discovery for a subsequent authoritative capture.

Only the discarded discovery digest is provisional. Both stable capture
passes still hash the complete content and construct the snapshot authority.
The sealing-only scan is different: it needs no semantic classification.
"""
from __future__ import annotations

from collections.abc import Iterable
import errno
import os
from pathlib import Path
import stat

from common_lore_index.graph import _discovery_classify as classification


ELIDED_DISCOVERY_CONTENT_HASH = "elided:capture-discovery-v1"


class CaptureDiscoveryHooks:
    """Preserve classifier readers and replace an unused digest with a probe."""

    def walk(self, top: Path) -> Iterable[tuple[str, list[str], list[str]]]:
        return os.walk(top)

    def readers(self) -> CaptureDiscoveryHooks:
        return self

    def content_hash(self, path: Path) -> str:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        try:
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise IsADirectoryError(errno.EISDIR, "discovery path is a directory")
        finally:
            os.close(descriptor)
        return ELIDED_DISCOVERY_CONTENT_HASH

    def first_line(self, path: Path) -> str:
        return classification.first_line(path)

    def is_go_generated_file(self, path: Path) -> bool:
        return classification.is_go_generated_file(path)

    def completion(self, path: Path) -> bool:
        return classification.is_zsh_completion_candidate(path)
