from __future__ import annotations

from pathlib import Path
import stat

import pytest

from repomap_kg.storage import external_row_sort
from repomap_kg.storage.external_row_sort import (
    ExternalRowSortError,
    external_sort_encoded_rows,
    external_sort_rows,
)


def test_default_run_payload_target_is_four_mib() -> None:
    assert external_row_sort._DEFAULT_RUN_BYTE_LIMIT == 4 * 1024**2


def test_external_sort_merges_multiple_bounded_passes() -> None:
    rows = [(value, {"payload": value}) for value in range(12, -1, -1)]

    assert list(
        external_sort_rows(
            rows,
            key_indexes=(0,),
            field_count=2,
            run_byte_limit=1,
            merge_fan_in=2,
        )
    ) == [[value, {"payload": value}] for value in range(13)]


def test_external_sort_exposes_the_validated_canonical_row_encoding() -> None:
    assert list(
        external_sort_encoded_rows(
            ((2, {"z": 1, "a": "café"}), (1, {})),
            key_indexes=(0,),
            field_count=2,
        )
    ) == ['[1,{}]', '[2,{"a":"caf\\u00e9","z":1}]']


def test_external_sort_uses_private_runs_and_removes_them(
    monkeypatch,
) -> None:
    paths: list[Path] = []
    modes: list[int] = []
    original = external_row_sort._write_encoded_rows

    def capturing_write(directory, rows, artifacts):
        path = original(directory, rows, artifacts)
        paths.append(path)
        modes.append(stat.S_IMODE(path.stat().st_mode))
        return path

    monkeypatch.setattr(
        external_row_sort,
        "_write_encoded_rows",
        capturing_write,
    )

    assert list(
        external_sort_rows(
            [(3,), (2,), (1,)],
            key_indexes=(0,),
            field_count=1,
            run_byte_limit=1,
            merge_fan_in=2,
        )
    ) == [[1], [2], [3]]
    assert paths
    assert set(modes) == {0o600}
    assert all(not path.exists() for path in paths)
    assert all(not path.parent.exists() for path in paths)


def test_external_sort_cancellation_closes_source_and_removes_runs(
    monkeypatch,
) -> None:
    paths: list[Path] = []
    closed = False
    checks = 0
    original = external_row_sort._write_encoded_rows

    def capturing_write(directory, rows, artifacts):
        path = original(directory, rows, artifacts)
        paths.append(path)
        return path

    def source():
        nonlocal closed
        try:
            for value in range(20, -1, -1):
                yield (value,)
        finally:
            closed = True

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 8:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        external_row_sort,
        "_write_encoded_rows",
        capturing_write,
    )

    with pytest.raises(KeyboardInterrupt):
        list(
            external_sort_rows(
                source(),
                key_indexes=(0,),
                field_count=1,
                cancellation_check=cancel,
                run_byte_limit=1,
                merge_fan_in=2,
            )
        )
    assert closed is True
    assert paths
    assert all(not path.exists() for path in paths)
    assert all(not path.parent.exists() for path in paths)


def test_external_sort_rejects_invalid_keys_without_echoing_values() -> None:
    with pytest.raises(ExternalRowSortError, match="sort key") as error:
        list(
            external_sort_rows(
                [(None, "private-value")],
                key_indexes=(0,),
                field_count=2,
            )
        )

    assert "private-value" not in str(error.value)


def test_external_sort_bounds_live_runs_and_reports_merge_overlap() -> None:
    artifacts: list[tuple[int, int]] = []

    result = list(
        external_sort_rows(
            [(value,) for value in range(99, -1, -1)],
            key_indexes=(0,),
            field_count=1,
            artifact_observer=lambda byte_count, run_count: artifacts.append(
                (byte_count, run_count)
            ),
            run_byte_limit=1,
            merge_fan_in=4,
        )
    )

    assert result == [[value] for value in range(100)]
    assert max(run_count for _bytes, run_count in artifacts) <= 17
    assert max(byte_count for byte_count, _runs in artifacts) > 0
    assert artifacts[-1] == (0, 0)


