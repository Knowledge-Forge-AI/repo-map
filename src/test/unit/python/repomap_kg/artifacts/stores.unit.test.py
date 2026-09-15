from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
from typing import cast

import pytest

from repomap_kg.artifacts import (
    ArtifactIntegrityError,
    ArtifactReference,
    FileSystemArtifactStore,
    MemoryArtifactStore,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def put(store: FileSystemArtifactStore | MemoryArtifactStore, content: bytes = b"abc"):
    return store.put(
        content,
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )


def test_filesystem_and_fake_store_have_semantic_reference_parity(
    tmp_path: Path,
) -> None:
    filesystem = FileSystemArtifactStore(tmp_path / "store")
    memory = MemoryArtifactStore()

    filesystem_ref = put(filesystem)
    memory_ref = put(memory)

    assert filesystem_ref.semantic_mapping() == memory_ref.semantic_mapping()
    assert filesystem.read(filesystem_ref) == memory.read(memory_ref) == b"abc"
    assert filesystem_ref.locator != memory_ref.locator


def test_filesystem_store_is_private_atomic_and_cleans_temporary_material(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store)

    assert (store.root.stat().st_mode & 0o077) == 0
    assert store.read(ref) == b"abc"
    assert not tuple(store.root.rglob("*.tmp"))


def test_stale_missing_swapped_truncated_and_oversized_objects_fail_closed(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store)
    path = store.object_path(ref)

    path.write_bytes(b"ab")
    with pytest.raises(ArtifactIntegrityError, match="size"):
        store.read(ref)

    path.write_bytes(b"xyz")
    with pytest.raises(ArtifactIntegrityError, match="digest"):
        store.read(ref)

    path.unlink()
    with pytest.raises(ArtifactIntegrityError, match="missing"):
        store.read(ref)

    ref = put(store, b"abc")
    with pytest.raises(ArtifactIntegrityError, match="bounds"):
        store.read(ref, max_bytes=2)


def test_memory_store_models_exact_immutable_object_versions() -> None:
    store = MemoryArtifactStore()
    ref1 = put(store)
    assert ref1.store_version == "object-v1"

    store.delete(ref1)
    ref2 = put(store)
    assert ref2.store_version == "object-v2"

    with pytest.raises(ArtifactIntegrityError, match="stale"):
        store.read(ref1)
    assert store.read(ref2) == b"abc"


def test_filesystem_store_rejects_symlink_hardlink_and_special_file(
    tmp_path: Path,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store)
    path = store.object_path(ref)
    original = path.read_bytes()

    path.unlink()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        store.read(ref)

    path.unlink()
    path.write_bytes(original)
    hardlink = tmp_path / "hardlink"
    os.link(path, hardlink)
    with pytest.raises(ArtifactIntegrityError, match="link count"):
        store.read(ref)

    hardlink.unlink()
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        store.read(ref)


@pytest.mark.parametrize("bound", [-1, True])
def test_store_rejects_invalid_object_bounds(bound: int) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        MemoryArtifactStore().put(b"x", max_bytes=bound)


@pytest.mark.parametrize("content", ["text", 123, [object()]])
def test_store_rejects_non_byte_content(content: object) -> None:
    with pytest.raises(TypeError, match="artifact content"):
        MemoryArtifactStore().put(cast(bytes, content))


def test_iterable_content_is_materialized_exactly_and_bounded() -> None:
    store = MemoryArtifactStore()
    empty = store.put([b""])
    joined = store.put([b"a", bytes(b"bc")])

    assert store.read(empty) == b""
    assert store.read(joined) == b"abc"
    with pytest.raises(ArtifactIntegrityError, match="bounds") as error:
        store.put([b"ab", b"c"], max_bytes=2)
    assert error.value.code.value == "artifact_bounds"


def test_requested_digest_is_validated_and_enforced() -> None:
    store = MemoryArtifactStore()
    digest = "sha256:" + hashlib.sha256(b"abc").hexdigest()

    with pytest.raises(ValueError, match="content digest"):
        store.put(b"abc", content_digest="sha256:short")
    with pytest.raises(ArtifactIntegrityError, match="supplied digest"):
        store.put(b"abc", content_digest="sha256:" + "0" * 64)
    assert store.put(b"abc", content_digest=digest).content_digest == digest


def test_memory_store_reuses_versions_and_fails_closed_on_invalid_reads() -> None:
    store = MemoryArtifactStore()
    ref = put(store)
    assert put(store).store_version == ref.store_version

    with pytest.raises(ArtifactIntegrityError, match="reference"):
        store.read(cast(ArtifactReference, object()))
    with pytest.raises(ArtifactIntegrityError, match="bounds"):
        store.read(ref, max_bytes=2)
    with pytest.raises(ArtifactIntegrityError, match="locator"):
        store.read(replace(ref, locator=replace(ref.locator, kind="filesystem")))
    assert store.delete(ref)
    assert not store.delete(ref)


def test_filesystem_store_rejects_unsafe_existing_directory(tmp_path: Path) -> None:
    root = tmp_path / "unsafe"
    root.mkdir(mode=0o755)

    with pytest.raises(ArtifactIntegrityError, match="store root is unsafe"):
        FileSystemArtifactStore(root)


def test_filesystem_delete_and_neutral_locator_are_supported(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store)
    neutral = replace(
        ref,
        locator=replace(
            ref.locator,
            kind="object",
            value=f"tenant-neutral/{ref.content_digest[7:]}",
        ),
    )

    assert neutral.locator.kind == "object"
    assert neutral.locator.value == f"tenant-neutral/{ref.content_digest[7:]}"
    assert store.read(neutral) == b"abc"
    assert store.delete(ref)


def test_filesystem_store_permissions_and_directory_hardening(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store)
    path = store.object_path(ref)

    path.chmod(0o644)
    with pytest.raises(ArtifactIntegrityError, match="permissions are unsafe"):
        store.read(ref)
    assert not store.verify(ref)

    path.chmod(0o600)
    assert store.verify(ref)

    (store.root / "objects").chmod(0o755)
    with pytest.raises(ArtifactIntegrityError, match="object directory is unsafe"):
        store.read(ref)

    (store.root / "objects").chmod(0o700)
    (store.root / "temporary").chmod(0o755)
    with pytest.raises(ArtifactIntegrityError, match="temporary directory is unsafe"):
        put(store, b"xyz")


def test_filesystem_store_idempotent_put_and_collision_detection(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref1 = put(store, b"immutable-content")
    path = store.object_path(ref1)
    stat1 = path.stat()

    ref2 = put(store, b"immutable-content")
    assert ref1 == ref2
    assert ref1.locator == ref2.locator
    stat2 = path.stat()
    assert (stat1.st_ino, stat1.st_mtime_ns) == (stat2.st_ino, stat2.st_mtime_ns)

    # Corrupting target file on disk causes integrity error on put
    path.write_bytes(b"corrupted-content")
    with pytest.raises(ArtifactIntegrityError, match="digest|bounds"):
        put(store, b"immutable-content")
    assert not tuple(store.root.rglob("*.tmp"))


def test_filesystem_and_memory_store_read_get_stream_verify_parity(tmp_path: Path) -> None:
    fs_store = FileSystemArtifactStore(tmp_path / "fs_store")
    mem_store = MemoryArtifactStore()
    for store in (fs_store, mem_store):
        ref = put(store, b"payload-bytes")
        assert store.get(ref) == b"payload-bytes"
        stream = store.open_stream(ref)
        assert stream.read() == b"payload-bytes"
        assert store.verify(ref)

        bad_ref = replace(ref, content_digest="sha256:" + "0" * 64)
        assert not store.verify(bad_ref)

        with pytest.raises(ArtifactIntegrityError, match="reference"):
            store.read(cast(ArtifactReference, "invalid-reference"))

    with pytest.raises(ArtifactIntegrityError, match="reference"):
        fs_store.delete(cast(ArtifactReference, "invalid-reference"))


def test_filesystem_store_locator_mismatch_and_stale_version(tmp_path: Path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = put(store, b"sample")

    wrong_fs = replace(ref, locator=replace(ref.locator, value="objects/0000000000000000000000000000000000000000000000000000000000000000"))
    with pytest.raises(ArtifactIntegrityError, match="locator does not address"):
        store.read(wrong_fs)

    wrong_neutral = replace(ref, locator=replace(ref.locator, kind="object", value="tenant-neutral/0000000000000000000000000000000000000000000000000000000000000000"))
    with pytest.raises(ArtifactIntegrityError, match="locator does not address"):
        store.read(wrong_neutral)

    stale = replace(ref, locator=replace(ref.locator, store_version="fs-1-2-3-4"))
    with pytest.raises(ArtifactIntegrityError, match="stale") as error:
        store.read(stale)
    assert error.value.code.value == "artifact_stale"


def test_memory_store_collision_missing_and_tampered_read() -> None:
    store = MemoryArtifactStore()
    ref = put(store, b"hello")

    key = store._locator(ref)
    obj = store._objects[key]
    store._objects[key] = replace(obj, content=b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="content-address collision"):
        put(store, b"hello")

    with pytest.raises(ArtifactIntegrityError, match="size does not match"):
        store.read(ref)

    store._objects[key] = replace(obj, content=b"12345")
    with pytest.raises(ArtifactIntegrityError, match="digest does not match"):
        store.read(ref)

    missing_ref = replace(ref, content_digest="sha256:" + "e" * 64, locator=replace(ref.locator, value="tenant-neutral/" + "e" * 64))
    with pytest.raises(ArtifactIntegrityError, match="missing artifact") as error:
        store.read(missing_ref)
    assert error.value.code.value == "artifact_missing"
    assert not store.delete(missing_ref)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("object", "bucket/data"),
        ("filesystem", "../escape"),
        ("filesystem", "foo/../bar"),
        ("filesystem", "./relative"),
        ("filesystem", "/absolute/path"),
        ("filesystem", "~/home/path"),
        ("filesystem", "C:/windows/path"),
        ("filesystem", "https://example.com"),
        ("filesystem", "has space"),
        ("filesystem", "has:colon"),
        ("filesystem", "has?query"),
        ("filesystem", "has#frag"),
        ("invalid-kind", "objects/normal"),
    ],
)
def test_artifact_locator_rejects_unsafe_constructs(kind: str, value: str) -> None:
    from repomap_kg.artifacts.references import ArtifactLocator

    message = "invalid locator kind" if kind == "invalid-kind" else "invalid locator"
    with pytest.raises(ValueError, match=f"^{message}$"):
        ArtifactLocator(kind, value)


def test_artifact_reference_semantics_contracts() -> None:
    from repomap_kg.artifacts.references import (
        ArtifactLocator,
        ArtifactReference,
        MAX_ARTIFACT_SIZE,
    )

    digest = "sha256:" + "c" * 64
    locator = ArtifactLocator("filesystem", f"objects/{'c' * 64}", "fs-1")
    ref = ArtifactReference(
        digest,
        10,
        "application/octet-stream",
        "bytes-v1",
        PrivacyClassification.PUBLIC,
        locator,
    )

    assert ref.store_version == "fs-1"
    assert ref.store_generation == "fs-1"
    assert locator.path == f"objects/{'c' * 64}"
    assert locator.store_generation == "fs-1"

    mapping = ref.to_mapping()
    assert ArtifactReference.from_mapping(mapping) == ref
    public_map = ref.to_public_mapping()
    assert "locator" not in public_map
    assert ArtifactReference.from_semantic_mapping(public_map).content_digest == digest

    assert ref.with_store_version("fs-2").store_version == "fs-2"
    new_loc = ArtifactLocator("object", f"tenant-neutral/{'c' * 64}", "obj-1")
    assert ref.with_locator(new_loc).locator == new_loc

    with pytest.raises(ValueError, match="artifact size"):
        ArtifactReference(digest, -1, "a/b", "fmt", PrivacyClassification.PUBLIC, locator)
    with pytest.raises(ValueError, match="artifact size"):
        ArtifactReference(digest, MAX_ARTIFACT_SIZE + 1, "a/b", "fmt", PrivacyClassification.PUBLIC, locator)
    with pytest.raises(ValueError, match="content digest"):
        ArtifactReference("md5:123", 10, "a/b", "fmt", PrivacyClassification.PUBLIC, locator)
    with pytest.raises(ValueError, match="media type"):
        ArtifactReference(digest, 10, "bad media type with spaces", "fmt", PrivacyClassification.PUBLIC, locator)
    with pytest.raises(ValueError, match="record format"):
        ArtifactReference(digest, 10, "a/b", "bad format spaces", PrivacyClassification.PUBLIC, locator)

    ref2 = ArtifactReference(digest, 10, "application/octet-stream", "bytes-v1", PrivacyClassification.PUBLIC, new_loc)
    assert ref == ref2
    assert hash(ref) == hash(ref2)
    assert ref != object()
    with pytest.raises(TypeError):
        _ = ref < object()
