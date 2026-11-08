"""Read-only filesystem-store admission does not create directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from common_lore_index.artifacts import ArtifactIntegrityError, FileSystemArtifactStore


def test_create_false_admits_existing_private_store_without_temporary_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "objects"
    root.mkdir(mode=0o700)
    (root / "objects").mkdir(mode=0o700)
    store = FileSystemArtifactStore(root, create=False)

    assert store.root == root.absolute()
    assert not (root / "temporary").exists()


def test_create_false_does_not_materialize_missing_store(tmp_path: Path) -> None:
    root = tmp_path / "missing"

    with pytest.raises(ArtifactIntegrityError, match="store root"):
        FileSystemArtifactStore(root, create=False)
    assert not root.exists()
