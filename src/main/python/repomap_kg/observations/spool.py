"""Private disk-backed replay for bounded staged-ingestion observations."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from repomap_kg.observations.raw import RawObservation


class ObservationSpool:
    """Replay one deterministic observation sequence from a private JSONL file."""

    def __init__(
        self,
        path: Path,
        count: int,
        byte_count: int = 0,
        allocated_byte_count: int = 0,
    ) -> None:
        self.path = path
        self.count = count
        self.byte_count = byte_count
        self.allocated_byte_count = allocated_byte_count
        self._closed = False

    @classmethod
    def from_observations(
        cls, observations: Iterable[RawObservation]
    ) -> ObservationSpool:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="repomap-observations-",
            suffix=".jsonl",
        )
        path = Path(raw_path)
        count = 0
        byte_count = 0
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                for observation in observations:
                    encoded = observation.to_json_line()
                    handle.write(encoded)
                    count += 1
                    byte_count += len(encoded.encode("utf-8"))
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        stat = path.stat()
        return cls(path, count, byte_count, stat.st_blocks * 512)

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[RawObservation]:
        if self._closed:
            raise RuntimeError("observation spool is closed")
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                yield RawObservation.from_json_line(line, line_number=line_number)

    def close(self) -> None:
        if self._closed:
            return
        self.path.unlink(missing_ok=True)
        self._closed = True

    def __enter__(self) -> ObservationSpool:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
