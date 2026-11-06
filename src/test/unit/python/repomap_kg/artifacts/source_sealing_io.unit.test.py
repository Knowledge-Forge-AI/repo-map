from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import common_lore_index.artifacts._source_sealing_io as io_mod
from common_lore_index.artifacts._source_sealing_io import (
    SourceUnsealableError,
    open_source_body,
)


def _open(path: Path, content: bytes):
    return open_source_body(
        path.parent,
        path.name,
        expected_size=len(content),
        expected_digest=hashlib.sha256(content).hexdigest(),
        expected_executable=False,
    )


def test_partial_consumer_closes_descriptor_and_refuses_unverified_body(
    tmp_path, monkeypatch
):
    path = tmp_path / "source.py"
    path.write_bytes(b"abc")
    closed: list[int] = []
    body_descriptor: list[int] = []
    original_close = io_mod.os.close

    def recording_close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(io_mod.os, "close", recording_close)
    with pytest.raises(ValueError, match="source changed while sealing"):
        with _open(path, b"abc") as body:
            body_descriptor.append(body._descriptor)
            assert next(body) == b"abc"
    assert closed
    assert body_descriptor
    with pytest.raises(OSError):
        os.fstat(body_descriptor[0])


def test_store_failure_preserves_original_error_and_closes_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"abc")
    closed: list[int] = []
    body_descriptor: list[int] = []
    original_close = io_mod.os.close

    def recording_close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(io_mod.os, "close", recording_close)
    with pytest.raises(RuntimeError, match="store failed"):
        with _open(path, b"abc") as body:
            body_descriptor.append(body._descriptor)
            next(body)
            raise RuntimeError("store failed")
    assert closed
    with pytest.raises(OSError):
        os.fstat(body_descriptor[0])


def test_fstat_failure_is_source_change_and_closes_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"abc")
    original_fstat = io_mod.os.fstat
    calls = 0

    def failing_fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("fstat failed")
        return original_fstat(descriptor)

    monkeypatch.setattr(io_mod.os, "fstat", failing_fstat)
    with pytest.raises(ValueError, match="source changed while sealing"):
        with _open(path, b"abc") as body:
            body_descriptor = body._descriptor
            next(body)
            next(body)
    with pytest.raises(OSError):
        os.fstat(body_descriptor)


def test_initial_file_fstat_failure_closes_opened_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"abc")
    original_open = io_mod.os.open
    original_fstat = io_mod.os.fstat
    opened: list[int] = []
    calls = 0

    def recording_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def failing_fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("initial fstat failed")
        return original_fstat(descriptor)

    monkeypatch.setattr(io_mod.os, "open", recording_open)
    monkeypatch.setattr(io_mod, "_supports_dir_fd", lambda: True)
    monkeypatch.setattr(io_mod.os, "fstat", failing_fstat)
    with pytest.raises(OSError, match="initial fstat failed"):
        with _open(path, b"abc"):
            pass
    assert len(opened) >= 2
    with pytest.raises(OSError):
        os.fstat(opened[-1])


def test_fallback_checks_path_identity_and_streams(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    content = b"abc"
    path.write_bytes(content)
    monkeypatch.setattr(io_mod, "_supports_dir_fd", lambda: False)
    with _open(path, content) as body:
        assert list(body) == [content]


def test_fallback_rejects_path_mutation_before_success(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"abc")
    monkeypatch.setattr(io_mod, "_supports_dir_fd", lambda: False)
    with pytest.raises(ValueError, match="source changed while sealing"):
        with _open(path, b"abc") as body:
            path.write_bytes(b"abd")
            list(body)


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo"))
def test_unsealable_path_kinds_are_rejected(tmp_path, kind):
    source = tmp_path / "source.py"
    source.write_bytes(b"abc")
    target = tmp_path / kind
    if kind == "symlink":
        if not hasattr(os, "symlink"):
            pytest.skip("symlinks unavailable")
        target.symlink_to(source)
    elif kind == "hardlink":
        os.link(source, target)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFOs unavailable")
        os.mkfifo(target)
    with pytest.raises(SourceUnsealableError, match="source inventory is not sealable"):
        with _open(target, b"abc"):
            pass


def test_symlinked_directory_component_is_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.py").write_bytes(b"abc")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SourceUnsealableError, match="source inventory is not sealable"):
        with open_source_body(
            tmp_path,
            "link/source.py",
            expected_size=3,
            expected_digest=hashlib.sha256(b"abc").hexdigest(),
            expected_executable=False,
        ):
            pass


@pytest.mark.parametrize("mutation", ("mode", "size", "digest"))
def test_descriptor_stream_rejects_source_mutation(tmp_path, mutation):
    path = tmp_path / "source.py"
    content = b"abc"
    path.write_bytes(content)
    if mutation == "mode":
        path.chmod(0o700)
        with pytest.raises(ValueError, match="source changed while sealing"):
            with _open(path, content):
                pass
        return
    with pytest.raises(ValueError, match="source changed while sealing"):
        with _open(path, content) as body:
            path.write_bytes(b"abd" if mutation == "digest" else b"abcd")
            list(body)
