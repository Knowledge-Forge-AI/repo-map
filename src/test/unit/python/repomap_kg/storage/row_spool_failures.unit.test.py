"""Failure boundaries retain row-file custody until explicit transfer."""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NoReturn

import pytest

from common_lore_index.storage import row_spool as module
from common_lore_index.storage.row_spool import RowSpool, RowSpoolWriter


class Interrupted(BaseException):
    """An injected in-process interruption without OS signal delivery."""


@pytest.mark.parametrize("boundary", ["fdopen", "clock", "observer", "timing", "stat", "constructor", "iterator", "encoding"])
def test_from_rows_failure_reclaims_file_and_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unrelated")
    allocated: list[tuple[int, Path]] = []
    original_mkstemp = module.tempfile.mkstemp
    original_stat = Path.stat
    marker = Interrupted()

    def allocate(**kwargs):
        fd, name = original_mkstemp(**kwargs)
        allocated.append((fd, Path(name)))
        return fd, name

    def refuse(*_args, **_kwargs) -> NoReturn:
        raise marker

    def stat(path, *args, **kwargs):
        if allocated and path == allocated[0][1]:
            raise marker
        return original_stat(path, *args, **kwargs)

    def rows():
        yield {"value": "public 🐦"}
        raise marker

    class RefusingSpool(RowSpool):
        def __init__(self, *_args, **_kwargs) -> None:
            raise marker

    monkeypatch.setattr(module.tempfile, "mkstemp", allocate)
    observer = None
    timing = None
    clock = module.time.monotonic_ns
    selected: type[RowSpool] = RowSpool
    inputs: Iterable[Mapping[str, object]] = ({"value": "public 🐦"},)
    if boundary == "fdopen":
        monkeypatch.setattr(module.os, "fdopen", refuse)
    elif boundary == "clock":
        timing = lambda _: None
        clock = refuse
    elif boundary == "observer":
        observer = refuse
    elif boundary == "timing":
        timing = refuse
    elif boundary == "stat":
        monkeypatch.setattr(Path, "stat", stat)
    elif boundary == "constructor":
        selected = RefusingSpool
    elif boundary == "iterator":
        inputs = rows()
    else:
        inputs = ({"value": "\ud800"},)
    try:
        with pytest.raises((Interrupted, UnicodeEncodeError)) as caught:
            selected.from_rows(inputs, dir=tmp_path, artifact_observer=observer, timing_observer=timing, monotonic_ns=clock)
        if boundary != "encoding":
            assert caught.value is marker
        assert len(allocated) == 1
        with pytest.raises(OSError):
            os.fstat(allocated[0][0])
        assert not os.path.lexists(allocated[0][1])
        assert sentinel.read_bytes() == b"unrelated"
    finally:
        for _fd, path in allocated:
            path.unlink(missing_ok=True)


def test_finished_writer_transfers_custody_to_replay(tmp_path: Path) -> None:
    rows = ({"value": "é"}, {"value": ""})
    with RowSpoolWriter(dir=tmp_path) as writer:
        for row in rows:
            writer.write_row(row)
        spool = writer.finish()
    try:
        writer.abort()
        assert spool.path.exists()
        assert tuple(spool) == rows
        assert spool.byte_count == spool.path.stat().st_size
        with pytest.raises(RuntimeError):
            writer.finish()
        with pytest.raises(RuntimeError):
            writer.write_row({})
    finally:
        spool.close()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("boundary", ["flush", "close", "stat", "constructor"])
def test_finish_failure_remains_owned_until_context_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    writer = RowSpoolWriter(dir=tmp_path)
    handle = writer._handle
    original_stat = Path.stat
    marker = Interrupted()

    class Handle:
        def flush(self):
            if boundary == "flush":
                raise marker
            handle.flush()

        def close(self):
            handle.close()
            if boundary == "close":
                raise marker

    def stat(path, *args, **kwargs):
        if path == writer.path:
            raise marker
        return original_stat(path, *args, **kwargs)

    def refuse(*_args, **_kwargs) -> NoReturn:
        raise marker

    writer.write_row({"value": "public"})
    monkeypatch.setattr(writer, "_handle", Handle())
    if boundary == "stat":
        monkeypatch.setattr(Path, "stat", stat)
    elif boundary == "constructor":
        monkeypatch.setattr(module, "RowSpool", refuse)
    try:
        with pytest.raises(Interrupted) as caught:
            with writer:
                writer.finish()
        assert caught.value is marker
        assert handle.closed
        assert not os.path.lexists(writer.path)
    finally:
        handle.close()
        writer.path.unlink(missing_ok=True)


def test_cleanup_failure_does_not_replace_producer_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary = Interrupted()
    secondary = OSError("synthetic unlink refusal")
    original_unlink = Path.unlink
    paths: list[Path] = []

    def refuse(path, *args, **kwargs):
        if path.name.startswith("repomap-stage-rows-"):
            paths.append(path)
            raise secondary
        return original_unlink(path, *args, **kwargs)

    def rows():
        yield {"value": "public"}
        raise primary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", refuse)
            with pytest.raises(Interrupted) as caught:
                RowSpool.from_rows(rows(), dir=tmp_path)
        assert caught.value is primary
        assert len(paths) == 1
    finally:
        for path in paths:
            original_unlink(path, missing_ok=True)
    assert not tuple(tmp_path.iterdir())


def test_handle_close_failure_does_not_replace_row_producer_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_fdopen = module.os.fdopen
    handles = []
    marker = Interrupted()

    class Handle:
        def __init__(self, handle):
            self.handle = handle

        def write(self, value):
            return self.handle.write(value)

        def close(self):
            self.handle.close()
            raise OSError("synthetic close failure after release")

    def fdopen(*args, **kwargs):
        handle = original_fdopen(*args, **kwargs)
        handles.append(handle)
        return Handle(handle)

    def rows():
        yield {"value": "public"}
        raise marker

    monkeypatch.setattr(module.os, "fdopen", fdopen)
    with pytest.raises(Interrupted) as caught:
        RowSpool.from_rows(rows(), dir=tmp_path)
    assert caught.value is marker
    assert len(handles) == 1 and handles[0].closed
    assert not tuple(tmp_path.iterdir())
