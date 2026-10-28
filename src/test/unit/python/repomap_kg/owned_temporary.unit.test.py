"""Owned scratch cleanup preserves the portable worker's existing authority boundary."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

from repomap_kg._temporary import OwnedTemporaryDirectory
from repomap_kg.coordinator import _portable_authority as authority


def test_context_cleans_nested_readonly_files_and_is_idempotent(tmp_path):
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    with owner as name:
        root = Path(name)
        child = root / 'nested'; child.mkdir()
        (child / 'input').write_bytes(b'public fixture')
        (child / 'input').chmod(0o400)
        assert root.stat().st_mode & 0o777 == 0o700
    assert not root.exists()
    owner.cleanup()


def test_body_exception_propagates_after_owned_cleanup(tmp_path):
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    with pytest.raises(ValueError, match='body failed'):
        with owner as name:
            (Path(name) / 'input').write_bytes(b'data')
            raise ValueError('body failed')
    assert not Path(owner.name).exists()


def test_finalizer_cleans_an_abandoned_owned_directory(tmp_path):
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    root = Path(owner.name); (root / 'input').write_bytes(b'data')
    del owner
    gc.collect()
    assert not root.exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_unexpected_nodes_refuse_without_touching_foreign_data(tmp_path, kind):
    if kind == 'fifo' and not hasattr(os, 'mkfifo'):
        pytest.skip('FIFO creation is unavailable on this platform')
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    root = Path(owner.name)
    foreign = tmp_path / 'foreign'; foreign.write_bytes(b'preserve')
    target = root / 'unexpected'
    if kind == 'symlink':
        target.symlink_to(foreign)
    elif kind == 'hardlink':
        os.link(foreign, target)
    else:
        os.mkfifo(target)
    try:
        with pytest.raises(RuntimeError, match='unexpected node'):
            owner.cleanup()
        assert foreign.read_bytes() == b'preserve' and target.lstat()
    finally:
        target.unlink()
        owner.cleanup()


def test_replaced_root_refuses_and_preserves_both_directories(tmp_path):
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    root = Path(owner.name); moved = tmp_path / 'retained'
    (root / 'original').write_bytes(b'owned')
    root.rename(moved); root.mkdir()
    (root / 'foreign').write_bytes(b'preserve')
    try:
        with pytest.raises(RuntimeError, match='root identity changed'):
            owner.cleanup()
        assert (moved / 'original').read_bytes() == b'owned'
        assert (root / 'foreign').read_bytes() == b'preserve'
    finally:
        (root / 'foreign').unlink(); root.rmdir(); moved.rename(root)
        owner.cleanup()


def test_removed_root_is_already_clean(tmp_path):
    owner = OwnedTemporaryDirectory(prefix='owned-', dir=str(tmp_path))
    Path(owner.name).rmdir()
    owner.cleanup()


def test_descriptor_mutations_are_still_refused_even_inside_write_root(tmp_path):
    if not hasattr(os, 'O_DIRECTORY'):
        pytest.skip('directory descriptors are unavailable on this platform')
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for event in ('os.remove', 'os.rmdir'):
            with pytest.raises(PermissionError, match='filesystem authority denied'):
                authority._validate_audit_event(event, ('file', descriptor), (tmp_path,), (tmp_path,))
    finally:
        os.close(descriptor)
