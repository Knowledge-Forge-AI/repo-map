"""W7 real-filesystem sealing and store refusal contracts.

Each scenario uses the public sealing fixture and/or the real private
filesystem store. The mutations are performed on temporary files, never by
replacing the sealing or storage subject with a fake implementation.
"""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._source_sealing_io import open_source_body
import common_lore_index.artifacts._store_metered as store_metered
from common_lore_index.artifacts._store_filesystem import _private_details
from common_lore_index.artifacts.sealing_governance import (
    SealingBudget,
    SealingBudgetExceeded,
)
from common_lore_index.artifacts.store import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
)
from repomap_test_support.sealing_governance_fixtures import (
    binding_for,
    graph_for,
    open_descriptor_count,
    seal,
    write_tree,
)


def _object_names(store: FileSystemArtifactStore) -> tuple[str, ...]:
    return tuple(sorted(path.name for path in (store.root / "objects").iterdir()))


def test_elapsed_budget_refusal_keeps_prior_store_objects_and_resources(
    tmp_path: Path,
) -> None:
    source = write_tree(tmp_path / "source", {"main.py": b"VALUE = 1\n"})
    graph = graph_for(binding_for("entry", source))
    store_root = tmp_path / "store"
    store = FileSystemArtifactStore(store_root)
    accepted = store.put(b"accepted before refusal")
    before_objects = _object_names(store)
    before_fds = open_descriptor_count()
    meter = SealingMeter(SealingBudget(max_elapsed_ms=0), governed=True)

    with pytest.raises(SealingBudgetExceeded, match="elapsed_ms"):
        seal(graph, store_root, io_meter=meter)

    snapshot = meter.snapshot()
    assert snapshot.refused_limit == "elapsed_ms"
    assert snapshot.opens == 0
    assert _object_names(store) == before_objects
    assert store.read(accepted) == b"accepted before refusal"
    assert tuple((store.root / "temporary").iterdir()) == ()
    assert open_descriptor_count() == before_fds


def test_write_budget_refusal_after_body_install_preserves_accepted_state(
    tmp_path: Path,
) -> None:
    payload = b"accepted source body\n"
    source = write_tree(tmp_path / "source", {"main.py": payload})
    graph = graph_for(binding_for("entry", source))
    store_root = tmp_path / "store"
    store = FileSystemArtifactStore(store_root)
    accepted = store.put(b"incumbent artifact")
    before_fds = open_descriptor_count()
    meter = SealingMeter(
        SealingBudget(max_read_bytes=10**9, max_write_bytes=len(payload)),
        governed=True,
    )

    # The body object fits the write budget. The later manifest object must be
    # refused before its first write, leaving the already accepted body and
    # incumbent object in custody.
    with pytest.raises(SealingBudgetExceeded, match="write_bytes"):
        seal(graph, store_root, io_meter=meter)

    snapshot = meter.snapshot()
    assert snapshot.refused_limit == "write_bytes"
    assert snapshot.write_bytes == len(payload)
    assert store.read(accepted) == b"incumbent artifact"
    assert len(_object_names(store)) == 2
    assert tuple((store.root / "temporary").iterdir()) == ()
    assert open_descriptor_count() == before_fds


def test_stream_growth_after_open_is_refused_by_the_declared_bound(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"abc")
    target = store.object_path(reference)
    stream = store.open_stream(reference, max_bytes=reference.size_bytes)
    try:
        with target.open("ab") as changed:
            changed.write(b"x")
        with pytest.raises(ArtifactIntegrityError, match="bounds exceeded"):
            stream.read(-1)
    finally:
        stream.close()


def test_stream_metadata_change_is_detected_at_eof_without_path_replacement(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"stable")
    target = store.object_path(reference)
    stream = store.open_stream(reference)
    try:
        target.chmod(0o400)
        with pytest.raises(ArtifactIntegrityError, match="changed during read"):
            stream.read(-1)
    finally:
        # Restore the owner-private mode before the temporary store is torn
        # down so no later cleanup operation observes an unsafe object.
        target.chmod(0o600)
        stream.close()


def test_source_read_error_cleans_store_temporary_and_keeps_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.py"
    content = b"source body"
    source.write_bytes(content)
    store = FileSystemArtifactStore(tmp_path / "store")
    accepted = store.put(b"incumbent")
    descriptor: int | None = None
    original_read = os.read

    def failing_read(fd: int, length: int) -> bytes:
        if fd == descriptor:
            raise OSError(errno.EIO, "source read failed")
        return original_read(fd, length)

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            source.parent,
            source.name,
            expected_size=len(content),
            expected_digest=hashlib.sha256(content).hexdigest(),
            expected_executable=False,
        ) as body:
            descriptor = body._descriptor
            monkeypatch.setattr(os, "read", failing_read)
            store.put(body, content_digest="sha256:" + hashlib.sha256(content).hexdigest())

    monkeypatch.undo()  # End the FD fault before the number can be reused.
    assert store.read(accepted) == b"incumbent"
    assert tuple((store.root / "temporary").iterdir()) == ()


