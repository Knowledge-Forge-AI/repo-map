"""Internal artifact and row encoding helpers for external row sorting."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
import json
import os
from pathlib import Path
import tempfile

from repomap_kg.storage.structural_digest_encoding import (
    CanonicalJsonEncodingError,
    iter_canonical_json_chunks,
)


class ExternalRowSortError(ValueError):
    """Raised when a row cannot satisfy the bounded ordering contract."""


def _check_cancellation(
    cancellation_check: Callable[[], None] | None,
) -> None:
    if cancellation_check is not None:
        cancellation_check()


def _close_iterator(iterator: object) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


class _ArtifactTracker:
    def __init__(self, observer: Callable[[int, int], None] | None) -> None:
        self._observer = observer
        self._sizes: dict[Path, int] = {}

    def begin(self, path: Path) -> None:
        self._sizes[path] = 0
        self._publish()

    def resize(self, path: Path, byte_count: int) -> None:
        if path not in self._sizes or byte_count < self._sizes[path]:
            raise ExternalRowSortError(
                "external structural digest artifact state is invalid"
            )
        self._sizes[path] = byte_count
        self._publish()

    def remove(self, path: Path) -> None:
        self._sizes.pop(path, None)
        self._publish()

    def clear(self) -> None:
        if not self._sizes:
            return
        self._sizes.clear()
        self._publish()

    def _publish(self) -> None:
        if self._observer is not None:
            self._observer(sum(self._sizes.values()), len(self._sizes))


def _sort_key(
    row: Sequence[object],
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
) -> tuple[object, ...]:
    try:
        key = tuple(row[index] for index in key_indexes)
    except IndexError as error:
        raise ExternalRowSortError(
            "external structural digest sort key is invalid"
        ) from error
    if key_types is None:
        valid = all(
            not isinstance(value, bool) and isinstance(value, (int, str))
            for value in key
        )
    else:
        valid = all(
            not isinstance(value, bool) and type(value) is expected_type
            for value, expected_type in zip(key, key_types)
        )
    if not valid:
        raise ExternalRowSortError(
            "external structural digest sort key is invalid"
        )
    return key


def _encode_row(
    row: Sequence[object],
    key_indexes: tuple[int, ...],
    field_count: int,
    key_types: tuple[type, ...] | None,
    cancellation_check: Callable[[], None] | None,
) -> tuple[tuple[object, ...], str]:
    if not isinstance(row, (tuple, list)) or len(row) != field_count:
        raise ExternalRowSortError(
            "external structural digest row is invalid"
        )
    key = _sort_key(row, key_indexes, key_types)
    try:
        encoded = "".join(
            iter_canonical_json_chunks(row, cancellation_check)
        )
    except CanonicalJsonEncodingError as error:
        raise ExternalRowSortError(
            "external structural digest row value is invalid"
        ) from error
    return key, encoded


def _decode_row(encoded: str, field_count: int) -> list[object]:
    try:
        row = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ExternalRowSortError(
            "external structural digest run is invalid"
        ) from error
    if not isinstance(row, list) or len(row) != field_count:
        raise ExternalRowSortError(
            "external structural digest run is invalid"
        )
    return row


def _write_encoded_rows(
    directory: Path,
    rows: Iterable[str],
    artifacts: _ArtifactTracker,
) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix="run-",
        suffix=".jsonl",
        dir=directory,
    )
    path = Path(raw_path)
    iterator = iter(rows)
    tracked = False
    try:
        tracked = True
        artifacts.begin(path)
        with os.fdopen(
            descriptor,
            "w",
            encoding="ascii",
            newline="\n",
        ) as handle:
            written_bytes = 0
            for encoded in iterator:
                written_bytes += len(encoded) + 1
                artifacts.resize(path, written_bytes)
                handle.write(encoded)
                handle.write("\n")
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if tracked:
            artifacts.remove(path)
        path.unlink(missing_ok=True)
        raise
    finally:
        _close_iterator(iterator)
    return path


def _iter_encoded_run(
    path: Path,
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
    field_count: int,
) -> Iterator[tuple[tuple[object, ...], str]]:
    try:
        with path.open(encoding="ascii") as handle:
            for line in handle:
                encoded = line.removesuffix("\n")
                row = _decode_row(encoded, field_count)
                yield _sort_key(row, key_indexes, key_types), encoded
    except OSError as error:
        raise ExternalRowSortError(
            "external structural digest run is unavailable"
        ) from error
