"""Filesystem portability, sealing refusal and store integrity custody."""


from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import common_lore_index.artifacts._source_sealing_io as source_io
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._source_sealing_io import (
    SourceUnsealableError,
    open_source_body,
)
from common_lore_index.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from repomap_test_support.sealing_governance_fixtures import open_descriptor_count


def _metadata(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _objects(store: FileSystemArtifactStore) -> tuple[str, ...]:
    return tuple(sorted(path.name for path in (store.root / "objects").iterdir()))


def _stream(
    root: Path, relative: str, size: int, digest: str, meter: SealingMeter,
):
    with open_source_body(
        root,
        relative,
        expected_size=size,
        expected_digest=digest,
        expected_executable=False,
        io_meter=meter,
    ) as body:
        yield from body


def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # This is the only capability patch: it selects the supported
    # portability route and does not replace os.open/read/stat or the subject.
    monkeypatch.setattr(source_io, "_supports_dir_fd", lambda: False)


def test_stable_nested_fallback_source_streams_into_real_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_fallback(monkeypatch)
    root = tmp_path / "source"
    nested = root / "package" / "inner"
    nested.mkdir(parents=True)
    path = nested / "module.py"
    payload = b"VALUE = 1\n"
    path.write_bytes(payload)
    size, digest = _metadata(path)
    store = FileSystemArtifactStore(tmp_path / "store")
    before = open_descriptor_count()
    meter = SealingMeter(None, governed=False)

    reference = store.put(
        _stream(root, "package/inner/module.py", size, digest, meter),
        io_meter=meter,
    )

    assert reference.size_bytes == len(payload)
    assert store.read(reference) == payload
    assert not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == before


@pytest.mark.parametrize("relative", ("", "package/../module.py", "package//module.py"))
def test_fallback_rejects_invalid_relative_path_without_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str,
) -> None:
    _force_fallback(monkeypatch)
    root = tmp_path / "source"
    root.mkdir()
    before = open_descriptor_count()
    with pytest.raises(SourceUnsealableError, match="source inventory is not sealable"):
        with open_source_body(
            root,
            relative,
            expected_size=0,
            expected_digest=hashlib.sha256(b"").hexdigest(),
            expected_executable=False,
        ):
            raise AssertionError("invalid path was admitted")
    assert open_descriptor_count() == before


def test_fallback_context_refuses_an_unconsumed_body_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_fallback(monkeypatch)
    root = tmp_path / "source"
    nested = root / "package"
    nested.mkdir(parents=True)
    path = nested / "module.py"
    path.write_bytes(b"VALUE = 4\n")
    size, digest = _metadata(path)
    before = open_descriptor_count()

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            root,
            "package/module.py",
            expected_size=size,
            expected_digest=digest,
            expected_executable=False,
        ):
            pass
    assert open_descriptor_count() == before


@pytest.mark.parametrize("mutation", ("disappeared", "parent-replaced", "truncated"))
def test_fallback_path_or_parent_replacement_is_detected_at_eof_and_keeps_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    _force_fallback(monkeypatch)
    root = tmp_path / "source"
    parent = root / "package"
    parent.mkdir(parents=True)
    path = parent / "module.py"
    payload = b"VALUE = 2\n"
    path.write_bytes(payload)
    size, digest = _metadata(path)
    store = FileSystemArtifactStore(tmp_path / "store")
    incumbent = store.put(b"incumbent")
    before = open_descriptor_count()
    meter = SealingMeter(None, governed=False)

    with pytest.raises(ValueError, match="source changed while sealing"):
        with open_source_body(
            root,
            "package/module.py",
            expected_size=size,
            expected_digest=digest,
            expected_executable=False,
            io_meter=meter,
        ) as body:
            if mutation == "disappeared":
                path.unlink()
            elif mutation == "truncated":
                # The opened inode remains owned by the body, but its next real
                # read returns EOF before the declared size (211->217).
                path.write_bytes(b"")
            else:
                parent.rename(root / "package-old")
                parent.mkdir()
                (parent / "module.py").write_bytes(payload)
            store.put(body, io_meter=meter)

    assert store.read(incumbent) == b"incumbent"
    assert _objects(store) == (incumbent.content_digest.removeprefix("sha256:"),)
    assert not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("symlink", "non-directory", "hardlink"))
def test_fallback_inventory_refusals_preserve_incumbent_and_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    _force_fallback(monkeypatch)
    root = tmp_path / "source"
    root.mkdir()
    payload = b"VALUE = 3\n"
    target = root / "module.py"
    relative = "module.py"
    if kind == "symlink":
        real = root / "real.py"
        real.write_bytes(payload)
        target.symlink_to(real)
    elif kind == "non-directory":
        target = root / "package"
        target.write_bytes(payload)
        relative = "package/module.py"
    else:
        target.write_bytes(payload)
        os.link(target, root / "module-alias.py")
        target = root / "module-alias.py"
        relative = target.name
    size, digest = len(payload), hashlib.sha256(payload).hexdigest()
    store = FileSystemArtifactStore(tmp_path / "store")
    incumbent = store.put(b"incumbent")
    before = open_descriptor_count()
    meter = SealingMeter(None, governed=False)

    with pytest.raises(SourceUnsealableError, match="source inventory is not sealable"):
        store.put(_stream(root, relative, size, digest, meter), io_meter=meter)

    assert store.read(incumbent) == b"incumbent"
    assert _objects(store) == (incumbent.content_digest.removeprefix("sha256:"),)
    assert not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == before


@pytest.mark.parametrize("fault", ("bound", "digest", "collision"))
def test_metered_file_integrity_refusals_preserve_existing_objects(tmp_path: Path, fault: str) -> None:
    from common_lore_index.artifacts import _store_metered as metered
    from common_lore_index.artifacts._store_filesystem import _private_details

    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"accepted")
    target = store.object_path(reference)
    before, descriptors = _objects(store), open_descriptor_count()
    meter = SealingMeter(None, governed=False)
    temporary = tmp_path / "candidate"
    if fault == "collision":
        temporary.write_bytes(b"rejected")
        temporary.chmod(0o600)
        with pytest.raises(ArtifactIntegrityError, match="content-address collision"):
            metered.metered_compare_collision(target, temporary, reference.size_bytes,
                reference.content_digest, owner_uid=os.getuid(), private_details_fn=_private_details,
                meter=meter)
        assert temporary.read_bytes() == b"rejected"
    else:
        with pytest.raises(ArtifactIntegrityError, match="bounds exceeded" if fault == "bound" else "digest does not match"):
            metered.metered_verify_path(target,
                digest="sha256:" + "0" * 64 if fault == "digest" else reference.content_digest,
                length=reference.size_bytes, bound=1 if fault == "bound" else reference.size_bytes,
                expected_version=None, owner_uid=os.getuid(), private_details_fn=_private_details,
                meter=meter)
    assert store.read(reference) == b"accepted"
    assert _objects(store) == before and not list((store.root / "temporary").iterdir())
    assert open_descriptor_count() == descriptors
