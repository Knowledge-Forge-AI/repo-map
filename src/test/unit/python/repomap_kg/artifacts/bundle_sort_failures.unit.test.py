"""Real spill and merge failures stop progress while retaining resource custody."""
from __future__ import annotations

import builtins
from collections.abc import Iterator
from pathlib import Path
import threading
from typing import Any, BinaryIO, Literal

import pytest

from common_lore_index.artifacts import _bundle_sort_runs as runs_module
from common_lore_index.artifacts import _bundle_stream_sort as sorter_module
from common_lore_index.artifacts._bundle_cancellation import BundleEncodingCancelled, close_iterator
from common_lore_index.artifacts._bundle_stream_sort import BoundedExternalRowSorter


def _run_files(sorter: BoundedExternalRowSorter) -> set[Path]:
    assert sorter._temp_dir is not None
    return set(Path(sorter._temp_dir.name).iterdir())


@pytest.mark.parametrize("fan_in", [0, 1, True])
def test_nonprogressing_fan_in_is_refused_before_any_io(fan_in: int) -> None:
    with pytest.raises(ValueError, match="merge fan-in must be an integer greater than one"):
        runs_module.BundleSortRuns(
            directory=lambda: pytest.fail("must not acquire a directory"),
            checkpoint=lambda: None, opener=builtins.open, fan_in=fan_in,
        )


class FaultingOutput:
    """Delegate actual IO and retain the real handle for closure assertions."""

    def __init__(self, raw: Any, failure: str, error: BaseException, event: threading.Event) -> None:
        self.raw = raw
        self.failure = failure
        self.error = error
        self.event = event

    @property
    def name(self) -> str:
        return self.raw.name

    def write(self, data: bytes) -> int:
        result = self.raw.write(data)
        if self.failure == "write":
            raise self.error
        if self.failure == "cancel":
            self.event.set()
        return result

    def flush(self) -> None:
        self.raw.flush()
        if self.failure == "flush":
            raise self.error

    def close(self) -> None:
        self.raw.close()
        if self.failure == "close":
            raise self.error


@pytest.mark.parametrize("failure", ["write", "flush", "close", "cancel"])
def test_partial_merge_output_failure_closes_every_handle_and_stops_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    event = threading.Event()
    primary = OSError("synthetic merge output refusal")
    consumed: list[int] = []
    input_closed: list[bool] = []
    opened: list[BinaryIO] = []
    outputs: list[Any] = []
    original_temporary = runs_module.tempfile.NamedTemporaryFile

    def temporary(**kwargs):
        raw = original_temporary(**kwargs)
        outputs.append(raw)
        return FaultingOutput(raw, failure, primary, event) if kwargs["prefix"] == "merge_" else raw

    def open_run(path: Path, mode: Literal["rb"]) -> BinaryIO:
        handle = builtins.open(path, mode)
        opened.append(handle)
        return handle

    def rows() -> Iterator[dict[str, object]]:
        try:
            for number in range(100):
                consumed.append(number)
                yield {"value": number}
        finally:
            input_closed.append(True)

    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 3)
    monkeypatch.setattr(sorter_module, "open", open_run, raising=False)
    monkeypatch.setattr(runs_module.tempfile, "NamedTemporaryFile", temporary)
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path, cancel_event=event) as sorter:
        with pytest.raises(BundleEncodingCancelled if failure == "cancel" else OSError) as caught:
            tuple(sorter.sort_family_records("files", rows()))
        if failure != "cancel":
            assert caught.value is primary
        assert not _run_files(sorter)
    assert consumed == [0, 1, 2]
    assert input_closed == [True]
    assert len(outputs) == 4
    assert all(handle.closed for handle in opened + outputs)
    assert not tuple(tmp_path.iterdir())


def test_merge_read_failure_closes_partial_inputs_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = OSError("synthetic run read refusal")
    handles: list[BinaryIO] = []

    class Reader:
        def __init__(self, raw: BinaryIO) -> None:
            self.raw = raw

        def __iter__(self):
            return self

        def __next__(self):
            next(self.raw)
            raise primary

        def close(self) -> None:
            self.raw.close()

    def open_run(path: Path, mode: Literal["rb"]):
        raw = builtins.open(path, mode)
        handles.append(raw)
        return Reader(raw)

    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 3)
    monkeypatch.setattr(sorter_module, "open", open_run, raising=False)
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        with pytest.raises(OSError) as caught:
            tuple(sorter.sort_family_records("files", ({"value": n} for n in range(20))))
        assert caught.value is primary
        assert not _run_files(sorter)
    assert len(handles) == 3 and all(handle.closed for handle in handles)
    assert not tuple(tmp_path.iterdir())


def test_failed_unlink_aborts_compaction_and_retains_every_path_for_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_unlink = Path.unlink
    primary = OSError("synthetic run unlink refusal")
    refused: list[Path] = []
    consumed: list[int] = []

    def unlink(path: Path, *args, **kwargs):
        if path.name.startswith("run_") and not refused:
            refused.append(path)
            raise primary
        return original_unlink(path, *args, **kwargs)

    def rows() -> Iterator[dict[str, object]]:
        for number in range(100):
            consumed.append(number)
            yield {"value": number}

    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 2)
    monkeypatch.setattr(Path, "unlink", unlink)
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        with pytest.raises(OSError) as caught:
            tuple(sorter.sort_family_records("files", rows()))
        assert caught.value is primary
        assert not _run_files(sorter)
    assert consumed == [0, 1]
    assert len(refused) == 1 and not refused[0].exists()
    assert not tuple(tmp_path.iterdir())


def test_new_cleanup_error_does_not_replace_actual_source_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = ValueError("synthetic source failure")
    secondary = OSError("synthetic unlink refusal")
    original_unlink = Path.unlink
    refused: list[Path] = []

    def unlink(path: Path, *args, **kwargs):
        if path.name.startswith("run_") and not refused:
            refused.append(path)
            raise secondary
        return original_unlink(path, *args, **kwargs)

    def rows() -> Iterator[dict[str, object]]:
        yield {"value": 1}
        raise primary

    monkeypatch.setattr(Path, "unlink", unlink)
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        with pytest.raises(ValueError) as caught:
            tuple(sorter.sort_family_records("files", rows()))
        assert caught.value is primary
        # This particular unlink was deliberately refused. Other owned files
        # must already be gone; the real directory fallback retries this one.
        assert _run_files(sorter) == set(refused)
    assert len(refused) == 1 and not refused[0].exists()
    assert not tuple(tmp_path.iterdir())


def test_partial_consumer_close_reclaims_all_multilevel_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 3)
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        stream = sorter.sort_family_records("files", ({"value": n} for n in range(37)))
        assert next(stream)
        close_iterator(stream)
        assert sorter._temp_dir is not None
        assert not tuple(Path(sorter._temp_dir.name).iterdir())
    assert not tuple(tmp_path.iterdir())
