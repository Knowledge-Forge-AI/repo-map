"""Bounded external sort for canonical publication bundle record streams."""

from __future__ import annotations

import heapq
from pathlib import Path
import tempfile
from typing import IO, Iterable, Iterator, Mapping

from repomap_kg.artifacts._canonical import canonical_json
from repomap_kg.artifacts.bundle import MAX_BUNDLE_LINE_BYTES
from repomap_kg.storage.staging_family_rows import StageFamily


_MAX_MEMORY_BUFFER_BYTES = 64 * 1024 * 1024


class BoundedExternalRowSorter:
    """Sort family records by canonical_json(record) with bounded heap memory."""

    def __init__(
        self,
        *,
        max_buffer_bytes: int = _MAX_MEMORY_BUFFER_BYTES,
        spool_dir: Path | str | None = None,
    ) -> None:
        self._max_buffer_bytes = max_buffer_bytes
        self._spool_dir = Path(spool_dir) if spool_dir is not None else None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.spill_run_count = 0
        self.spill_bytes = 0

    def _ensure_temp_dir(self) -> Path:
        if self._temp_dir is None:
            if self._spool_dir is not None:
                self._spool_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dir = tempfile.TemporaryDirectory(
                prefix="repomap_sort_",
                dir=str(self._spool_dir) if self._spool_dir is not None else None,
            )
        return Path(self._temp_dir.name)

    def sort_family_records(
        self,
        family: StageFamily,
        rows: Iterable[dict[str, object] | Mapping[str, object]],
    ) -> Iterator[bytes]:
        """Encode, sort, and stream canonical record lines for one family."""
        buffer: list[bytes] = []
        buffer_bytes = 0
        run_paths: list[Path] = []
        temp_dir: Path | None = None

        try:
            for row in rows:
                line = canonical_json(
                    {"family": family, "frame": "record", "record": dict(row)}
                )
                if len(line) > MAX_BUNDLE_LINE_BYTES:
                    raise ValueError("publication bundle line bounds exceeded")
                buffer.append(line)
                buffer_bytes += len(line)

                if buffer_bytes >= self._max_buffer_bytes:
                    buffer.sort()
                    if temp_dir is None:
                        temp_dir = self._ensure_temp_dir()
                    run_file = tempfile.NamedTemporaryFile(
                        dir=temp_dir, prefix=f"run_{family}_", suffix=".tmp", delete=False
                    )
                    try:
                        for item in buffer:
                            run_file.write(item)
                        run_file.flush()
                    finally:
                        run_file.close()
                    run_paths.append(Path(run_file.name))
                    self.spill_run_count += 1
                    self.spill_bytes += buffer_bytes
                    buffer.clear()
                    buffer_bytes = 0

            if not run_paths:
                # All rows fit in memory buffer
                buffer.sort()
                yield from buffer
                return

            if buffer:
                buffer.sort()
                if temp_dir is None:
                    temp_dir = self._ensure_temp_dir()
                run_file = tempfile.NamedTemporaryFile(
                    dir=temp_dir, prefix=f"run_{family}_", suffix=".tmp", delete=False
                )
                try:
                    for item in buffer:
                        run_file.write(item)
                    run_file.flush()
                finally:
                    run_file.close()
                run_paths.append(Path(run_file.name))
                self.spill_run_count += 1
                self.spill_bytes += buffer_bytes
                buffer.clear()

            # Merge sorted binary runs
            opened_files: list[IO[bytes]] = []
            try:
                opened_files = [open(path, "rb") for path in run_paths]
                for line in heapq.merge(*opened_files):
                    yield line
            finally:
                for file_obj in opened_files:
                    try:
                        file_obj.close()
                    except OSError:
                        pass
        finally:
            for path in run_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def close(self) -> None:
        """Clean up temporary directory and resources."""
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            finally:
                self._temp_dir = None

    def __enter__(self) -> BoundedExternalRowSorter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
