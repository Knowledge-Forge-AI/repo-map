"""Metered store put: incumbent references, exact W1/R7/R7c counters and custody."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

import common_lore_index.artifacts._store_metered as store_metered
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._store_common import ArtifactIntegrityError
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.artifacts.store import FileSystemArtifactStore
from repomap_test_support.sealing_governance_fixtures import open_descriptor_count

CHUNK = 64 * 1024


def _calls(size: int) -> int:
    return -(-size // CHUNK) + 1


def _temporaries(store: FileSystemArtifactStore) -> list[str]:
    return sorted(os.listdir(store.root / "temporary"))


def test_metered_put_returns_the_incumbent_reference_with_exact_new_object_counters(tmp_path: Path) -> None:
    data = os.urandom(3 * CHUNK + 5)
    plain = FileSystemArtifactStore(tmp_path / "plain").put(data, media_type="application/octet-stream")
    store = FileSystemArtifactStore(tmp_path / "metered")
    meter = SealingMeter(None, governed=False)
    reference = store.put(data, media_type="application/octet-stream", io_meter=meter)
    assert (reference.content_digest, reference.size_bytes, reference.media_type) == (
        plain.content_digest, plain.size_bytes, plain.media_type,
    )
    assert store.read(reference) == data
    snapshot = meter.snapshot()
    assert snapshot.write_bytes == len(data) and snapshot.reader("store") == len(data)
    assert snapshot.read_calls == _calls(len(data))
    assert (snapshot.opens, snapshot.fsyncs) == (3, 2), "mkstemp, directory sync, readback"
    assert _temporaries(store) == []


def test_collision_reads_both_objects_then_reads_back_for_three_s(tmp_path: Path) -> None:
    data = b"z" * (2 * CHUNK + 1)
    store = FileSystemArtifactStore(tmp_path / "store")
    first = store.put(data)
    meter = SealingMeter(None, governed=False)
    second = store.put(data, io_meter=meter)
    assert second.content_digest == first.content_digest
    snapshot = meter.snapshot()
    assert snapshot.reader("store") == 3 * len(data)
    assert snapshot.read_calls == 3 * _calls(len(data))
    assert (snapshot.opens, snapshot.fsyncs) == (4, 1), "collision path never syncs the directory"
    assert _temporaries(store) == []


def test_collision_with_different_bytes_is_refused_and_the_temporary_removed(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    data = b"stored bytes"
    reference = store.put(data)
    target = store.object_path(reference)
    target.chmod(0o600)
    target.write_bytes(b"forged bytes")
    meter = SealingMeter(None, governed=False)
    with pytest.raises(ArtifactIntegrityError, match="digest does not match reference"):
        store.put(data, io_meter=meter)
    assert _temporaries(store) == []


def test_write_refusal_happens_before_the_chunk_and_never_leaves_a_temporary(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    before = open_descriptor_count()
    meter = SealingMeter(SealingBudget(max_write_bytes=5), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="write_bytes"):
        store.put(iter([b"abc", b"def"]), io_meter=meter)
    assert meter.snapshot().write_bytes == 3
    assert _temporaries(store) == [] and os.listdir(store.root / "objects") == []
    assert open_descriptor_count() == before


@pytest.mark.parametrize(("opens", "installed"), [(0, False), (1, True), (2, True)])
def test_open_refusals_at_each_step_keep_incumbent_custody(tmp_path: Path, opens: int, installed: bool) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    before = open_descriptor_count()
    meter = SealingMeter(SealingBudget(max_opens=opens), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="opens"):
        store.put(b"payload", io_meter=meter)
    # A refusal after installation leaves the object under store custody: no
    # deletion and no claim that it was durably synchronized or verified.
    assert bool(os.listdir(store.root / "objects")) is installed
    assert _temporaries(store) == [] and open_descriptor_count() == before


def test_readback_refuses_before_opening_when_the_body_cannot_fit(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    meter = SealingMeter(SealingBudget(max_read_bytes=6), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        store.put(b"payload", io_meter=meter)
    assert meter.snapshot().opens == 2 and meter.snapshot().read_calls == 0


def test_exact_readback_headroom_is_size_plus_one(tmp_path: Path) -> None:
    for budget, ok in ((8, True), (7, False)):
        store = FileSystemArtifactStore(tmp_path / f"store-{budget}")
        meter = SealingMeter(SealingBudget(max_read_bytes=budget), governed=True)
        if ok:
            store.put(b"payload", io_meter=meter)
            assert meter.snapshot().read_bytes == 7
        else:
            with pytest.raises(SealingBudgetExceeded):
                store.put(b"payload", io_meter=meter)


def test_directory_fsync_counts_one_open_and_one_fsync_and_maps_failures(tmp_path: Path, monkeypatch) -> None:
    meter = SealingMeter(None, governed=False)
    store_metered.metered_fsync_directory(tmp_path, meter)
    assert (meter.snapshot().opens, meter.snapshot().fsyncs) == (1, 1)
    with pytest.raises(ArtifactIntegrityError, match="durability failed"):
        store_metered.metered_fsync_directory(tmp_path / "missing", meter)
    assert meter.snapshot().opens == 2, "an admitted failed open still counts"

    def failing_fsync(descriptor: int) -> None:
        raise OSError(5, "input/output error")

    monkeypatch.setattr(store_metered.os, "fsync", failing_fsync)
    before = open_descriptor_count()
    with pytest.raises(ArtifactIntegrityError, match="durability failed"):
        store_metered.metered_fsync_directory(tmp_path, meter)
    assert open_descriptor_count() == before


def test_compare_closes_the_stored_descriptor_when_the_temporary_cannot_open(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"same")
    target = store.object_path(reference)
    meter = SealingMeter(None, governed=False)
    before = open_descriptor_count()
    with pytest.raises(ArtifactIntegrityError, match="artifact read failed"):
        store_metered.metered_compare_collision(
            target, tmp_path / "missing-temporary", 4, reference.content_digest,
            owner_uid=os.getuid(),
            private_details_fn=lambda path, *, owner_uid: os.lstat(path), meter=meter,
        )
    assert open_descriptor_count() == before and meter.snapshot().opens == 2


def test_verify_maps_size_digest_bound_and_version_failures(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"abcdef")
    path = store.object_path(reference)
    def details(item: Path, *, owner_uid: int) -> os.stat_result:
        return os.lstat(item)

    digest = "sha256:" + hashlib.sha256(b"abcdef").hexdigest()
    meter = SealingMeter(None, governed=False)

    def verify(**overrides: object) -> None:
        arguments: dict[str, Any] = dict(
            digest=digest, length=6, bound=6, expected_version=None, owner_uid=os.getuid(),
            private_details_fn=details, meter=meter,
        )
        arguments.update(overrides)
        store_metered.metered_verify_path(path, **arguments)

    verify()
    with pytest.raises(ArtifactIntegrityError, match="bounds exceeded"):
        verify(bound=5)
    with pytest.raises(ArtifactIntegrityError, match="size does not match"):
        verify(length=5, bound=6)
    with pytest.raises(ArtifactIntegrityError, match="size does not match"):
        verify(length=7, bound=7)
    with pytest.raises(ArtifactIntegrityError, match="digest does not match"):
        verify(digest="sha256:" + "0" * 64)
    with pytest.raises(ArtifactIntegrityError, match="version is stale"):
        verify(expected_version="fs-0-0-0-0")
    with pytest.raises(ArtifactIntegrityError, match="not a regular file"):
        store_metered.metered_verify_path(
            tmp_path / "absent", digest=digest, length=6, bound=6, expected_version=None,
            owner_uid=os.getuid(), private_details_fn=lambda item, *, owner_uid: os.lstat(path),
            meter=meter,
        )


def test_default_put_never_touches_the_metered_module(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("default put used the metered path")

    monkeypatch.setattr(store_metered, "metered_put", forbidden)
    store = FileSystemArtifactStore(tmp_path / "store")
    assert store.read(store.put(b"default")) == b"default"
