"""Store temporary cleanup preserves the producer's primary error."""
from __future__ import annotations

from pathlib import Path
import os
from typing import BinaryIO

import pytest

from common_lore_index.artifacts._bundle_cancellation import BundleEncodingCancelled
from common_lore_index.artifacts.store import ArtifactErrorCode, ArtifactIntegrityError, FileSystemArtifactStore
from common_lore_index.artifacts import _store_filesystem as filesystem
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


@pytest.mark.parametrize("primary", [BundleEncodingCancelled(), ValueError("cancelled"), RuntimeError("producer failure")])
def test_failed_temporary_unlink_preserves_the_actual_producer_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: Exception,
) -> None:
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(root)
    original_unlink = Path.unlink
    paths: list[Path] = []

    def refuse(path, *args, **kwargs):
        if path.name.startswith(".artifact-"):
            paths.append(path)
            raise OSError("synthetic temporary unlink refusal")
        return original_unlink(path, *args, **kwargs)

    def chunks():
        yield b"public prefix"
        raise primary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", refuse)
            with pytest.raises(type(primary)) as caught:
                store.put(chunks(), media_type="application/octet-stream", record_format="raw-v1", privacy=PrivacyClassification.RAW_SOURCE)
        assert caught.value is primary
        assert len(paths) == 1
    finally:
        for path in paths:
            original_unlink(path, missing_ok=True)


def test_unaccompanied_temporary_cleanup_failure_retains_write_failed_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(root)
    store.put(b"public", media_type="application/octet-stream", record_format="raw-v1", privacy=PrivacyClassification.RAW_SOURCE)
    original_unlink = Path.unlink
    paths: list[Path] = []

    def refuse(path, *args, **kwargs):
        if path.name.startswith(".artifact-"):
            paths.append(path)
            raise OSError("synthetic temporary unlink refusal")
        return original_unlink(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", refuse)
            with pytest.raises(ArtifactIntegrityError) as caught:
                store.put(b"public", media_type="application/octet-stream", record_format="raw-v1", privacy=PrivacyClassification.RAW_SOURCE)
        assert caught.value.code == ArtifactErrorCode.WRITE_FAILED
        assert len(paths) == 1
    finally:
        for path in paths:
            original_unlink(path, missing_ok=True)


def test_handled_caller_error_does_not_hide_a_new_cleanup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common_lore_index.artifacts._store_temporary import remove_temporary

    marker = tmp_path / "temporary"
    marker.write_bytes(b"owned")
    original_unlink = Path.unlink

    def refuse(path, *args, **kwargs):
        if path == marker:
            raise OSError("synthetic unlink refusal")
        return original_unlink(path, *args, **kwargs)

    try:
        raise ValueError("already handled caller error")
    except ValueError:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", refuse)
            with pytest.raises(ArtifactIntegrityError) as caught:
                remove_temporary(marker)
        assert caught.value.code == ArtifactErrorCode.WRITE_FAILED
    finally:
        original_unlink(marker, missing_ok=True)


def test_put_permission_failure_closes_its_exact_temporary_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(root)
    original_mkstemp = filesystem.tempfile.mkstemp
    original_fchmod = os.fchmod
    allocated: list[tuple[int, Path, os.stat_result]] = []
    primary = PermissionError("synthetic permission refusal")

    def allocate(**kwargs):
        descriptor, name = original_mkstemp(**kwargs)
        allocated.append((descriptor, Path(name), os.fstat(descriptor)))
        return descriptor, name

    def chmod(descriptor, mode):
        if allocated and descriptor == allocated[0][0]:
            raise primary
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(filesystem.tempfile, "mkstemp", allocate)
    monkeypatch.setattr(os, "fchmod", chmod)
    leaked = False
    try:
        with pytest.raises(ArtifactIntegrityError) as caught:
            store.put(b"public", media_type="application/octet-stream", record_format="raw-v1", privacy=PrivacyClassification.RAW_SOURCE)
        assert caught.value.code == ArtifactErrorCode.PERMISSION_DENIED
        assert caught.value.__cause__ is primary
        assert len(allocated) == 1
        descriptor, path, identity = allocated[0]
        try:
            current = os.fstat(descriptor)
            leaked = (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino)
        except OSError:
            pass
        assert not path.exists()
    finally:
        if leaked:
            os.close(allocated[0][0])
    assert not leaked


def test_stream_constructor_failure_closes_the_raw_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(root)
    reference = store.put(b"public", media_type="application/octet-stream", record_format="raw-v1", privacy=PrivacyClassification.RAW_SOURCE)
    primary = RuntimeError("synthetic stream constructor refusal")
    acquired: list[BinaryIO] = []

    def refuse(raw, **_kwargs):
        acquired.append(raw)
        raise primary

    monkeypatch.setattr(filesystem, "VerifyingArtifactStream", refuse)
    try:
        with pytest.raises(RuntimeError) as caught:
            store.open_stream(reference)
        assert caught.value is primary
        assert len(acquired) == 1
        closed = acquired[0].closed
    finally:
        for handle in acquired:
            try:
                handle.close()
            except OSError:
                pass
    assert closed
