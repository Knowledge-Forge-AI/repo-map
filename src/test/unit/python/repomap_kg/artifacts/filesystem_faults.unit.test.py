"""Filesystem artifact error causality and durability contracts."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from repomap_kg.artifacts import _store_filesystem as filesystem
from repomap_kg.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore


@pytest.mark.parametrize("boundary", ["open", "fsync"])
def test_directory_durability_error_preserves_cause_and_closes_descriptor(
    tmp_path: Path, boundary: str,
) -> None:
    failure = OSError("injected directory durability failure")
    real_close = os.close
    with mock.patch.object(filesystem.os, boundary, side_effect=failure):
        with mock.patch.object(filesystem.os, "close", wraps=real_close) as close:
            with pytest.raises(ArtifactIntegrityError, match="directory durability") as caught:
                filesystem._fsync_directory(tmp_path)
    assert caught.value.__cause__ is failure
    assert close.call_count == (1 if boundary == "fsync" else 0)


@pytest.mark.parametrize("failure", [PermissionError("injected refusal"), OSError("injected write failure")])
def test_publication_replace_failure_removes_temporary_and_preserves_prior_object(
    tmp_path: Path, failure: OSError,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    previous = store.put(b"accepted")
    before = tuple(store._objects.iterdir())
    with mock.patch.object(filesystem.os, "replace", side_effect=failure):
        with pytest.raises(ArtifactIntegrityError, match="publication failed") as caught:
            store.put(b"new candidate")
    assert caught.value.__cause__ is failure
    expected = "permission_denied" if isinstance(failure, PermissionError) else "write_failed"
    assert caught.value.code.value == expected
    assert tuple(store._objects.iterdir()) == before
    assert tuple(store._temporary.iterdir()) == ()
    assert store.read(previous) == b"accepted"


def test_descriptor_identity_change_refuses_read_and_closes_descriptor(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    reference = store.put(b"accepted")
    with mock.patch.object(filesystem, "_same_file", return_value=False):
        with mock.patch.object(filesystem.os, "fstat", wraps=os.fstat) as inspected:
            with pytest.raises(ArtifactIntegrityError, match="changed during read"):
                store.read(reference)
    descriptor = inspected.call_args.args[0]
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert store.read(reference) == b"accepted"
