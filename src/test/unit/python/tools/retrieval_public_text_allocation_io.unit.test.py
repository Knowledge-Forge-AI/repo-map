"""Receipt custody: canonical finite bytes, sealing, 0700/0600 custody and spent writes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import retrieval_public_text_allocation_io as io_owner
from retrieval_public_text_allocation_io import (
    LOCK_NAME, MAX_RECEIPT_BYTES, AllocationRefused, canonical_receipt_bytes, locked_root, read_receipt,
    receipt_digest, seal_receipt, write_receipt,
)

ALLOWED = frozenset({"a.json", "b.json"})


def test_canonical_bytes_are_sorted_ascii_and_refuse_nonfinite_or_foreign_values() -> None:
    assert canonical_receipt_bytes({"b": [1, None], "a": "\u00e9"}) == b'{"a":"\\u00e9","b":[1,null]}\n'
    for value in ({"x": 1.5}, {"x": float("nan")}, {1: "key"}, {"x": object()}, {"x": b"raw"}):
        with pytest.raises(ValueError):
            canonical_receipt_bytes(value)


def test_seal_binds_digest_over_body_without_the_field() -> None:
    sealed = seal_receipt({"kind": "x", "receipt_sha256": "stale"})
    body = canonical_receipt_bytes({"kind": "x"})
    assert sealed == canonical_receipt_bytes({"kind": "x", "receipt_sha256": receipt_digest(body)})


def test_write_then_read_round_trips_and_second_write_is_spent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    with locked_root(root, create=True, allowed=ALLOWED) as path:
        record = write_receipt(path, "a.json", {"kind": "first"})
        assert read_receipt(path, "a.json") == record
        assert read_receipt(path, "b.json") is None
        with pytest.raises(AllocationRefused):
            write_receipt(path, "a.json", {"kind": "second"})
    assert os.stat(root / "a.json").st_mode & 0o777 == 0o600
    assert os.stat(root).st_mode & 0o777 == 0o700
    assert (root / LOCK_NAME).exists()


def test_root_custody_refusals(tmp_path: Path) -> None:
    with pytest.raises(AllocationRefused):
        with locked_root(Path("relative"), create=True, allowed=ALLOWED):
            pass
    with pytest.raises(AllocationRefused):
        with locked_root(tmp_path / "missing", create=False, allowed=ALLOWED):
            pass
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o755)
    with pytest.raises(AllocationRefused):
        with locked_root(loose, create=False, allowed=ALLOWED):
            pass
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(AllocationRefused):
        with locked_root(tmp_path / "link", create=False, allowed=ALLOWED):
            pass
    (target / "foreign.json").write_bytes(b"{}")
    (target / "foreign.json").chmod(0o600)
    with pytest.raises(AllocationRefused):
        with locked_root(target, create=False, allowed=ALLOWED):
            pass


@pytest.mark.parametrize("raw", [
    b'{"kind":"x"', b'{"kind":"x"}\n', b'{"kind": "x", "receipt_sha256": "x"}\n', b"\xff\n", b"[]\n",
])
def test_torn_noncanonical_unsealed_or_non_object_receipts_refuse(tmp_path: Path, raw: bytes) -> None:
    root = tmp_path / "root"
    with locked_root(root, create=True, allowed=ALLOWED) as path:
        (path / "a.json").write_bytes(raw)
        (path / "a.json").chmod(0o600)
        with pytest.raises(AllocationRefused):
            read_receipt(path, "a.json")


def test_digest_mismatch_and_oversize_receipts_refuse(tmp_path: Path) -> None:
    root = tmp_path / "root"
    with locked_root(root, create=True, allowed=ALLOWED) as path:
        forged = canonical_receipt_bytes({"kind": "x", "receipt_sha256": "sha256:" + "0" * 64})
        (path / "a.json").write_bytes(forged)
        (path / "a.json").chmod(0o600)
        with pytest.raises(AllocationRefused):
            read_receipt(path, "a.json")
        (path / "b.json").write_bytes(b" " * (MAX_RECEIPT_BYTES + 1))
        (path / "b.json").chmod(0o600)
        with pytest.raises(AllocationRefused):
            read_receipt(path, "b.json")
        with pytest.raises(AllocationRefused):
            write_receipt(path, "b.json", {"blob": "x" * MAX_RECEIPT_BYTES})


def test_failed_write_leaves_the_receipt_spent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    with locked_root(root, create=True, allowed=ALLOWED) as path:
        def broken_fsync(_descriptor: int) -> None:
            raise OSError("disk")

        monkeypatch.setattr(io_owner.os, "fsync", broken_fsync)
        with pytest.raises(AllocationRefused, match="remains spent"):
            write_receipt(path, "a.json", {"kind": "x"})
        monkeypatch.undo()
        assert (path / "a.json").exists()
        with pytest.raises(AllocationRefused):
            write_receipt(path, "a.json", {"kind": "retry"})
