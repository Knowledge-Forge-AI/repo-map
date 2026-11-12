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
        dir: Path | str | None = None,
        artifact_observer: Callable[[int], None] | None = None,
        timing_observer: Callable[[int], None] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> RowSpool:
        if dir is not None:
            descriptor, raw_path = tempfile.mkstemp(prefix="repomap-stage-rows-", suffix=".jsonl", dir=str(dir))
        else:
            descriptor, raw_path = tempfile.mkstemp(prefix="repomap-stage-rows-", suffix=".jsonl")
        path = Path(raw_path)
        count = 0
        byte_count = 0
        elapsed_ns = 0
        descriptor_owned = True
        try:
            handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
            descriptor_owned = False
            try:
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
                    handle.close()
                except BaseException:
                    pass
                raise
            else:
                handle.close()
            if timing_observer is not None:
                timing_observer(elapsed_ns)
            stat = path.stat()
            return cls(path, count, byte_count, stat.st_blocks * 512)
        except BaseException:
            if descriptor_owned:
                try:
                    os.close(descriptor)
                except BaseException:
                    pass
            try:
                path.unlink(missing_ok=True)
            except BaseException:
                pass
            raise

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


class RowSpoolWriter:
    """Incrementally write rows into a private JSONL spool file."""

    def __init__(
        self,
        *,
        dir: Path | str | None = None,
        artifact_observer: Callable[[int], None] | None = None,
    ) -> None:
        if dir is not None:
            Path(dir).mkdir(parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(prefix="repomap-stage-rows-", suffix=".jsonl", dir=str(dir))
        else:
            descriptor, raw_path = tempfile.mkstemp(prefix="repomap-stage-rows-", suffix=".jsonl")
        self.path = Path(raw_path)
        self._descriptor = descriptor
        try:
            self._handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        except BaseException:
            try:
                os.close(descriptor)
            except BaseException:
                pass
            try:
                self.path.unlink(missing_ok=True)
            except BaseException:
                pass
            raise
        self._count = 0
        self._byte_count = 0
        self._artifact_observer = artifact_observer
        self._finished = False
        self._transferred = False
        self._aborted = False

    def write_row(self, row: Mapping[str, object]) -> None:
        if self._finished:
            raise RuntimeError("writer already finished")
        if not isinstance(row, Mapping):
            raise ValueError("staged row is invalid")
        encoded = json.dumps(
            dict(row),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        projected_bytes = self._byte_count + len(encoded.encode("utf-8")) + 1
        if self._artifact_observer is not None:
            self._artifact_observer(projected_bytes)
        self._handle.write(encoded)
        self._handle.write("\n")
        self._count += 1
        self._byte_count = projected_bytes

    def finish(self) -> RowSpool:
        if self._finished:
            raise RuntimeError("writer already finished")
        self._handle.flush()
        self._handle.close()
        self._finished = True
        stat = self.path.stat()
        spool = RowSpool(self.path, self._count, self._byte_count, stat.st_blocks * 512)
        self._transferred = True
        return spool

    def abort(self) -> None:
        if self._transferred or self._aborted:
            return
        error: BaseException | None = None
        try:
            self._handle.close()
        except BaseException as caught:
            error = caught
        self._finished = True
        try:
            self.path.unlink(missing_ok=True)
            self._aborted = True
        except BaseException:
            if error is None:
                raise
        if error is not None:
            raise error

    def __enter__(self) -> RowSpoolWriter:
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        if exc_type is None:
            self.abort()
        else:
            try:
                self.abort()
            except BaseException:
                pass


__all__ = ["RowSpool", "RowSpoolWriter"]
