"""Bounded external sort for canonical publication bundle record streams."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Iterable, Iterator, Mapping

from common_lore_index._temporary import OwnedTemporaryDirectory
from common_lore_index.artifacts._canonical import canonical_json
from common_lore_index.artifacts._bundle_cancellation import (
    BundleEncodingCancelled, close_iterator, closing_bundle_resource,
)
from common_lore_index.artifacts._bundle_sort_runs import BundleSortRuns
from common_lore_index.artifacts.bundle import MAX_BUNDLE_LINE_BYTES
from common_lore_index.storage.staging_family_rows import StageFamily


_MAX_MEMORY_BUFFER_BYTES = 64 * 1024 * 1024
_MAX_MERGE_FAN_IN = 32


class BoundedExternalRowSorter:
    """Sort canonical family lines with bounded buffers and merge descriptors."""

    def __init__(
        self, *, max_buffer_bytes: int = _MAX_MEMORY_BUFFER_BYTES,
        spool_dir: Path | str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._cancel_event = cancel_event
        self._max_buffer_bytes = max_buffer_bytes
        self._spool_dir = Path(spool_dir) if spool_dir is not None else None
        self._temp_dir: OwnedTemporaryDirectory | None = None
        self.spill_run_count = 0
        self.spill_bytes = 0

    def _check_cancelled(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise BundleEncodingCancelled()

    def _ensure_temp_dir(self) -> Path:
        if self._temp_dir is None:
            if self._spool_dir is not None:
                self._spool_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dir = OwnedTemporaryDirectory(
                prefix="repomap_sort_",
                dir=str(self._spool_dir) if self._spool_dir is not None else None,
            )
        return Path(self._temp_dir.name)

    def _admitted_lines(
        self, family: StageFamily,
        rows: Iterable[dict[str, object] | Mapping[str, object]],
        byte_budget: int | None, record_budget: int | None,
    ) -> Iterator[bytes]:
        iterator = None
        failed = False
        records = size = 0
        try:
            self._check_cancelled()
            iterator = iter(rows)
            while True:
                self._check_cancelled()
                try:
                    row = next(iterator)
                except StopIteration:
                    break
                self._check_cancelled()
                line = canonical_json({"family": family, "frame": "record", "record": dict(row)})
                if len(line) > MAX_BUNDLE_LINE_BYTES:
                    raise ValueError("publication bundle line bounds exceeded")
                records += 1
                size += len(line)
                if record_budget is not None and records > record_budget:
                    raise ValueError("publication bundle record bounds exceeded")
                if byte_budget is not None and size > byte_budget:
                    raise ValueError("publication bundle byte bounds exceeded")
                yield line
        except BaseException:
            failed = True
            raise
        finally:
            close_iterator(iterator, preserve_primary=failed)

    def sort_family_records(
        self, family: StageFamily,
        rows: Iterable[dict[str, object] | Mapping[str, object]], *,
        byte_budget: int | None = None, record_budget: int | None = None,
    ) -> Iterator[bytes]:
        """Admit canonical records, then sort with bounded incremental fan-in."""
        runs = BundleSortRuns(
            directory=self._ensure_temp_dir, checkpoint=self._check_cancelled,
            opener=open, fan_in=_MAX_MERGE_FAN_IN,
        )
        lines = self._admitted_lines(family, rows, byte_budget, record_budget)
        failed = False
        try:
            buffer: list[bytes] = []
            buffer_bytes = 0
            for line in lines:
                buffer.append(line)
                buffer_bytes += len(line)
                if buffer_bytes >= self._max_buffer_bytes:
                    buffer.sort()
                    runs.spill(buffer, family)
                    buffer.clear()
                    buffer_bytes = 0
            buffer.sort()
            if not runs.has_runs:
                for line in buffer:
                    self._check_cancelled()
                    yield line
            else:
                if buffer:
                    runs.spill(buffer, family)
                merged = runs.merged()
                with closing_bundle_resource(merged):
                    yield from merged
        except BaseException:
            failed = True
            raise
        finally:
            self.spill_run_count += runs.initial_run_count
            self.spill_bytes += runs.initial_bytes
            try:
                close_iterator(lines, preserve_primary=failed)
            except BaseException:
                failed = True
                raise
            finally:
                runs.close(preserve_primary=failed)

    def close(self) -> None:
        """Clean up this sorter's owned temporary directory."""
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            finally:
                self._temp_dir = None

    def __enter__(self) -> BoundedExternalRowSorter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
