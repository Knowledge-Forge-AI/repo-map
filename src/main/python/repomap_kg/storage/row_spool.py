"""Private disk-backed replay for bounded staged-ingestion rows."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path


class RowSpool:
    """Replay one deterministic row sequence from a private JSONL file."""

    def __init__(
        self,
        path: Path,
        count: int,
        byte_count: int,
        allocated_byte_count: int = 0,
    ) -> None:
        self.path = path
        self.count = count
        self.byte_count = byte_count
        self.allocated_byte_count = allocated_byte_count
        self._closed = False

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Mapping[str, object]],
        *,
        artifact_observer: Callable[[int], None] | None = None,
        timing_observer: Callable[[int], None] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> RowSpool:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="repomap-stage-rows-",
            suffix=".jsonl",
        )
        path = Path(raw_path)
        count = 0
        byte_count = 0
        elapsed_ns = 0
        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise ValueError("staged row is invalid")
                    started = monotonic_ns() if timing_observer is not None else 0
                    encoded = json.dumps(
                        dict(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    projected_bytes = (
                        byte_count + len(encoded.encode("utf-8")) + 1
                    )
                    if artifact_observer is not None:
                        artifact_observer(projected_bytes)
                    handle.write(encoded)
                    handle.write("\n")
                    count += 1
                    byte_count = projected_bytes
                    if timing_observer is not None:
                        elapsed_ns += max(0, monotonic_ns() - started)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        if timing_observer is not None:
            timing_observer(elapsed_ns)
        stat = path.stat()
        return cls(path, count, byte_count, stat.st_blocks * 512)

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[dict[str, object]]:
        if self._closed:
            raise RuntimeError("row spool is closed")
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError("staged row spool is invalid") from error
                if not isinstance(row, dict):
                    raise ValueError("staged row spool is invalid")
                yield row

    def close(self) -> None:
        if self._closed:
            return
        self.path.unlink(missing_ok=True)
        self._closed = True

    def __enter__(self) -> RowSpool:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
