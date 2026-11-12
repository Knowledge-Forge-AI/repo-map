"""Owned spill runs and bounded, incremental merge levels for one family."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack
import heapq
from pathlib import Path
import tempfile
from typing import BinaryIO, Literal

from common_lore_index.artifacts._bundle_cancellation import closing_bundle_resource


class BundleSortRuns:
    """Keep run custody through partial writes, compaction and final iteration."""

    def __init__(
        self, *, directory: Callable[[], Path], checkpoint: Callable[[], None],
        opener: Callable[[Path, Literal["rb"]], BinaryIO], fan_in: int,
    ) -> None:
        if type(fan_in) is not int or fan_in < 2:
            raise ValueError("merge fan-in must be an integer greater than one")
        self._directory = directory
        self._checkpoint = checkpoint
        self._opener = opener
        self._fan_in = fan_in
        self._owned: set[Path] = set()
        self._levels: list[list[Path]] = []
        self.initial_run_count = 0
        self.initial_bytes = 0

    @property
    def has_runs(self) -> bool:
        return any(self._levels)

    def _write(self, lines: Iterator[bytes], prefix: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            dir=self._directory(), prefix=prefix, suffix=".tmp", delete=False,
        )
        path = Path(handle.name)
        self._owned.add(path)
        with closing_bundle_resource(handle):
            for line in lines:
                self._checkpoint()
                handle.write(line)
            handle.flush()
        return path

    def _remove(self, paths: Sequence[Path], *, preserve_primary: bool = False) -> None:
        first: BaseException | None = None
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except BaseException as error:
                if first is None:
                    first = error
            else:
                self._owned.discard(path)
        if first is not None and not preserve_primary:
            raise first

    def _merged_lines(self, paths: Sequence[Path]) -> Iterator[bytes]:
        stack = ExitStack()
        with closing_bundle_resource(stack):
            opened: list[BinaryIO] = []
            for path in paths:
                self._checkpoint()
                handle = self._opener(path, "rb")
                stack.enter_context(closing_bundle_resource(handle))
                opened.append(handle)
            for line in heapq.merge(*opened):
                self._checkpoint()
                yield line

    def _compact(self, paths: Sequence[Path]) -> Path:
        lines = self._merged_lines(paths)
        with closing_bundle_resource(lines):
            output = self._write(lines, "merge_")
        # Failed unlink aborts progress, with all remaining paths still owned.
        self._remove(paths)
        return output

    def _add(self, path: Path, level: int) -> None:
        while True:
            if level == len(self._levels):
                self._levels.append([])
            self._levels[level].append(path)
            if len(self._levels[level]) < self._fan_in:
                return
            path = self._compact(self._levels[level])
            self._levels[level] = []
            level += 1

    def spill(self, lines: Sequence[bytes], family: str) -> None:
        path = self._write(iter(lines), f"run_{family}_")
        self.initial_run_count += 1
        self.initial_bytes += sum(map(len, lines))
        self._add(path, 0)

    def merged(self) -> Iterator[bytes]:
        while sum(map(len, self._levels)) > self._fan_in:
            level = next(n for n, paths in enumerate(self._levels) if paths)
            paths = self._levels[level]
            self._levels[level] = []
            output = paths[0] if len(paths) == 1 else self._compact(paths)
            self._add(output, level + 1)
        paths = [path for level in self._levels for path in level]
        lines = self._merged_lines(paths)
        with closing_bundle_resource(lines):
            yield from lines

    def close(self, *, preserve_primary: bool = False) -> None:
        self._remove(sorted(self._owned), preserve_primary=preserve_primary)
