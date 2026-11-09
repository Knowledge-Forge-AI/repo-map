"""Real descriptor and object custody at governed sealing I/O boundaries."""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from common_lore_index.artifacts._metered_io import MeteredRaw, metered_hash, metered_open
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from repomap_test_support.sealing_governance_fixtures import open_descriptor_count


def _objects(store: FileSystemArtifactStore) -> dict[str, tuple[bytes, int]]:
    return {path.name: (path.read_bytes(), path.stat().st_mode)
            for path in (store.root / "objects").iterdir()}


def test_directory_descriptor_keeps_the_original_anchor_after_rename(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "fixture").write_bytes(b"original")
    before = open_descriptor_count()
    anchor = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    descriptor = None
    try:
        source.rename(tmp_path / "moved")
        source.mkdir()
        (source / "fixture").write_bytes(b"replacement")
        meter = SealingMeter(SealingBudget(max_opens=1), governed=True)
        descriptor = metered_open(meter, "fixture", os.O_RDONLY, dir_fd=anchor)
        assert os.read(descriptor, 64) == b"original"
        assert meter.snapshot().opens == 1
        with pytest.raises(SealingBudgetExceeded, match="opens"):
            metered_open(meter, "fixture", os.O_RDONLY, dir_fd=anchor)
        assert (source / "fixture").read_bytes() == b"replacement"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(anchor)
    assert open_descriptor_count() == before


def test_raw_stream_zero_read_and_repeated_close_preserve_descriptor_ownership(tmp_path: Path) -> None:
    path = tmp_path / "fixture"
    path.write_bytes(b"payload")
    before = open_descriptor_count()
    meter = SealingMeter(SealingBudget(max_read_bytes=8), governed=True)
    descriptor = metered_open(meter, path, os.O_RDONLY)
    raw = MeteredRaw(meter, "capture", descriptor)
    try:
        assert raw.fileno() == descriptor and raw.readable() and not raw.seekable()
        assert raw.readinto(bytearray()) == 0
        assert meter.snapshot().read_calls == 0
        buffer = bytearray(7)
        assert raw.readinto(buffer) == 7 and bytes(buffer) == b"payload"
        assert raw.readinto(buffer) == 0
        assert meter.snapshot().reader("capture") == 7
    finally:
        raw.close()
        raw.close()
    with pytest.raises(OSError) as closed:
        os.fstat(descriptor)
    assert closed.value.errno == errno.EBADF
    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("absent", "directory"))
def test_hash_failure_counts_only_attempted_io_and_releases_owned_fd(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "fixture"
    if kind == "directory":
        path.mkdir()
    before = open_descriptor_count()
    meter = SealingMeter(None, governed=False)
    hasher = hashlib.sha256()
    with pytest.raises(OSError):
        metered_hash(meter, "capture", path, hasher.update)
    assert (meter.snapshot().opens, meter.snapshot().read_calls, meter.snapshot().read_bytes) == (1, 0, 0)
    assert hasher.digest() == hashlib.sha256(b"").digest()
    assert open_descriptor_count() == before


@pytest.mark.parametrize("case", ("empty", "mixed-empty-chunks", "oversized", "wrong-digest", "bad-chunk"))
def test_streamed_put_keeps_accepted_objects_and_removes_its_temporary(tmp_path: Path, case: str) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    accepted = store.put(b"accepted fixture")
    before_objects = _objects(store)
    assert all(stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600
               for _, mode in before_objects.values())
    before_fds = open_descriptor_count()
    meter = SealingMeter(None, governed=False)
    content: Any = iter((b"",))  # Includes intentionally invalid chunks below.
    expected = b""
    options: dict[str, Any] = {}
    failure = None
    if case == "mixed-empty-chunks":
        content = iter((b"", bytearray(b"abc"), memoryview(b"def"), b""))
        expected = b"abcdef"
    elif case == "oversized":
        content = iter((b"abc", b"defg"))
        options = {"max_bytes": 6}
        failure = "bounds exceeded"
    elif case == "wrong-digest":
        content = iter((b"abc",))
        options = {"content_digest": "sha256:" + "0" * 64}
        failure = "digest does not match supplied"
    elif case == "bad-chunk":
        content = iter((b"abc", "invalid"))
        failure = "must be bytes"
    if failure is not None:
        with pytest.raises(ArtifactIntegrityError, match=failure):
            store.put(content, io_meter=meter, **options)
        assert _objects(store) == before_objects
    else:
        reference = store.put(content, io_meter=meter)
        assert reference.content_digest == "sha256:" + hashlib.sha256(expected).hexdigest()
        assert reference.size_bytes == len(expected) and store.read(reference) == expected
        assert meter.snapshot().write_bytes == len(expected)
        assert meter.snapshot().reader("store") == len(expected)
    assert store.read(accepted) == b"accepted fixture"
    assert not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == before_fds


@pytest.mark.parametrize("kind", ("wrong-size", "same-size-corruption", "symlink"))
def test_collision_refusal_keeps_exact_incumbent_and_foreign_file(tmp_path: Path, kind: str) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    body = b"fixture payload"
    reference = store.put(body)
    target = store.object_path(reference)
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"foreign fixture")
    prior: tuple[int, str | bytes]
    if kind == "symlink":
        target.unlink()
        target.symlink_to(foreign)
        prior = (target.lstat().st_mode, os.readlink(target))
    else:
        target.write_bytes(b"short" if kind == "wrong-size" else b"x" * len(body))
        prior = (target.lstat().st_mode, target.read_bytes())
    before_fds = open_descriptor_count()
    meter = SealingMeter(None, governed=False)
    with pytest.raises(ArtifactIntegrityError):
        store.put(body, io_meter=meter)
    after = (target.lstat().st_mode, os.readlink(target) if target.is_symlink() else target.read_bytes())
    assert after == prior
    assert foreign.read_bytes() == b"foreign fixture"
    assert len(list((store.root / "objects").iterdir())) == 1
    assert not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == before_fds
