"""Metered, result-equivalent classification readers R1-R4 (ADR 0173 section 3.3).

Each reader reproduces the incumbent decoding stack and its observable result:

* R1 ``content_hash`` follows symlinks and digests the whole body.
* R2 ``first_line`` keeps ``TextIOWrapper`` UTF-8 decoding and readahead and
  may stop once the stripped line provably cannot start with ``#!``; every
  shebang predicate requires that prefix, so the classification is unchanged.
* R3 keeps the incumbent 40-line read, including later-line and buffered
  readahead decode failures.
* R4 streams strict UTF-8 to EOF and applies the ``splitlines``/``isspace``
  prefix rule with at most ten characters of carry; any decode error yields
  ``False`` exactly as ``read_text`` would.

Only governed meters bound retained classification text; observe-only meters
keep the incumbent unbounded retention and only count.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from common_lore_index.artifacts._metered_io import (
    READ_CHUNK,
    metered_hash,
    metered_open,
    metered_text,
    read_to_eof,
)
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import CLASSIFICATION_MAX_RETAINED_CHARS
from common_lore_index.extractors.languages.go_metadata import detect_go_generated_marker
from common_lore_index.extractors.shell.zsh_identity import ZSH_COMPLETION_PATH_PARTS

_READER = "classification"
_LINE_PIECE = 4096
_GO_LINES = 40
_PREFIXES = ("#compdef", "_arguments")
_CARRY = max(len(prefix) for prefix in _PREFIXES)
# str.splitlines boundaries; each one is also str.isspace.
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")


def metered_first_line(meter: SealingMeter, path: Path) -> str:
    """R2: the stripped first text line, or a non-shebang witness of it."""

    retained = 0
    head = ""  # the first two characters after leading whitespace
    parts: list[str] = []
    try:
        with metered_text(meter, _READER, path) as handle:
            while True:
                piece = handle.readline(_LINE_PIECE)
                parts.append(piece)
                retained += len(piece)
                if meter.governed and retained > CLASSIFICATION_MAX_RETAINED_CHARS:
                    raise meter.refuse_retention()
                if not piece or piece.endswith("\n"):
                    break
                if len(head) < 2:
                    head = (head + piece)[:2] if head else piece.lstrip()[:2]
                    if head and not "#!".startswith(head):
                        break  # no shebang predicate can match this line
    except UnicodeDecodeError:
        return ""
    return "".join(parts).strip()


def metered_is_go_generated(meter: SealingMeter, path: Path) -> bool:
    """R3: the incumbent 40-line generated-marker read."""

    lines: list[str] = []
    retained = 0
    try:
        with metered_text(meter, _READER, path) as handle:
            for _ in range(_GO_LINES):
                if not meter.governed:
                    lines.append(handle.readline())
                    continue
                remaining = CLASSIFICATION_MAX_RETAINED_CHARS - retained
                line = handle.readline(remaining + 1)
                if len(line) > remaining:
                    raise meter.refuse_retention()
                retained += len(line)
                lines.append(line)
    except UnicodeDecodeError:
        return False
    return detect_go_generated_marker("".join(lines)) is not None


class _CompletionScanner:
    """Incremental ``has_completion_content_evidence`` over decoded chunks.

    Lines are split with ``str.splitlines`` (the same boundaries as the
    incumbent); a line split across chunks carries at most ten characters of
    its stripped start, or a "decided, skip to line end" state.
    """

    def __init__(self) -> None:
        self.matched = False
        self._carry: str | None = ""  # "" at a line start, None when decided

    def feed(self, text: str) -> None:
        for piece in text.splitlines(keepends=True):
            ended = piece[-1] in _LINE_BREAKS
            if self._carry is None:
                self._carry = "" if ended else None
                continue
            head = (self._carry + piece) if self._carry else piece.lstrip()
            core = head.rstrip("".join(_LINE_BREAKS)) if ended else head
            if not core:
                self._carry = ""
            elif ended or len(core) >= _CARRY:
                self.matched = self.matched or core.startswith(_PREFIXES)
                self._carry = "" if ended else None
            else:
                self._carry = core

    def finish(self) -> bool:
        if self._carry:
            self.matched = self.matched or self._carry.startswith(_PREFIXES)
        return self.matched


def metered_completion(meter: SealingMeter, path: Path) -> bool:
    """R4: streaming ``is_zsh_completion_candidate(path)`` with identical results."""

    if path.name.startswith("_") and any(
        part in ZSH_COMPLETION_PATH_PARTS for part in path.parts[:-1]
    ):
        return True
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    scanner = _CompletionScanner()
    try:
        try:
            size = os.stat(path).st_size
        except OSError:
            size = None
        if size is not None:
            meter.require_read_headroom(size)
        descriptor = metered_open(meter, path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            read_to_eof(
                meter, _READER, descriptor, chunk=READ_CHUNK,
                declared=os.fstat(descriptor).st_size,
                consume=lambda data: scanner.feed(decoder.decode(data)),
            )
        finally:
            os.close(descriptor)
        scanner.feed(decoder.decode(b"", final=True))
    except (OSError, UnicodeDecodeError):
        return False
    return scanner.finish()


def metered_content_hash(meter: SealingMeter, path: Path) -> str:
    """R1: the discovery content hash, following symlinks like ``open(path, 'rb')``."""

    digest = hashlib.sha256()
    metered_hash(meter, "discovery", path, digest.update)
    return digest.hexdigest()


@dataclass(frozen=True)
class ClassificationReaders:
    """Reader functions bound to one meter, passed to ``classify_path``."""

    meter: SealingMeter

    def content_hash(self, path: Path) -> str:
        return metered_content_hash(self.meter, path)

    def first_line(self, path: Path) -> str:
        return metered_first_line(self.meter, path)

    def is_go_generated_file(self, path: Path) -> bool:
        return metered_is_go_generated(self.meter, path)

    def completion(self, path: Path) -> bool:
        return metered_completion(self.meter, path)


__all__ = (
    "ClassificationReaders",
    "metered_completion",
    "metered_content_hash",
    "metered_first_line",
    "metered_is_go_generated",
)
