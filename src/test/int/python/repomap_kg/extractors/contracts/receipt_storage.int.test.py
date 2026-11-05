"""ADR 0154 real-filesystem receipt storage, refusal and bounds.

Every case uses a fresh temporary directory and public-safe fixture data.
No target repository code is executed.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from common_lore_index.extractors.contracts.bounded_io import (
    BoundedIOError,
    open_child_directory,
    open_directory,
    read_regular_file,
    remove_owned_file,
    write_new_regular_file,
)
from common_lore_index.extractors.contracts.receipt_codec import (
    MAX_RECEIPT_BYTES,
    encode_receipt,
    load_receipt,
    receipt_digest,
    receipt_file_name,
    store_receipt,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from repomap_test_support.extractor_contracts.receipt_fixtures import (
    canonical,
    declared_receipt,
    receipt,
)


@pytest.fixture
def store() -> Iterator[tuple[int, Path]]:
    with tempfile.TemporaryDirectory(prefix="cloe-receipts-") as temporary:
        root = Path(temporary) / "receipts"
        root.mkdir(mode=0o700)
        fd = open_directory(root)
        try:
            yield fd, root
        finally:
            os.close(fd)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def test_round_trip_is_exclusive_private_and_digest_named(store: tuple[int, Path]) -> None:
    fd, root = store
    value = receipt()
    digest = store_receipt(fd, value)
    path = root / receipt_file_name(digest)
    assert path.read_bytes() == encode_receipt(value)
    assert receipt_digest(path.read_bytes()) == digest
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_receipt(fd, digest) == value
    with pytest.raises(BoundedIOError) as raised:
        store_receipt(fd, value)
    assert raised.value.code == "target_exists"
    assert load_receipt(fd, store_receipt(fd, declared_receipt())) == declared_receipt()
    assert len(list(root.iterdir())) == 2


def test_shared_descriptor_cannot_bypass_private_directory_admission(
    store: tuple[int, Path],
) -> None:
    fd, root = store
    identity = write_new_regular_file(fd, "owned.json", b"original", max_bytes=16)
    root.chmod(0o777)
    try:
        for action in (
            lambda: read_regular_file(fd, "owned.json", max_bytes=16),
            lambda: write_new_regular_file(fd, "new.json", b"x", max_bytes=16),
            lambda: remove_owned_file(fd, "owned.json", identity),
            lambda: open_child_directory(fd, "child"),
        ):
            with pytest.raises(BoundedIOError) as raised:
                action()
            assert raised.value.code == "unsafe_directory"
        assert (root / "owned.json").read_bytes() == b"original"
        assert not (root / "new.json").exists()
    finally:
        root.chmod(0o700)
    assert read_regular_file(fd, "owned.json", max_bytes=16) == b"original"


def test_existing_foreign_targets_are_refused_and_untouched(store: tuple[int, Path]) -> None:
    fd, root = store
    with tempfile.TemporaryDirectory(prefix="cloe-outside-") as outside_dir:
        outside = Path(outside_dir) / "outside.json"
        outside.write_bytes(b"outside-owner")
        data = encode_receipt(receipt())
        name = receipt_file_name(receipt_digest(data))
        (root / name).symlink_to(outside)
        for target in (name, "foreign.json"):
            if target == "foreign.json":
                (root / target).write_bytes(b"foreign-owner")
            with pytest.raises(BoundedIOError) as raised:
                write_new_regular_file(fd, target, data, max_bytes=MAX_RECEIPT_BYTES)
            assert raised.value.code == "target_exists"
        with pytest.raises(BoundedIOError) as raised:
            load_receipt(fd, receipt_digest(data))
        assert raised.value.code == "symlink_refused"
        assert outside.read_bytes() == b"outside-owner"
        assert (root / "foreign.json").read_bytes() == b"foreign-owner"
        assert (root / name).is_symlink()


def test_directory_symlinks_and_traversal_are_refused(store: tuple[int, Path]) -> None:
    fd, root = store
    (root / "real").mkdir(mode=0o700)
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    with pytest.raises(BoundedIOError) as raised:
        open_directory(root / "link")
    assert raised.value.code == "symlink_refused"
    with pytest.raises(BoundedIOError) as raised:
        open_child_directory(fd, "link")
    assert raised.value.code == "symlink_refused"
    child = open_child_directory(fd, "real")
    try:
        write_new_regular_file(child, "inside.json", b"{}", max_bytes=16)
    finally:
        os.close(child)
    assert (root / "real" / "inside.json").read_bytes() == b"{}"
    for name in ("../escape.json", "real/inside.json", "..", "."):
        with pytest.raises(BoundedIOError) as raised:
            write_new_regular_file(fd, name, b"{}", max_bytes=16)
        assert raised.value.code == "invalid_name"
    assert not (root.parent / "escape.json").exists()


def test_byte_bounds_refuse_without_partial_files(store: tuple[int, Path]) -> None:
    fd, root = store
    with pytest.raises(BoundedIOError) as raised:
        write_new_regular_file(fd, "big.json", b"x" * 17, max_bytes=16)
    assert raised.value.code == "oversized"
    assert not (root / "big.json").exists()
    (root / "big.json").write_bytes(b"x" * (MAX_RECEIPT_BYTES + 1))
    with pytest.raises(BoundedIOError) as raised:
        read_regular_file(fd, "big.json", max_bytes=MAX_RECEIPT_BYTES)
    assert raised.value.code == "oversized"


def test_non_regular_and_linked_files_are_refused(store: tuple[int, Path]) -> None:
    fd, root = store
    os.mkfifo(root / "pipe.json")
    (root / "dir.json").mkdir()
    (root / "one.json").write_bytes(b"{}")
    os.link(root / "one.json", root / "two.json")
    for name, code in (("pipe.json", "not_regular"), ("dir.json", "not_regular"),
                       ("two.json", "linked_file"), ("absent.json", "missing")):
        with pytest.raises(BoundedIOError) as raised:
            read_regular_file(fd, name, max_bytes=64)
        assert raised.value.code == code, name


@pytest.mark.parametrize("data,code", [
    (b'{"schema":"cloe-extractor-run-receipt-v1","schema":"x"}', "duplicate_key"),
    (b'{"exit_status":NaN}', "non_finite_number"),
    (b"[[[[[[[[]]]]]]]]", "too_deep"),
    (b"not json", "invalid_json"),
])
def test_malformed_stored_receipts_refuse_with_codes(
    store: tuple[int, Path], data: bytes, code: str
) -> None:
    fd, _ = store
    digest = receipt_digest(data)
    write_new_regular_file(fd, receipt_file_name(digest), data, max_bytes=MAX_RECEIPT_BYTES)
    with pytest.raises(ContractError) as raised:
        load_receipt(fd, digest)
    assert raised.value.code == code


def test_tampered_or_unknown_field_receipts_refuse(store: tuple[int, Path]) -> None:
    fd, root = store
    payload = json.loads(encode_receipt(receipt()))
    payload["observed"]["verification"] = "verified"
    forged = canonical(payload)
    forged_digest = receipt_digest(forged)
    write_new_regular_file(fd, receipt_file_name(forged_digest), forged, max_bytes=MAX_RECEIPT_BYTES)
    with pytest.raises(ContractError) as raised:
        load_receipt(fd, forged_digest)
    assert raised.value.code == "invalid_observed"
    digest = store_receipt(fd, receipt())
    path = root / receipt_file_name(digest)
    path.chmod(0o600)
    original = path.read_bytes()
    path.unlink()
    path.write_bytes(original.replace(b"run-0001", b"run-0002"))
    with pytest.raises(ContractError) as raised:
        load_receipt(fd, digest)
    assert raised.value.code == "digest_mismatch"
    assert _snapshot(root)[path.name] != original