def test_run_growth_is_observed_before_bytes_are_written(tmp_path) -> None:
    samples: list[tuple[int, int]] = []

    def stop_at_first_bytes(byte_count: int, run_count: int) -> None:
        samples.append((byte_count, run_count))
        if byte_count > 0:
            raise MemoryError("artifact ceiling")

    artifacts = external_row_sort._ArtifactTracker(stop_at_first_bytes)
    with pytest.raises(MemoryError, match="artifact ceiling"):
        external_row_sort._write_encoded_rows(
            tmp_path,
            iter(("x" * 100,)),
            artifacts,
        )

    assert samples[0] == (0, 1)
    assert samples[-1] == (0, 0)
    assert list(tmp_path.iterdir()) == []


def test_external_sort_cancels_during_row_encoding_then_retries_exactly() -> None:
    checks = 0
    rows = [(1, "x" * 200_000)]

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 4:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(
            external_sort_rows(
                rows,
                key_indexes=(0,),
                field_count=2,
                cancellation_check=cancel,
            )
        )

    assert list(
        external_sort_rows(rows, key_indexes=(0,), field_count=2)
    ) == [[1, "x" * 200_000]]


def test_external_sort_cancels_during_merge_and_closes_run_iterators(
    monkeypatch,
) -> None:
    merge_active = False
    closed_runs = 0
    original_merge = external_row_sort._merge_encoded_runs
    original_iter = external_row_sort._iter_encoded_run

    def tracking_merge(*args, **kwargs):
        nonlocal merge_active
        merge_active = True
        try:
            yield from original_merge(*args, **kwargs)
        finally:
            merge_active = False

    def tracking_iter(*args, **kwargs):
        nonlocal closed_runs
        try:
            yield from original_iter(*args, **kwargs)
        finally:
            closed_runs += 1

    def cancel() -> None:
        if merge_active:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        external_row_sort,
        "_merge_encoded_runs",
        tracking_merge,
    )
    monkeypatch.setattr(
        external_row_sort,
        "_iter_encoded_run",
        tracking_iter,
    )
    artifacts: list[tuple[int, int]] = []

    with pytest.raises(KeyboardInterrupt):
        list(
            external_sort_rows(
                [(value,) for value in range(8, -1, -1)],
                key_indexes=(0,),
                field_count=1,
                cancellation_check=cancel,
                artifact_observer=lambda byte_count, run_count: artifacts.append(
                    (byte_count, run_count)
                ),
                run_byte_limit=1,
                merge_fan_in=2,
            )
        )

    assert closed_runs > 0
    assert artifacts[-1] == (0, 0)
    assert list(
        external_sort_rows(
            [(value,) for value in range(8, -1, -1)],
            key_indexes=(0,),
            field_count=1,
            run_byte_limit=1,
            merge_fan_in=2,
        )
    ) == [[value] for value in range(9)]


def test_external_sort_rejects_invalid_limits_and_fan_in() -> None:
    with pytest.raises(ValueError, match="external row sort configuration is invalid"):
        list(
            external_sort_rows(
                [(1,)],
                key_indexes=(0,),
                field_count=1,
                run_byte_limit=0,
            )
        )

    with pytest.raises(ValueError, match="external row sort configuration is invalid"):
        list(
            external_sort_rows(
                [(1,)],
                key_indexes=(0,),
                field_count=1,
                merge_fan_in=1,
            )
        )

    with pytest.raises(ValueError, match="external row sort configuration is invalid"):
        list(
            external_sort_rows(
                [(1,)],
                key_indexes=(0,),
                field_count=1,
                key_types=(int, str),
            )
        )


def test_external_sort_rejects_invalid_sort_key_types() -> None:
    with pytest.raises(ExternalRowSortError, match="external structural digest sort key is invalid"):
        list(
            external_sort_rows(
                [(True,)],
                key_indexes=(0,),
                field_count=1,
            )
        )

    with pytest.raises(ExternalRowSortError, match="external structural digest sort key is invalid"):
        list(
            external_sort_rows(
                [(1.5,)],
                key_indexes=(0,),
                field_count=1,
            )
        )

    with pytest.raises(ExternalRowSortError, match="external structural digest sort key is invalid"):
        list(
            external_sort_rows(
                [("not-an-int",)],
                key_indexes=(0,),
                field_count=1,
                key_types=(int,),
            )
        )