def test_metered_put_invalid_content_keeps_incumbent_and_cleans_temporary(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    accepted = store.put(b"incumbent")
    meter = SealingMeter(None, governed=False)

    with pytest.raises(ArtifactIntegrityError, match="must be bytes or iterable"):
        store.put(cast(Any, 123), io_meter=meter)

    assert store.read(accepted) == b"incumbent"
    assert tuple((store.root / "temporary").iterdir()) == ()


def test_metered_put_fsync_failure_keeps_incumbent_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    accepted = store.put(b"incumbent")

    def failing_fsync(_descriptor: int) -> None:
        raise OSError(errno.EIO, "fsync failed")

    monkeypatch.setattr(store_metered.os, "fsync", failing_fsync)
    with pytest.raises(ArtifactIntegrityError, match="publication failed"):
        store.put(b"new body", io_meter=SealingMeter(None, governed=False))

    assert store.read(accepted) == b"incumbent"
    assert tuple((store.root / "temporary").iterdir()) == ()


@pytest.mark.parametrize(
    ("bound", "message"),
    ((3, "bounds exceeded"), (4, "size does not match")),
)
def test_metered_verify_growth_refuses_bound_or_declared_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: int,
    message: str,
) -> None:
    store = FileSystemArtifactStore(tmp_path / f"store-{bound}")
    reference = store.put(b"abc")
    target = store.object_path(reference)
    real_read = store_metered.metered_read

    def grow_after_first_read(meter, reader, descriptor, length):
        data = real_read(meter, reader, descriptor, length)
        if target.stat().st_size == 3:
            with target.open("ab") as changed:
                changed.write(b"x")
        return data

    monkeypatch.setattr(store_metered, "metered_read", grow_after_first_read)
    with pytest.raises(ArtifactIntegrityError, match=message):
        store_metered.metered_verify_path(
            target,
            digest=reference.content_digest,
            length=3,
            bound=bound,
            expected_version=None,
            owner_uid=os.getuid(),
            private_details_fn=_private_details,
            meter=SealingMeter(None, governed=False),
        )


def test_metered_verify_detects_post_open_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"abc")
    target = store.object_path(reference)
    opened: list[int] = []
    real_open = store_metered.metered_open
    real_fstat = store_metered.os.fstat

    def recording_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def changed_fstat(descriptor: int):
        details = real_fstat(descriptor)
        if opened and descriptor == opened[0]:
            target.chmod(0o400)
            return real_fstat(descriptor)
        return details

    monkeypatch.setattr(store_metered, "metered_open", recording_open)
    monkeypatch.setattr(store_metered.os, "fstat", changed_fstat)
    try:
        with pytest.raises(ArtifactIntegrityError, match="changed during read"):
            store_metered.metered_verify_path(
                target,
                digest=reference.content_digest,
                length=reference.size_bytes,
                bound=reference.size_bytes,
                expected_version=None,
                owner_uid=os.getuid(),
                private_details_fn=_private_details,
                meter=SealingMeter(None, governed=False),
            )
    finally:
        target.chmod(0o600)


def test_metered_verify_detects_post_read_metadata_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"abc")
    target = store.object_path(reference)
    opened: list[int] = []
    fstats = 0
    real_open = store_metered.metered_open
    real_fstat = store_metered.os.fstat

    def recording_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def changed_after_open(descriptor: int):
        nonlocal fstats
        details = real_fstat(descriptor)
        if opened and descriptor == opened[0]:
            fstats += 1
            if fstats == 1:
                target.chmod(0o400)
        return details

    monkeypatch.setattr(store_metered, "metered_open", recording_open)
    monkeypatch.setattr(store_metered.os, "fstat", changed_after_open)
    try:
        with pytest.raises(ArtifactIntegrityError, match="changed during read"):
            store_metered.metered_verify_path(
                target,
                digest=reference.content_digest,
                length=reference.size_bytes,
                bound=reference.size_bytes,
                expected_version=None,
                owner_uid=os.getuid(),
                private_details_fn=_private_details,
                meter=SealingMeter(None, governed=False),
            )
    finally:
        target.chmod(0o600)


def test_metered_verify_reports_declared_length_and_stale_version(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"abc")
    target = store.object_path(reference)

    with pytest.raises(ArtifactIntegrityError, match="size does not match"):
        store_metered.metered_verify_path(
            target,
            digest=reference.content_digest,
            length=4,
            bound=4,
            expected_version=None,
            owner_uid=os.getuid(),
            private_details_fn=_private_details,
            meter=SealingMeter(None, governed=False),
        )
    with pytest.raises(ArtifactIntegrityError, match="version is stale"):
        store_metered.metered_verify_path(
            target,
            digest=reference.content_digest,
            length=reference.size_bytes,
            bound=reference.size_bytes,
            expected_version="fs-stale",
            owner_uid=os.getuid(),
            private_details_fn=_private_details,
            meter=SealingMeter(None, governed=False),
        )
