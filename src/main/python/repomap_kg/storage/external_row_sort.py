"""Bounded external ordering for structural-digest row streams."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
import heapq
from pathlib import Path
import tempfile

from repomap_kg.storage._external_row_sort_helpers import (
    ExternalRowSortError,
    _ArtifactTracker,
    _check_cancellation,
    _close_iterator,
    _decode_row,
    _encode_row,
    _iter_encoded_run,
    _write_encoded_rows,
)

__all__ = (
    "ExternalRowSortError",
    "external_sort_encoded_rows",
    "external_sort_rows",
)

_DEFAULT_RUN_BYTE_LIMIT = 4 * 1024 * 1024
_DEFAULT_MERGE_FAN_IN = 32
_MAX_RUN_LEVELS = 4


def external_sort_rows(
    rows: Iterable[Sequence[object]],
    *,
    key_indexes: tuple[int, ...],
    field_count: int,
    key_types: tuple[type, ...] | None = None,
    cancellation_check: Callable[[], None] | None = None,
    artifact_observer: Callable[[int, int], None] | None = None,
    run_byte_limit: int = _DEFAULT_RUN_BYTE_LIMIT,
    merge_fan_in: int = _DEFAULT_MERGE_FAN_IN,
) -> Iterator[list[object]]:
    """Yield rows in stable key order using bounded in-memory runs."""

    encoded_rows = external_sort_encoded_rows(
        rows,
        key_indexes=key_indexes,
        field_count=field_count,
        key_types=key_types,
        cancellation_check=cancellation_check,
        artifact_observer=artifact_observer,
        run_byte_limit=run_byte_limit,
        merge_fan_in=merge_fan_in,
    )
    try:
        for encoded in encoded_rows:
            yield _decode_row(encoded, field_count)
    finally:
        _close_iterator(encoded_rows)


def external_sort_encoded_rows(
    rows: Iterable[Sequence[object]],
    *,
    key_indexes: tuple[int, ...],
    field_count: int,
    key_types: tuple[type, ...] | None = None,
    cancellation_check: Callable[[], None] | None = None,
    artifact_observer: Callable[[int, int], None] | None = None,
    run_byte_limit: int = _DEFAULT_RUN_BYTE_LIMIT,
    merge_fan_in: int = _DEFAULT_MERGE_FAN_IN,
) -> Iterator[str]:
    """Yield validated canonical row encodings in stable key order."""

    if (
        run_byte_limit <= 0
        or merge_fan_in < 2
        or (key_types is not None and len(key_types) != len(key_indexes))
    ):
        raise ValueError("external row sort configuration is invalid")
    source = iter(rows)
    artifacts = _ArtifactTracker(artifact_observer)
    try:
        with tempfile.TemporaryDirectory(
            prefix="repomap-structural-digest-"
        ) as raw_directory:
            directory = Path(raw_directory)
            buffered: list[tuple[tuple[object, ...], str]] = []
            buffered_bytes = 0
            run_levels: list[list[Path]] = [
                [] for _level in range(_MAX_RUN_LEVELS)
            ]
            has_runs = False
            for row in source:
                _check_cancellation(cancellation_check)
                key, encoded = _encode_row(
                    row,
                    key_indexes,
                    field_count,
                    key_types,
                    cancellation_check,
                )
                encoded_bytes = len(encoded)
                if buffered and buffered_bytes + encoded_bytes > run_byte_limit:
                    _add_run(
                        run_levels,
                        _write_run(directory, buffered, artifacts),
                        directory,
                        key_indexes,
                        key_types,
                        field_count,
                        cancellation_check,
                        merge_fan_in,
                        artifacts,
                    )
                    has_runs = True
                    buffered = []
                    buffered_bytes = 0
                buffered.append((key, encoded))
                buffered_bytes += encoded_bytes
                if buffered_bytes >= run_byte_limit:
                    _add_run(
                        run_levels,
                        _write_run(directory, buffered, artifacts),
                        directory,
                        key_indexes,
                        key_types,
                        field_count,
                        cancellation_check,
                        merge_fan_in,
                        artifacts,
                    )
                    has_runs = True
                    buffered = []
                    buffered_bytes = 0

            if not has_runs:
                buffered.sort(key=lambda item: (item[0], item[1]))
                for _key, encoded in buffered:
                    _check_cancellation(cancellation_check)
                    yield encoded
                return

            if buffered:
                _add_run(
                    run_levels,
                    _write_run(directory, buffered, artifacts),
                    directory,
                    key_indexes,
                    key_types,
                    field_count,
                    cancellation_check,
                    merge_fan_in,
                    artifacts,
                )
            runs = _finalize_run_levels(
                run_levels,
                directory,
                key_indexes,
                key_types,
                field_count,
                cancellation_check,
                artifacts,
            )
            for encoded in _merge_encoded_runs(
                runs,
                key_indexes,
                key_types,
                field_count,
                cancellation_check,
            ):
                yield encoded
    finally:
        _close_iterator(source)
        artifacts.clear()


def _add_run(
    levels: list[list[Path]],
    path: Path,
    directory: Path,
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
    field_count: int,
    cancellation_check: Callable[[], None] | None,
    merge_fan_in: int,
    artifacts: _ArtifactTracker,
    level: int = 0,
) -> None:
    if level >= len(levels):
        raise ExternalRowSortError(
            "external structural digest run bound is exceeded"
        )
    levels[level].append(path)
    if len(levels[level]) < merge_fan_in:
        return
    group = levels[level]
    levels[level] = []
    output = _write_merged_run(
        directory,
        group,
        key_indexes,
        key_types,
        field_count,
        cancellation_check,
        artifacts,
    )
    _remove_runs(group, artifacts)
    _add_run(
        levels,
        output,
        directory,
        key_indexes,
        key_types,
        field_count,
        cancellation_check,
        merge_fan_in,
        artifacts,
        level + 1,
    )


def _finalize_run_levels(
    levels: list[list[Path]],
    directory: Path,
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
    field_count: int,
    cancellation_check: Callable[[], None] | None,
    artifacts: _ArtifactTracker,
) -> list[Path]:
    final: list[Path] = []
    for group in levels:
        if not group:
            continue
        if len(group) == 1:
            final.extend(group)
            continue
        output = _write_merged_run(
            directory,
            group,
            key_indexes,
            key_types,
            field_count,
            cancellation_check,
            artifacts,
        )
        _remove_runs(group, artifacts)
        final.append(output)
    return final


def _remove_runs(runs: Sequence[Path], artifacts: _ArtifactTracker) -> None:
    for path in runs:
        path.unlink(missing_ok=True)
        artifacts.remove(path)


def _write_run(
    directory: Path,
    rows: list[tuple[tuple[object, ...], str]],
    artifacts: _ArtifactTracker,
) -> Path:
    rows.sort(key=lambda item: (item[0], item[1]))
    return _write_encoded_rows(
        directory,
        (encoded for _key, encoded in rows),
        artifacts,
    )


def _write_merged_run(
    directory: Path,
    runs: list[Path],
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
    field_count: int,
    cancellation_check: Callable[[], None] | None,
    artifacts: _ArtifactTracker,
) -> Path:
    return _write_encoded_rows(
        directory,
        _merge_encoded_runs(
            runs,
            key_indexes,
            key_types,
            field_count,
            cancellation_check,
        ),
        artifacts,
    )


def _merge_encoded_runs(
    runs: Sequence[Path],
    key_indexes: tuple[int, ...],
    key_types: tuple[type, ...] | None,
    field_count: int,
    cancellation_check: Callable[[], None] | None,
) -> Iterator[str]:
    iterators = [
        _iter_encoded_run(path, key_indexes, key_types, field_count)
        for path in runs
    ]
    heap: list[tuple[tuple[object, ...], str, int]] = []
    try:
        for index, iterator in enumerate(iterators):
            try:
                key, encoded = next(iterator)
            except StopIteration:
                continue
            heapq.heappush(heap, (key, encoded, index))
        while heap:
            _check_cancellation(cancellation_check)
            _key, encoded, index = heapq.heappop(heap)
            yield encoded
            try:
                key, next_encoded = next(iterators[index])
            except StopIteration:
                continue
            heapq.heappush(heap, (key, next_encoded, index))
    finally:
        for iterator in iterators:
            _close_iterator(iterator)
